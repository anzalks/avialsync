"""Standard Video Loader."""

import json
import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import numpy as np

from avialsync.core.cache import CacheManager
from avialsync.core.errors import CacheError, SourceOpenError
from avialsync.core.source import VideoMetadata, VideoSource
from avialsync.runtime import MediaRuntimeError, no_window_kwargs, require_ffprobe

logger = logging.getLogger(__name__)

_VIDEO_FRAME_CACHE_VERSION = 1
_FRAME_TIMES_NAME = "video_frame_times.npy"


class VideoStandardLoader(VideoSource):
    """Loads standard videos utilizing ffprobe metadata."""

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}
        self._start_time: float | None = None
        self._fps: float = 30.0
        self._frame_times: np.ndarray | None = None
        self._timing_stats_source: np.ndarray | None = None
        self._timing_stats: tuple[bool, float, float, float] = (False, 30.0, 30.0, 30.0)
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
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True, **no_window_kwargs()
            )
            meta = json.loads(result.stdout)
        except MediaRuntimeError as e:
            raise SourceOpenError(str(e)) from e
        except (json.JSONDecodeError, subprocess.CalledProcessError) as e:
            raise SourceOpenError(f"Failed to probe video: {path}") from e

        format_info = meta.get("format", {})

        # Parse start_time and duration from format
        st = format_info.get("start_time")
        if st is not None:
            self._start_time = float(st)

        d = format_info.get("duration")
        self._duration = float(d) if d is not None else 0.0
        self._container = format_info.get("format_name", "").split(",")[0]
        size_str = format_info.get("size")
        self._file_size = int(size_str) if size_str else path.stat().st_size

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

        # Frame timestamps are correctness evidence for VFR, stepping, and exact
        # trigger alignment.  Cache them once because ffprobe output is O(frames).
        self._frame_times = self._load_cached_frame_times(path)
        if self._frame_times is None:
            self._extract_frame_times(path)
            if self._frame_times is not None:
                self._save_frame_times_cache(path, self._frame_times)
        # Override FPS and scale timestamps if explicitly requested (e.g. by AOL session)
        override_fps = self._config.get("fps")
        if override_fps is not None and override_fps > 0 and self._fps > 0:
            scale = self._fps / float(override_fps)
            self._fps = float(override_fps)
            self._duration *= scale
            if self._frame_times is not None:
                self._frame_times = self._frame_times * scale

        if self._frame_count is None and self._frame_times is not None:
            self._frame_count = len(self._frame_times)
        self._frame_rate_statistics()

    @staticmethod
    def _cache_manager() -> CacheManager:
        return CacheManager(loader_version=_VIDEO_FRAME_CACHE_VERSION)

    def _load_cached_frame_times(self, path: Path) -> np.ndarray | None:
        manager = self._cache_manager()
        cache_path = manager.get_cache_dir(path) / _FRAME_TIMES_NAME
        if not manager.is_cache_valid(path) or not cache_path.is_file():
            return None
        try:
            times = np.load(cache_path, mmap_mode="r", allow_pickle=False)
        except (OSError, ValueError):
            logger.warning("Ignoring invalid video timestamp cache for %s", path, exc_info=True)
            return None
        if times.ndim != 1 or len(times) == 0 or not np.all(np.isfinite(times)):
            return None
        if len(times) > 1 and np.any(np.diff(times) <= 0):
            return None
        return cast(np.ndarray, times)

    def _save_frame_times_cache(self, path: Path, frame_times: np.ndarray) -> None:
        manager = self._cache_manager()
        temp_dir = manager.get_temp_cache_dir(path)
        try:
            np.save(temp_dir / _FRAME_TIMES_NAME, frame_times, allow_pickle=False)
            manager.commit_cache(path, temp_dir)
        except (CacheError, OSError):
            # Timestamp caching is an optimization.  Read-only acquisition
            # media must remain loadable with the in-memory evidence.
            logger.warning("Could not cache video frame timestamps for %s", path, exc_info=True)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _extract_frame_times(self, path: Path) -> None:
        cmd = [
            str(require_ffprobe()),
            "-v",
            "quiet",
            "-select_streams",
            "v:0",
            "-show_entries",
            # Packet order follows decode order for codecs with B-frames.
            # We extract packet PTS which is much faster than decoding frame metadata,
            # and sort the resulting array to recover the presentation-order timestamps.
            "packet=pts_time",
            "-of",
            "csv=p=0",
            str(path),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True, **no_window_kwargs()
            )
            times = []
            for line in result.stdout.strip().split("\n"):
                value = line.split(",", maxsplit=1)[0].strip()
                if value:
                    try:
                        times.append(float(value))
                    except ValueError:
                        pass
            if times:
                self._frame_times = np.unique(np.asarray(times, dtype=np.float64))
        except (MediaRuntimeError, OSError, subprocess.CalledProcessError) as error:
            logger.warning("Failed to extract frame times for %s: %s", path, error)
            self._frame_times = None

        if self._frame_times is None or len(self._frame_times) == 0:
            logger.warning("Frame times empty or extraction failed for %s", path)

    def needs_conversion(self) -> bool:
        return False

    def prepare(self, progress_cb: Callable[[float], None]) -> Path:
        if self._path is None:
            raise SourceOpenError("Video source has not been opened.")
        return self._path

    def media_path(self) -> Path:
        if self._path is None:
            raise SourceOpenError("Video source has not been opened.")
        return self._path

    def start_time(self) -> float | None:
        return self._start_time

    def frame_times(self) -> np.ndarray | None:
        return self._frame_times

    def is_vfr(self) -> bool:
        """Return whether decoded frame timestamps have variable intervals."""
        return self._frame_rate_statistics()[0]

    def _frame_rate_statistics(self) -> tuple[bool, float, float, float]:
        if self._timing_stats_source is self._frame_times:
            return self._timing_stats
        if self._frame_times is None or len(self._frame_times) < 2:
            stats = (False, self._fps, self._fps, self._fps)
        else:
            intervals = np.diff(self._frame_times)
            intervals = intervals[intervals > 1e-9]
            if len(intervals) == 0:
                stats = (False, self._fps, self._fps, self._fps)
            else:
                median_interval = float(np.median(intervals))
                tolerance = max(2e-6, median_interval * 5e-3)
                is_vfr = bool(np.any(np.abs(intervals - median_interval) > tolerance))
                measured = float(len(intervals) / np.sum(intervals))
                rates = 1.0 / intervals
                stats = (is_vfr, measured, float(np.min(rates)), float(np.max(rates)))
        self._timing_stats_source = self._frame_times
        self._timing_stats = stats
        return stats

    def video_metadata(self) -> VideoMetadata:
        """Return timestamp-authoritative stream metadata for inspection and OSD."""
        is_vfr, measured, min_rate, max_rate = self._frame_rate_statistics()
        return VideoMetadata(
            container=self._container,
            codec=self._codec,
            profile=self._profile,
            pixel_format=self._pix_fmt,
            width=self._width,
            height=self._height,
            nominal_fps=self._fps,
            measured_fps=measured,
            min_frame_rate=min_rate,
            max_frame_rate=max_rate,
            is_vfr=is_vfr,
            frame_count=self._frame_count,
            duration=self._duration,
            start_time=self._start_time,
            file_size_bytes=self._file_size,
        )

    def time_bounds(self) -> tuple[float, float]:
        st = self._start_time or 0.0
        return (st, st + getattr(self, "_duration", 0.0))

    def fps(self) -> float:
        return self._fps

    def label(self) -> str:
        if self._path is None:
            return "Unknown"
        return self._path.name
