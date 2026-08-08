"""Standard Video Loader."""

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np

from avialsync.core.cache import CacheManager
from avialsync.core.errors import CacheError, SourceOpenError
from avialsync.core.source import VideoMetadata, VideoSource

logger = logging.getLogger(__name__)

_VIDEO_FRAME_CACHE_VERSION = 1
_FRAME_TIMES_NAME = "video_frame_times.npy"

#: Divisor turning a sidecar's integer timestamps into seconds.  Machine-vision
#: cameras stamp a free-running nanosecond counter, which is why only the
#: *differences* between rows are used and the absolute value is discarded.
_SIDECAR_NANOSECONDS = 1e9


@dataclass(frozen=True)
class RecordedFrames:
    """Per-frame exposure evidence read from a capture sidecar."""

    #: Exposure time of each stored frame, in seconds from the first.
    times: np.ndarray

    #: Exposures the camera counted but did not store.  Derived from the frame
    #: counter, which is the only thing that proves they existed: the timestamps
    #: alone cannot distinguish "a frame was dropped here" from "the camera ran
    #: slower here", and on one real recording that was 9 073 frames — a quarter
    #: of the take — invisible in every other field.
    dropped: int = 0


def read_frame_timestamps(sidecar: Path) -> RecordedFrames | None:
    """Return per-frame exposure evidence from a ``frame_number,timestamp`` sidecar.

    Both columns matter.  The timestamps place every stored frame on the
    timeline; the counter says how many exposures never reached the file, which
    no other field in the recording records.

    Returns ``None`` rather than raising for anything unreadable: a missing or
    malformed sidecar costs exact timing, which is a degraded import, while a
    raised error would cost the video entirely.
    """
    try:
        if sidecar.stat().st_size == 0:
            logger.warning("Frame timestamp sidecar %s is empty.", sidecar)
            return None
        raw = np.loadtxt(sidecar, delimiter=",", dtype=np.float64, ndmin=2)
    except (OSError, ValueError):
        logger.warning("Cannot parse frame timestamp sidecar %s", sidecar, exc_info=True)
        return None
    if raw.size == 0 or raw.ndim != 2 or raw.shape[1] < 2:
        logger.warning("Frame timestamp sidecar %s has no timestamp column.", sidecar)
        return None

    times: np.ndarray = np.asarray(raw[:, 1], dtype=np.float64) / _SIDECAR_NANOSECONDS
    if len(times) < 2 or not np.all(np.isfinite(times)):
        logger.warning("Frame timestamp sidecar %s holds no usable timestamps.", sidecar)
        return None
    if np.any(np.diff(times) <= 0):
        logger.warning("Frame timestamps in %s are not strictly increasing.", sidecar)
        return None
    rebased: np.ndarray = times - times[0]

    counter = np.asarray(raw[:, 0], dtype=np.float64)
    steps = np.diff(counter)
    # A step of one is consecutive; anything larger is that many lost exposures.
    # Guarded against a counter that wraps or restarts, which would otherwise
    # report a negative or absurd loss.
    dropped = int(np.sum(steps[steps > 1] - 1)) if len(steps) and np.all(steps > 0) else 0
    return RecordedFrames(times=rebased, dropped=dropped)


