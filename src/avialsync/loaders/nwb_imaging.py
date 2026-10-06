"""An NWB file's imaging, played as video through the application's own decoder (D-188).

Imaging inside an NWB file is an array -- frames × rows × columns, usually 16-bit
-- and the video pane plays media files through PyAV (D-075). So the frames are
written once into a **lossless proxy** in the per-user cache: FFV1 in MP4, the
pixels exactly as recorded (``gray16le`` for 16-bit data, so display levels
window the real range, D-093), each frame stamped with the series' own
timestamp as its presentation time.

That last point is what makes the timing exact without any mapping. The pane
reads the proxy's presentation timestamps (``PyAVReader``, the one authority on
which frame is which), and those *are* the NWB timestamps, to the microsecond.
MP4 rather than Matroska because Matroska rounds every timestamp to the
millisecond, which collapses voltage-imaging frames onto each other. A series
whose times start below zero -- MP4 drops frames with negative presentation
times -- is written counting from its own first frame, and the session places it
by that origin (:func:`proxy_origin`).

The proxy is built on the first open and reused afterwards, keyed on the NWB
file's size, modification time and content edges like every other cache entry,
plus the series it holds -- so it never shares, or overwrites, the entry the same
file's time series are imported into.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.cache import CacheManager, cache_dir_for, source_identity
from avialsync.core.errors import SourceOpenError
from avialsync.core.source import VideoMetadata, VideoSource
from avialsync.loaders import nwb_format, nwb_read
from avialsync.loaders.nwb_format import SeriesInfo

logger = logging.getLogger(__name__)

#: Bumped whenever the proxy's encoding changes, so an old proxy is rebuilt.
_PROXY_VERSION = 1
_PROXY_NAME = "imaging.mp4"

#: Frames read from the file per block while encoding.
_BLOCK_BYTES = 64 * 1024 * 1024

#: Microsecond presentation times: exact for any imaging rate, and what MP4
#: carries without rounding.
_TIME_BASE = Fraction(1, 1_000_000)

#: FFV1 settings. Sixteen slices let the encoder use every core (measured 48 ->
#: 240 frames/s on 512x512 16-bit frames); level 3 is what supports slices.
_FFV1_OPTIONS = {"level": "3", "slices": "16", "slicecrc": "0"}

#: How many frames are sampled to choose a scale for data that is not unsigned
#: integer (floating-point dF/F movies, signed counts).
_SCALE_SAMPLE_FRAMES = 32


def default_imaging(contents: nwb_format.FileContents) -> SeriesInfo | None:
    """The imaging series a file is shown with when nothing says otherwise.

    Raw acquisition before anything derived from it, then the longest, then by
    name -- deterministic, so a session restored without its configuration
    reopens the same series it saved.
    """
    imaging = contents.of_kind("imaging")
    if not imaging:
        return None
    return min(
        imaging,
        key=lambda info: (not info.path.startswith("/acquisition"), -info.length, info.path),
    )


def proxy_origin(first_time: float) -> float:
    """The NWB time the proxy's zero stands for: 0, unless the series starts before it."""
    return min(0.0, float(first_time))


class _ProxyCache(CacheManager):
    """A cache entry keyed on the NWB file *and* the series it holds.

    Entries are named after their source path, and the same file's time series
    already own the entry named after it. Committing a proxy there would replace
    that import, and the import would replace the proxy back.
    """

    def __init__(self, series: str) -> None:
        super().__init__(
            loader_version=_PROXY_VERSION,
            cache_config={"series": series, "codec": "ffv1", "container": "mp4"},
        )
        self._series = series

    def get_cache_dir(self, source_path: Path) -> Path:
        return cache_dir_for(f"{source_identity(source_path)}#{self._series}", self._root)


