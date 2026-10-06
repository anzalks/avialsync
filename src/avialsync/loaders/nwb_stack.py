"""Read NWB image series as lazy planes for the two-photon viewer.

NWB gives each optical channel its own series -- ``TwoPhotonSeriesGreen`` and
``TwoPhotonSeriesRed`` on one imaging plane. Series that share a plane, a frame
shape and their frame times are read here as the channels of one stack (D-195),
so they can be shown alone or overlaid like the channels of a TIFF. The source
is named by its first series; the others travel in the ``channels`` import
choice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.errors import SourceOpenError
from avialsync.core.source import ImagingMetadata, ImagingSource
from avialsync.loaders import nwb_format, nwb_read
from avialsync.loaders.nwb_format import SeriesInfo
from avialsync.loaders.nwb_storage import children, is_group

#: Series whose third frame axis is depth. NWB stores an imaging frame as
#: ``(x, y)`` or ``(x, y, z)`` and gives each optical channel its own series and
#: imaging plane, so a third axis on these is a volume, never colour channels.
_VOLUME_TYPES = frozenset({"TwoPhotonSeries", "OnePhotonSeries"})


class NWBStackSource(ImagingSource):
    """One image plane at a time from a local or streamed NWB series."""

    def __init__(self) -> None:
        self._context: Any = None
        self._handle: Any = None
        self._info: SeriesInfo | None = None
        #: One series per channel when several series are read as channels.
        self._channels: list[SeriesInfo] = []
        self._frames = np.empty(0, dtype=np.int64)
        #: Chosen depth plane of a volumetric series; ``None`` when the third
        #: axis (if any) holds channels instead.
        self._depth: int | None = None

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
        self._depth = _depth(info, config)
        self._context = nwb_format.open_file(container)
        self._handle = self._context.__enter__()
        try:
            times = nwb_read.read_times(self._handle, info, 0, info.length)
            self._channels = self._series_channels(contents, info, times, config)
            usable = np.isfinite(times)
            if len(times) > 1:
                usable[1:] &= times[1:] > np.maximum.accumulate(times[:-1])
            self._frames = np.flatnonzero(usable)
            if not len(self._frames):
                raise SourceOpenError(f"{series} has no frame with a usable timestamp.")
            self._info = info
            height, width = info.frame_shape[:2]
            channels = self._channel_count(info)
            return ImagingMetadata(
                frame_count=len(self._frames),
                height=height,
                width=width,
                dtype=info.dtype,
                frame_times=times[self._frames],
                timing_source="NWB timestamps" if info.has_timestamps else "NWB frame rate",
                dataset=series,
                channel_count=channels,
                depth_planes=info.frame_shape[2] if self._depth is not None else 1,
                channel_names=self._channel_names(info),
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
        if not 0 <= channel < self._channel_count(self._info):
            raise IndexError(channel)
        stored = int(self._frames[index])
        source = self._channels[channel] if len(self._channels) > 1 else self._info
        plane = nwb_read.read_frames(self._handle, source, stored, stored + 1)[0]
        if len(source.frame_shape) == 2:
            return np.asarray(plane)
        if len(self._channels) > 1:
            return np.asarray(plane[..., self._depth or 0])
        return np.asarray(plane[..., channel if self._depth is None else self._depth])

    def _channel_count(self, info: SeriesInfo) -> int:
        if len(self._channels) > 1:
            return len(self._channels)
        if len(info.frame_shape) == 3 and self._depth is None:
            return info.frame_shape[2]
        return 1

    def _series_channels(
        self,
        contents: nwb_format.FileContents,
        info: SeriesInfo,
        times: np.ndarray,
        config: dict[str, Any],
    ) -> list[SeriesInfo]:
        """The series read as this stack's channels, checked to be one acquisition."""
        named = [str(path) for path in config.get("channels") or ()]
        if len(named) < 2:
            return [info]
        by_path = {item.path: item for item in contents.of_kind("imaging")}
        chosen = []
        for path in named:
            other = by_path.get(path)
            if other is None:
                raise SourceOpenError(f"{path} is not an image series in this file.")
            if not _same_acquisition(self._handle, info, times, other):
                raise SourceOpenError(
                    f"{other.name} does not share {info.name}'s plane, frame shape and times."
                )
            chosen.append(other)
        if info.path not in named:
            raise SourceOpenError(f"{info.name} must be one of its own channels.")
        return chosen

    def _channel_names(self, info: SeriesInfo) -> tuple[str, ...]:
        """Distinct series names for merged channels, else the plane's optical channel."""
        if len(self._channels) > 1:
            return _distinct_names([item.name for item in self._channels])
        if self._channel_count(info) != 1:
            return ()
        optical = _optical_channels(self._handle, info)
        return (optical[0],) if len(optical) == 1 else ()

    def close(self) -> None:
        """Release the owning thread's file or HTTP range handle."""
        if self._context is not None:
            self._context.__exit__(None, None, None)
        self._context = None
        self._handle = None
        self._info = None
        self._channels = []


