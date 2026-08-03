"""Proxy generation — re-encode videos to short-GOP scrub-friendly proxies."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from avialsync.runtime import no_window_kwargs


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
    """Background worker that re-encodes a video to a short-GOP proxy.

    Uses ffmpeg with keyint=1 (every frame is a keyframe) for instant
    scrubbing, scaled to 720p, fast preset.
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

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-vf",
            "scale=-2:720",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-g",
            "1",
            "-an",
            "-movflags",
            "+faststart",
            str(tmp),
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **no_window_kwargs(),
            )
            self._proc = proc

            while proc.poll() is None:
                if self._cancel:
                    proc.kill()
                    proc.wait()
                    tmp.unlink(missing_ok=True)
                    return
                import time

                time.sleep(0.25)

            stderr = proc.stderr.read() if proc.stderr else b""

            if proc.returncode != 0:
                err = stderr.decode(errors="replace")[-500:]
                self.error.emit(f"ffmpeg failed:\n{err}")
                tmp.unlink(missing_ok=True)
                return

            tmp.replace(dst)
            self.progress.emit(100)
            self.finished.emit(str(src), str(dst))

        except FileNotFoundError:
            self.error.emit("ffmpeg not found. Install ffmpeg to generate proxies.")
        except Exception as e:
            tmp.unlink(missing_ok=True)
            self.error.emit(str(e))