class NWBImagingSource(VideoSource):
    """Plays one imaging series of an NWB file through a cached lossless proxy."""

    @classmethod
    def display_name(cls) -> str:
        return "NWB Imaging"

    def __init__(self) -> None:
        self._path: Path | None = None
        self._info: SeriesInfo | None = None
        self._times = np.empty(0)
        #: Which stored frames are encoded: every one, unless the file's
        #: timestamps step backwards, when the frames that would play out of
        #: order are left out rather than reordered.
        self._frames = np.empty(0, dtype=np.int64)
        self._origin = 0.0
        self._proxy: Path | None = None
        self._frame_times: np.ndarray | None = None
        self._pixel_format = ""

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Claim an imaging series named inside an NWB file, or a bare NWB file.

        The session names imaging ``session.nwb/acquisition/TwoPhotonSeries``
        (:func:`nwb_format.object_path`), which nothing else can open. A bare
        ``.nwb`` scores below the time-series loader, so resolving one without
        saying which kind is wanted gets its time series.
        """
        if nwb_format.split_object_path(path) is not None:
            return 0.95
        return 0.85 if nwb_format.is_nwb_path(path) or nwb_format.is_zarr_nwb(path) else 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        named = nwb_format.split_object_path(path)
        if named is not None:
            path, series = named
            config = {**config, "series": series}
        contents = nwb_format.scan(path)
        wanted = config.get("series")
        if wanted:
            matches = [info for info in contents.of_kind("imaging") if info.path == wanted]
            info = matches[0] if matches else None
        else:
            info = default_imaging(contents)
        if info is None:
            raise SourceOpenError(
                f"{path.name} has no imaging stored in the file"
                + (f" under {wanted}." if wanted else ".")
            )
        with nwb_format.open_file(path) as handle:
            times = nwb_read.read_times(handle, info, 0, info.length)
        increasing = np.ones(len(times), dtype=bool)
        if len(times) > 1:
            increasing[1:] = times[1:] > np.maximum.accumulate(times)[:-1]
        if not np.all(increasing):
            logger.warning(
                "%s: %d frames step back in time and are left out of the proxy.",
                info.path,
                int(np.count_nonzero(~increasing)),
            )
        self._path = path
        self._info = info
        self._frames = np.flatnonzero(increasing & np.isfinite(times))
        self._times = times[self._frames]
        if len(self._times) == 0:
            raise SourceOpenError(f"{info.path} in {path.name} has no frame with a usable time.")
        self._origin = proxy_origin(float(self._times[0]))

    # ── Proxy ──────────────────────────────────────────────────────────────

    def needs_conversion(self) -> bool:
        return True

    def prepare_is_atomic(self) -> bool:
        """Encoding writes one indexed video and completes before publishing it."""
        return True

    def prepare(self, progress_cb: Callable[[float], None]) -> Path:
        if self._path is None or self._info is None:
            raise SourceOpenError("NWB imaging source has not been opened.")
        cache = _ProxyCache(self._info.path)
        proxy = cache.get_cache_dir(self._path) / _PROXY_NAME
        if not (cache.is_cache_valid(self._path) and proxy.is_file()):
            staging = cache.get_temp_cache_dir(self._path)
            try:
                self._encode(staging / _PROXY_NAME, progress_cb)
                cache.commit_cache(self._path, staging)
            except BaseException:
                # Our own staging directory under the cache root, never the recording.
                import shutil

                shutil.rmtree(staging, ignore_errors=True)
                raise
        self._proxy = proxy
        self._read_back(proxy)
        progress_cb(1.0)
        return proxy

    def _encode(self, target: Path, progress_cb: Callable[[float], None]) -> None:
        import av

        assert self._path is not None and self._info is not None
        info = self._info
        layout = _PixelLayout.for_series(info)
        container = av.open(str(target), "w")
        try:
            stream = container.add_stream("ffv1")
            stream.height, stream.width = info.frame_shape[0], info.frame_shape[1]
            stream.pix_fmt = layout.encoded
            stream.time_base = _TIME_BASE
            stream.codec_context.time_base = _TIME_BASE
            stream.codec_context.options = dict(_FFV1_OPTIONS)
            stream.codec_context.thread_count = os.cpu_count() or 1
            pts = _presentation_ticks(self._times - self._origin)
            frame_bytes = max(1, int(np.prod(info.frame_shape)) * np.dtype(info.dtype).itemsize)
            block = max(1, _BLOCK_BYTES // frame_bytes)
            with nwb_format.open_file(self._path) as handle:
                layout.fit_scale(handle, info, self._frames)
                written = 0
                for begin in range(0, len(self._frames), block):
                    wanted = self._frames[begin : begin + block]
                    stored = nwb_read.read_frames(handle, info, int(wanted[0]), int(wanted[-1]) + 1)
                    for index in wanted:
                        image = layout.convert(stored[index - wanted[0]])
                        frame = av.VideoFrame.from_ndarray(image, format=layout.source)
                        if layout.source != layout.encoded:
                            frame = frame.reformat(format=layout.encoded)
                        frame.pts = int(pts[written])
                        frame.time_base = _TIME_BASE
                        for packet in stream.encode(frame):
                            container.mux(packet)
                        written += 1
                    progress_cb(0.98 * written / len(self._frames))
            for packet in stream.encode():
                container.mux(packet)
        finally:
            container.close()
        self._pixel_format = layout.encoded
        logger.info(
            "Wrote %d frames of %s to an FFV1 %s proxy (%s).",
            len(self._frames),
            info.path,
            layout.encoded,
            layout.describe(),
        )

    def _read_back(self, proxy: Path) -> None:
        """Take frame times from the proxy itself, through the pane's own reader.

        The pane selects frames from this table (D-075), so it is the one this
        source reports -- not the NWB timestamps it was written from, which the
        container stores to the microsecond and no finer.
        """
        from avialsync.engine.pyav_reader import PyAVReader

        with PyAVReader(proxy) as reader:
            self._frame_times = np.asarray(reader.frame_times, dtype=np.float64)
        if not self._pixel_format:
            import av

            with av.open(str(proxy)) as container:
                self._pixel_format = container.streams.video[0].codec_context.pix_fmt or ""
        if len(self._frame_times) != len(self._times):
            logger.warning(
                "%s proxy holds %d frames; the series has %d.",
                proxy,
                len(self._frame_times),
                len(self._times),
            )

    # ── VideoSource ────────────────────────────────────────────────────────

    def media_path(self) -> Path:
        if self._proxy is None:
            raise SourceOpenError("NWB imaging proxy has not been prepared.")
        return self._proxy

    def start_time(self) -> float | None:
        # The proxy declares no wall clock; the session places it (D-110).
        return None

    def time_bounds(self) -> tuple[float, float]:
        times = self._frame_times
        if times is None or len(times) == 0:
            return (0.0, 0.0)
        return (float(times[0]), float(times[-1]) + self._frame_interval())

    def frame_times(self) -> np.ndarray | None:
        return self._frame_times

    def fps(self) -> float:
        if self._info is not None and self._info.rate:
            return float(self._info.rate)
        interval = self._frame_interval()
        return 1.0 / interval if interval > 0 else 0.0

    def _frame_interval(self) -> float:
        times = self._frame_times if self._frame_times is not None else self._times
        if len(times) < 2:
            return 0.0
        return float(np.median(np.diff(times)))

    def video_metadata(self) -> VideoMetadata:
        times = self._frame_times if self._frame_times is not None else np.empty(0)
        rates = 1.0 / np.diff(times) if len(times) > 1 else np.empty(0)
        rates = rates[np.isfinite(rates)]
        measured = float(len(rates) / np.sum(1.0 / rates)) if len(rates) else self.fps()
        median = float(np.median(rates)) if len(rates) else 0.0
        info = self._info
        return VideoMetadata(
            container="mp4 (NWB proxy)",
            codec="ffv1",
            pixel_format=self._pixel_format,
            width=info.frame_shape[1] if info else 0,
            height=info.frame_shape[0] if info else 0,
            nominal_fps=self.fps(),
            measured_fps=measured,
            min_frame_rate=float(np.min(rates)) if len(rates) else 0.0,
            max_frame_rate=float(np.max(rates)) if len(rates) else 0.0,
            is_vfr=bool(len(rates) and np.any(np.abs(rates - median) > max(1e-3, median * 5e-3))),
            frame_count=len(times) or None,
            duration=max(0.0, self.time_bounds()[1] - self.time_bounds()[0]),
            start_time=None,
            file_size_bytes=self._path.stat().st_size if self._path else 0,
        )

    def label(self) -> str:
        return self._info.name if self._info is not None else "NWB imaging"


def _presentation_ticks(seconds: np.ndarray) -> np.ndarray:
    """Microsecond ticks, strictly increasing even where two times round together."""
    ticks = np.round(seconds * 1_000_000).astype(np.int64)
    if len(ticks) > 1:
        floor = np.arange(len(ticks), dtype=np.int64)
        ticks = np.maximum.accumulate(ticks - floor) + floor
    return ticks


class _PixelLayout:
    """How a series' stored samples become proxy pixels.

    Unsigned 8- and 16-bit greyscale -- nearly all imaging -- is written as it is.
    Anything else has no lossless greyscale pixel format, so it is mapped onto
    the 16-bit range: signed integers by shifting, floating point by the range a
    sample of frames spans. That mapping is for display only; the samples in the
    file are never touched, and the log says what was done.
    """

    def __init__(self, source: str, encoded: str, kind: str, rgb: bool, volume: bool) -> None:
        self.source = source
        self.encoded = encoded
        self._kind = kind
        self._rgb = rgb
        self._volume = volume
        self._low = 0.0
        self._scale = 1.0

    @classmethod
    def for_series(cls, info: SeriesInfo) -> _PixelLayout:
        dtype = np.dtype(info.dtype)
        rgb = len(info.frame_shape) == 3 and info.frame_shape[2] in (3, 4)
        volume = len(info.frame_shape) == 3 and not rgb
        if volume:
            logger.warning("%s is a volume; the proxy shows its first plane.", info.path)
        # By kind and size rather than equality: a big-endian ``>u2`` file is
        # still 16-bit unsigned, and is not equal to ``np.uint16``.
        unsigned8 = dtype.kind == "u" and dtype.itemsize == 1
        if rgb:
            source = "rgb24" if unsigned8 else "rgb48le"
            encoded = "bgr0" if unsigned8 else "rgb48le"
            return cls(source, encoded, "rgb", rgb=True, volume=False)
        if unsigned8:
            return cls("gray", "gray", "native", rgb=False, volume=volume)
        if dtype.kind == "u" and dtype.itemsize == 2:
            return cls("gray16le", "gray16le", "native", rgb=False, volume=volume)
        if dtype.kind == "i" and dtype.itemsize == 2:
            return cls("gray16le", "gray16le", "shift", rgb=False, volume=volume)
        return cls("gray16le", "gray16le", "scale", rgb=False, volume=volume)

    def fit_scale(self, handle: Any, info: SeriesInfo, frames: np.ndarray) -> None:
        if self._kind != "scale":
            return
        picks = np.unique(np.linspace(0, len(frames) - 1, _SCALE_SAMPLE_FRAMES).astype(np.int64))
        samples = np.concatenate(
            [
                np.asarray(nwb_read.read_frames(handle, info, int(frames[i]), int(frames[i]) + 1))
                .astype(np.float64)
                .ravel()
                for i in picks
            ]
        )
        samples = samples[np.isfinite(samples)]
        if len(samples) == 0:
            return
        low, high = np.quantile(samples, [0.0005, 0.9995])
        self._low = float(low)
        self._scale = 65535.0 / float(high - low) if high > low else 1.0

    def convert(self, image: np.ndarray) -> np.ndarray:
        if self._volume:
            image = image[..., 0]
        if self._rgb:
            image = image[..., :3]
            return np.ascontiguousarray(image.astype(np.uint8 if self.source == "rgb24" else "<u2"))
        if self._kind == "native":
            return np.ascontiguousarray(
                image.astype("<u2" if self.source == "gray16le" else np.uint8, copy=False)
            )
        if self._kind == "shift":
            return (image.astype(np.int32) + 32768).astype("<u2")
        scaled = (np.nan_to_num(image.astype(np.float64), nan=self._low) - self._low) * self._scale
        return np.clip(scaled, 0, 65535).astype("<u2")

    def describe(self) -> str:
        if self._kind == "scale":
            return f"display range {self._low:.4g} to {self._low + 65535.0 / self._scale:.4g}"
        if self._kind == "shift":
            return "signed 16-bit shifted by 32768"
        return "pixels as stored"
