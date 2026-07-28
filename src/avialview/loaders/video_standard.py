"""Standard Video Loader."""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from avialview.core.source import VideoSource
from avialview.runtime import MediaRuntimeError, require_ffprobe


class VideoStandardLoader(VideoSource):
    """Loads standard videos utilizing ffprobe metadata."""

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}
        self._start_time: float | None = None
        self._fps: float = 30.0
        self._frame_times: np.ndarray | None = None
        # Extended metadata (D-020) — all probed from the existing ffprobe JSON
        self._codec: str = "unknown"
        self._duration: float = 0.0
        self._container: str = ""
        self._width: int = 0
        self._height: int = 0
        self._pix_fmt: str = ""
        self._profile: str = ""
        self._frame_count: int | None = None
        self._file_size: int = 0

    @classmethod
    def can_open(cls, path: Path) -> float:
        suffix = path.suffix.lower()
        if suffix in [".mp4", ".mov", ".mkv", ".avi", ".webm"]:
            # Could run ffprobe here to verify, but checking extension is faster
            return 0.9
        return 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        self._path = path
        self._config = config

        # Probe metadata
        cmd = [
            str(require_ffprobe()),
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            meta = json.loads(result.stdout)
        except MediaRuntimeError as e:
            raise ValueError(str(e)) from e
        except (json.JSONDecodeError, subprocess.CalledProcessError) as e:
            raise ValueError(f"Failed to probe video: {path}") from e

        format_info = meta.get("format", {})

        # Parse start_time and duration from format
        st = format_info.get("start_time")
        if st is not None:
            self._start_time = float(st)

        d = format_info.get("duration")
        self._duration = float(d) if d is not None else 0.0
        self._container = format_info.get("format_name", "").split(",")[0]
        size_str = format_info.get("size")
        self._file_size = int(size_str) if size_str else 0

        # Parse fields from first video stream
        streams = meta.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)

        if video_stream:
            self._codec = video_stream.get("codec_name", "unknown")
            r_frame_rate = video_stream.get("r_frame_rate", "0/0")
            num, den = r_frame_rate.split("/")
            if float(den) > 0:
                self._fps = float(num) / float(den)
            self._width = int(video_stream.get("width", 0))
            self._height = int(video_stream.get("height", 0))
            self._pix_fmt = video_stream.get("pix_fmt", "")
            self._profile = video_stream.get("profile", "")
            nb = video_stream.get("nb_frames")
            self._frame_count = int(nb) if nb and nb != "N/A" else None
        else:
            self._codec = "unknown"

        # Parse frame times (to ensure correct frame stepping for VFR/dropped-frames)
        # Note: This is an expensive operation for large videos, so we could defer it
        # However, for correct stepping we need it
        self._extract_frame_times(path)

    def _extract_frame_times(self, path: Path) -> None:
        cmd = [
            str(require_ffprobe()),
            "-v",
            "quiet",
            "-select_streams",
            "v:0",
            "-show_entries",
            # Packet order follows decode order for codecs with B-frames.  Frame
            # timestamps are presentation-order timestamps, which are the only
            # timestamps suitable for stepping and VFR detection.
            "frame=best_effort_timestamp_time",
            "-of",
            "csv=p=0",
            str(path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            times = []
            for line in result.stdout.strip().split("\n"):
                value = line.split(",", maxsplit=1)[0].strip()
                if value:
                    try:
                        times.append(float(value))
                    except ValueError:
                        pass
            if times:
                self._frame_times = np.array(times)
        except Exception:
            self._frame_times = None

    def needs_conversion(self) -> bool:
        return False

    def prepare(self, progress_cb: Callable[[float], None]) -> Path:
        if self._path is None:
            raise RuntimeError("Source not opened")
        return self._path

    def media_path(self) -> Path:
        if self._path is None:
            raise RuntimeError("Source not opened")
        return self._path

    def start_time(self) -> float | None:
        return self._start_time

    def frame_times(self) -> np.ndarray | None:
        return self._frame_times

    def is_vfr(self) -> bool:
        """Return whether decoded frame timestamps have variable intervals."""
        if self._frame_times is None or len(self._frame_times) < 3:
            return False
        intervals = np.diff(np.sort(self._frame_times))
        intervals = intervals[intervals > 1e-9]
        if len(intervals) < 2:
            return False
        return not np.allclose(intervals, np.median(intervals), rtol=1e-3, atol=1e-6)

    def time_bounds(self) -> tuple[float, float]:
        st = self._start_time or 0.0
        return (st, st + getattr(self, "_duration", 0.0))

    def fps(self) -> float:
        return self._fps

    def label(self) -> str:
        if self._path is None:
            return "Unknown"
        return self._path.name
