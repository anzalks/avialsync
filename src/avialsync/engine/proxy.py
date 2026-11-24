"""Proxy generation — re-encode videos to all-keyframe scrub-friendly proxies."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from avialsync.core.artifact_io import publish
from avialsync.core.sidecar_names import on_disk
from avialsync.engine.transcode import TranscodeCancelled, encode_proxy, expanded_media_sources

logger = logging.getLogger(__name__)


def proxy_path_for(video_path: Path) -> Path:
    """Return where a proxy for *video_path* is offered: beside it, as a video.

    Not in the cache, although it is derived: a proxy is a file the user asked
    for and opens as a recording of its own, so it has to be where they look.
    It is only the *suggestion* in a Save dialog: nothing is written into a
    recording's folder without the user choosing that place (D-244).
    """
    disk_path = on_disk(video_path)
    return disk_path.parent / f"{disk_path.stem}_proxy.mp4"


def needs_proxy(video_path: Path) -> bool:
    """Check if a proxy already exists and is newer than the source."""
    pp = proxy_path_for(video_path)
    if not pp.exists():
        return True
    ref = video_path.parent if video_path.parent.is_file() else video_path
    return pp.stat().st_mtime < ref.stat().st_mtime


class ProxyWorker(QObject):
    """Background worker that re-encodes a video to an all-keyframe proxy.

    Every frame is a keyframe, so a seek into a proxy never decodes forward and
    costs one frame wherever it lands. Encoded in-process with PyAV, so a proxy
    can be built on a machine with no media runtime installed.

    Cancellation is cooperative and checked once per frame, rather than by
    killing a child process. The partial file is removed either way: a truncated
    proxy that outlived its cancellation would be picked up as a finished one.
    """

    progress = Signal(int)  # 0–100
    finished = Signal(str, str)  # original_path, proxy_path
    error = Signal(str)

    def __init__(
        self,
        video_path: Path,
        destination: Path | None = None,
        sources: Iterable[Path | str] = (),
        media_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._video_path = video_path
        self._destination = destination
        self._sources = tuple(sources)
        self._media_path = media_path
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        src = self._video_path
        media_src = self._media_path or src
        dst = self._destination or proxy_path_for(src)
        protected = expanded_media_sources(media_src, (src, *self._sources))

        try:
            publish(
                dst,
                lambda tmp: encode_proxy(
                    media_src,
                    tmp,
                    progress=lambda fraction: self.progress.emit(int(fraction * 100)),
                    should_cancel=lambda: self._cancel,
                ),
                kind="proxy",
                sources=protected,
            )
        except TranscodeCancelled:
            return
        except Exception as error:
            logger.warning("Proxy generation failed for %s", src, exc_info=True)
            self.error.emit(f"Could not build a proxy for {src.name}: {error}")
            return

        self.progress.emit(100)
        self.finished.emit(str(src), str(dst))