def _depth(info: SeriesInfo, config: dict[str, Any]) -> int | None:
    """Return the depth plane to show from a volumetric series."""
    if len(info.frame_shape) != 3 or info.neurodata_type not in _VOLUME_TYPES:
        return None
    planes = info.frame_shape[2]
    # The first plane until the user picks another in the pane (D-194).
    depth = int(config.get("z") or 0)
    if not 0 <= depth < planes:
        raise SourceOpenError(f"{info.name} has no depth plane {depth}.")
    return depth


def _type(group: Any) -> str:
    value = group.attrs.get("neurodata_type", "")
    return value.decode() if isinstance(value, bytes) else str(value)


def _plane(handle: Any, info: SeriesInfo) -> Any:
    try:
        return handle[info.path]["imaging_plane"]
    except (KeyError, ValueError, OSError):
        return None


def _optical_channels(handle: Any, info: SeriesInfo) -> list[str]:
    """Names of the ``OpticalChannel`` groups on *info*'s imaging plane."""
    plane = _plane(handle, info)
    if not is_group(plane):
        return []
    return [
        str(child.name).rsplit("/", 1)[-1]
        for child in children(plane)
        if is_group(child) and _type(child) == "OpticalChannel"
    ]


def _same_acquisition(handle: Any, info: SeriesInfo, times: np.ndarray, other: SeriesInfo) -> bool:
    """Whether *other* is another channel of *info*: same plane, shape and frame times."""
    if other.path == info.path:
        return True
    if other.frame_shape != info.frame_shape or other.length != info.length:
        return False
    plane, other_plane = _plane(handle, info), _plane(handle, other)
    # Compared as objects: h5py names a linked group by the path it was reached
    # through, so two links to one plane have two names.
    if plane is None or other_plane is None or plane != other_plane:
        return False
    return bool(np.array_equal(times, nwb_read.read_times(handle, other, 0, other.length)))


def _distinct_names(names: list[str]) -> tuple[str, ...]:
    """What tells the series apart: ``TwoPhotonSeriesGreen`` -> ``Green``."""
    prefix = names[0]
    for name in names[1:]:
        while not name.startswith(prefix):
            prefix = prefix[:-1]
    stripped = [name[len(prefix) :].strip(" _-.") for name in names]
    return tuple(stripped) if all(stripped) and len(set(stripped)) == len(names) else tuple(names)


def channel_groups(path: Path, contents: nwb_format.FileContents) -> list[list[SeriesInfo]]:
    """The file's image series, grouped so each group is one acquisition's channels."""
    imaging = [info for info in contents.of_kind("imaging") if len(info.frame_shape) in (2, 3)]
    groups: list[tuple[np.ndarray, list[SeriesInfo]]] = []
    with nwb_format.open_file(path) as handle:
        for info in imaging:
            for times, group in groups:
                if _same_acquisition(handle, group[0], times, info):
                    group.append(info)
                    break
            else:
                groups.append((nwb_read.read_times(handle, info, 0, info.length), [info]))
    return [group for _times, group in groups]