class VideoStandardLoader(VideoSource):
    """Loads standard videos, probing metadata and frame timing with PyAV."""

    @classmethod
    def display_name(cls) -> str:
        return "Video"

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}
        self._start_time: float | None = None
        self._fps: float = 30.0
        self._frame_times: np.ndarray | None = None
        self._timing_stats_source: np.ndarray | None = None
        self._timing_stats: tuple[bool, float, float, float] = (False, 30.0, 30.0, 30.0)
        # Extended metadata (D-020) — all probed from the container with PyAV
        self._codec: str = "unknown"
        self._duration: float = 0.0
        self._container: str = ""
        self._width: int = 0
        self._height: int = 0
        self._pix_fmt: str = ""
        self._profile: str = ""
        self._frame_count: int | None = None
        self._file_size: int = 0
        # Per-frame timing supplied by the acquisition system, when it recorded
        # any.  Config-driven and never auto-discovered: a same-stem CSV beside a
        # video is at least as likely to be pose output as a timestamp log.
        self._exact_master: np.ndarray | None = None
        self._exact_source: np.ndarray | None = None
        self._dropped_frames: int = 0

    @classmethod
    def can_open(cls, path: Path) -> float:
        suffix = path.suffix.lower()
        if suffix in [".mp4", ".mov", ".mkv", ".avi", ".webm"]:
            # Could open the container here to verify, but the extension is faster
            return 0.9
        return 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        self._path = path
        self._config = config
        self._probe_metadata(path)

        # Frame timestamps are correctness evidence for VFR, stepping, and exact
        # trigger alignment.  Cache them once: building the table is O(frames).
        self._frame_times = self._load_cached_frame_times(path)
        if self._frame_times is None:
            self._extract_frame_times(path)
            if self._frame_times is not None:
                self._save_frame_times_cache(path, self._frame_times)
        # Override FPS and scale timestamps if explicitly requested (e.g. by a session plugin)
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
        self._bind_recorded_frame_times(config)

    def _probe_metadata(self, path: Path) -> None:
        """Read container and stream metadata with PyAV.

        This used to shell out to ``ffprobe`` and parse its JSON.  PyAV reads
        the same fields from the same FFmpeg libraries in-process, so the media
        runtime no longer has to exist on the machine (D-075) and a four-camera
        session stops paying four process launches.

        Nothing here decodes: opening a container reads headers only.
        """
        import av

        try:
            container = av.open(str(path))
        except (av.FFmpegError, OSError) as error:
            raise SourceOpenError(f"Failed to probe video: {path} ({error})") from error

        try:
            self._container = (container.format.name or "").split(",")[0]
            # Container timings are in microseconds on FFmpeg's own time base,
            # not the stream's. A container that declares neither is normal for
            # a raw stream; the frame table below is the authority regardless.
            if container.start_time is not None:
                self._start_time = container.start_time / 1_000_000.0
            self._duration = (container.duration or 0) / 1_000_000.0
            self._file_size = path.stat().st_size

            try:
                stream = container.streams.video[0]
            except IndexError:
                self._codec = "unknown"
                return

            codec_context = stream.codec_context
            self._codec = codec_context.name or "unknown"
            self._profile = codec_context.profile or ""
            self._pix_fmt = codec_context.pix_fmt or ""
            self._width = int(codec_context.width or 0)
            self._height = int(codec_context.height or 0)
            # ``base_rate`` is ffprobe's ``r_frame_rate``: the container's
            # declared rate, which for VFR media is a claim the frame
            # timestamps below routinely contradict (D-072).
            if stream.base_rate:
                self._fps = float(stream.base_rate)
            self._frame_count = int(stream.frames) or None
        finally:
            container.close()

    def _bind_recorded_frame_times(self, config: dict[str, Any]) -> None:
        """Adopt per-frame exposure times the acquisition system recorded, if given.

        A container declares a constant nominal rate whether or not the camera
        achieved it, so a capture that free-ran at 45.8 Hz and dropped frames
        still arrives labelled 30 fps CFR — 785 s of footage stretched across
        895 s of timeline, and no offset takes that back out because the error
        accumulates.  Correcting the *rate* is not enough either: with drops
        spread through the recording a single rate still leaves over a second of
        error at the worst frame.  The result is a per-frame mapping instead.

        Config keys:
            ``frame_timestamps``: path to a ``frame_number,timestamp`` sidecar.
            ``start_time``: master time of the first recorded frame (default 0).
        """
        sidecar_value = config.get("frame_timestamps")
        if not sidecar_value:
            return
        sidecar = Path(sidecar_value)
        evidence = read_frame_timestamps(sidecar)
        if evidence is None:
            return
        recorded = evidence.times
        self._dropped_frames = evidence.dropped
        source = self._frame_times
        if source is None or len(source) < 2:
            logger.warning(
                "No container frame timestamps for %s; sidecar timing cannot be applied.",
                self._path,
            )
            return

        paired = min(len(source), len(recorded))
        if len(source) != len(recorded):
            # Pairing runs from frame zero, so a common prefix is correct for
            # every frame it covers.  Worth saying out loud: a large mismatch
            # usually means the sidecar belongs to a different take.
            logger.warning(
                "%s has %d frames but %s lists %d; timing the first %d.",
                Path(str(self._path)).name,
                len(source),
                sidecar.name,
                len(recorded),
                paired,
            )

        self._exact_source = np.asarray(source[:paired], dtype=np.float64)
        self._exact_master = recorded[:paired] + float(config.get("start_time", 0.0))
        logger.info(
            "%s timed from %s: %d frames over %.3f s (container claimed %.3f s at %.3f fps); "
            "%d exposure(s) dropped.",
            Path(str(self._path)).name,
            sidecar.name,
            paired,
            float(self._exact_master[-1] - self._exact_master[0]),
            self._duration,
            self._fps,
            self._dropped_frames,
        )

    def exact_time_mapping(self) -> tuple[np.ndarray, np.ndarray] | None:
        """Return per-frame ``(master_time, source_time)`` evidence, if recorded."""
        if self._exact_master is None or self._exact_source is None:
            return None
        return self._exact_master, self._exact_source

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
        """Build the presentation-timestamp table with the decoder's own code.

        Deliberately :class:`PyAVReader` rather than a second implementation.
        The pane decodes through that class, and the table it builds is what
        selects the frame on screen; a loader that derived its own table from
        the same file by different means would be a second authority on which
        frame is which — the exact split D-075 removed (AGENTS.md rule 6).
        Both are now literally the same code, so they cannot disagree.

        Costs one demux pass, no decode: 225 ms on a 716 MB, 13 844-frame file,
        which is why the result is cached in the sidecar beside the media.
        """
        from avialsync.engine.pyav_reader import PyAVReader

        try:
            with PyAVReader(path) as reader:
                self._frame_times = np.asarray(reader.frame_times, dtype=np.float64)
        except (SourceOpenError, OSError) as error:
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

    def _recorded_duration(self) -> float:
        """Return the span the frames actually cover, in master-time seconds."""
        if self._exact_master is None or len(self._exact_master) < 2:
            return self._duration
        return float(self._exact_master[-1] - self._exact_master[0])

    def _recorded_rate_statistics(self) -> tuple[bool, float, float, float]:
        """Return ``(is_vfr, measured, min, max)`` from whichever timing is authoritative."""
        if self._exact_master is None or len(self._exact_master) < 2:
            return self._frame_rate_statistics()
        intervals = np.diff(self._exact_master)
        intervals = intervals[intervals > 1e-9]
        if len(intervals) == 0:  # pragma: no cover - the mapping is strictly increasing
            return self._frame_rate_statistics()
        median = float(np.median(intervals))
        tolerance = max(2e-6, median * 5e-3)
        rates = 1.0 / intervals
        return (
            bool(np.any(np.abs(intervals - median) > tolerance)),
            float(len(intervals) / float(np.sum(intervals))),
            float(np.min(rates)),
            float(np.max(rates)),
        )

    def video_metadata(self) -> VideoMetadata:
        """Return timestamp-authoritative stream metadata for inspection and OSD.

        When the acquisition system recorded when each frame was exposed, the
        rate fields describe *that*, on the master timeline, and ``nominal_fps``
        keeps the container's claim beside it — which is what that field is for.
        Derived from the container's own presentation timestamps instead, a
        sidecar-timed camera read "CFR 30.000 · measured 30.000", because the
        container really is CFR: the readout could not show the very discrepancy
        the sidecar exists to correct.
        """
        is_vfr, measured, min_rate, max_rate = self._recorded_rate_statistics()
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
            duration=self._recorded_duration(),
            start_time=self._start_time,
            file_size_bytes=self._file_size,
            dropped_frames=self._dropped_frames,
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
