"""Proxy generation — re-encode videos to all-keyframe scrub-friendly proxies."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from avialsync.engine.transcode import TranscodeCancelled, encode_proxy

logger = logging.getLogger(__name__)


def proxy_path_for(video_path: Path) -> Path:
    """Return the sidecar proxy path for a given video."""
    return video_path.parent / f"{video_path.stem}_proxy.mp4"


def needs_proxy(video_path: Path) -> bool:
    """Check if a proxy already exists and is newer than the source."""
    pp = proxy_path_for(video_path)
    if not pp.exists():
        return True
    return pp.stat().st_mtime < video_path.stat().st_mtime


class ProxyWorker(QObject):
    """Background worker that re-encodes a video to an all-keyframe proxy.

    Every frame is a keyframe, so a seek into a proxy never decodes forward and
    costs one frame wherever it lands. Encoded in-process with PyAV, so a proxy
    can be built on a machine with no media runtime installed (D-075).

    Cancellation is cooperative and checked once per frame, rather than by
    killing a child process. The partial file is removed either way: a truncated
    proxy that outlived its cancellation would be picked up as a finished one.
    """

    progress = Signal(int)  # 0–100
    finished = Signal(str, str)  # original_path, proxy_path
    error = Signal(str)

    def __init__(self, video_path: Path) -> None:
        super().__init__()
        self._video_path = video_path
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        src = self._video_path
        dst = proxy_path_for(src)
        tmp = dst.with_suffix(".tmp.mp4")

        try:
            encode_proxy(
                src,
                tmp,
                progress=lambda fraction: self.progress.emit(int(fraction * 100)),
                should_cancel=lambda: self._cancel,
            )
        except TranscodeCancelled:
            tmp.unlink(missing_ok=True)
            return
        except Exception as error:
            tmp.unlink(missing_ok=True)
            logger.warning("Proxy generation failed for %s", src, exc_info=True)
            self.error.emit(f"Could not build a proxy for {src.name}: {error}")
            return

        # Published only once it is complete, so a reader can never open a
        # proxy that is still being written.
        tmp.replace(dst)
        self.progress.emit(100)
        self.finished.emit(str(src), str(dst))
