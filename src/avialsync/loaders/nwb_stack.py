"""Read NWB image series as lazy planes for the two-photon viewer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.errors import SourceOpenError
from avialsync.core.source import ImagingMetadata, ImagingSource
from avialsync.loaders import nwb_format, nwb_read
from avialsync.loaders.nwb_format import SeriesInfo


class NWBStackSource(ImagingSource):
    """One image plane at a time from a local or streamed NWB series."""

    def __init__(self) -> None:
        self._context: Any = None
        self._handle: Any = None
        self._info: SeriesInfo | None = None
        self._frames = np.empty(0, dtype=np.int64)

    @classmethod
    def display_name(cls) -> str:
        return "Imaging"

    @classmethod
    def can_open(cls, path: Path) -> float:
        return 0.98 if nwb_format.split_object_path(path) is not None else 0.0

    def open(self, path: Path, config: dict[str, Any]) -> ImagingMetadata:
        named = nwb_format.split_object_path(path)
        if named is None:
            raise SourceOpenError("Choose an image series inside the NWB file.")
        container, series = named
        contents = nwb_format.scan(container)
        info = next((item for item in contents.of_kind("imaging") if item.path == series), None)
        if info is None or len(info.frame_shape) not in (2, 3):
            raise SourceOpenError(f"{series} has no readable image planes.")
        self._context = nwb_format.open_file(container)
        self._handle = self._context.__enter__()
        try:
            times = nwb_read.read_times(self._handle, info, 0, info.length)
            usable = np.isfinite(times)
            if len(times) > 1:
                usable[1:] &= times[1:] > np.maximum.accumulate(times[:-1])
            self._frames = np.flatnonzero(usable)
            if not len(self._frames):
                raise SourceOpenError(f"{series} has no frame with a usable timestamp.")
            self._info = info
            height, width = info.frame_shape[:2]
            channels = info.frame_shape[2] if len(info.frame_shape) == 3 else 1
            return ImagingMetadata(
                frame_count=len(self._frames),
                height=height,
                width=width,
                dtype=info.dtype,
                frame_times=times[self._frames],
                timing_source="NWB timestamps" if info.has_timestamps else "NWB frame rate",
                dataset=series,
                channel_count=channels,
            )
        except BaseException:
            self.close()
            raise

    def read_frame(self, index: int, channel: int = 0) -> np.ndarray:
        """Read one stored frame, selecting a channel from the last axis."""
        if self._info is None or self._handle is None:
            raise SourceOpenError("NWB imaging source is not open.")
        if not 0 <= index < len(self._frames):
            raise IndexError(index)
        channels = self._info.frame_shape[2] if len(self._info.frame_shape) == 3 else 1
        if not 0 <= channel < channels:
            raise IndexError(channel)
        stored = int(self._frames[index])
        plane = nwb_read.read_frames(self._handle, self._info, stored, stored + 1)[0]
        return np.asarray(plane[..., channel] if len(self._info.frame_shape) == 3 else plane)

    def close(self) -> None:
        """Release the owning thread's file or HTTP range handle."""
        if self._context is not None:
            self._context.__exit__(None, None, None)
        self._context = None
        self._handle = None
        self._info = None
