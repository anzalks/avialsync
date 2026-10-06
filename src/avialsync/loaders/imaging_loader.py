"""Lazy HDF5 and TIFF readers for time-indexed two-photon image stacks (D-186).

Both read one plane per request -- an HDF5 hyperslab or a TIFF page -- and never
the whole stack. Channels are read per request and overlaid by the viewer; a
depth plane, a dataset, an axis order or a frame rate the file does not settle
raises :class:`~avialsync.core.errors.ImagingChoiceRequired` so the user is
asked rather than given a guess.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import tifffile

from avialsync.core.errors import ImagingChoiceRequired, SourceOpenError
from avialsync.core.source import ImagingMetadata, ImagingSource

#: Axis letters a stack may carry. T, Y and X are required.
_AXES = "TCZYX"


def _text(value: object) -> str:
    """Decode common HDF5 attribute string representations."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _rate_from(attrs: dict[str, Any]) -> tuple[float | None, str]:
    """Return a frame rate and the attribute it came from, if the file has one."""
    for name in ("fps", "frame_rate", "frameRate"):
        if name in attrs:
            return float(attrs[name]), name
    for name in ("dt", "frame_interval", "TimeIncrement"):
        if name in attrs:
            interval = float(attrs[name])
            return (1.0 / interval if interval > 0 else 0.0), name
    return None, ""


def _times(count: int, config: dict[str, Any], attrs: dict[str, Any]) -> tuple[np.ndarray, str]:
    """Resolve frame times: a timestamp table first, then a frame rate.

    Within each, what the user or a session plugin supplied in *config* wins
    over what the file says -- file timing is a default, never truth (AGENTS
    known traps). A per-frame table beats any constant rate because it carries
    the acquisition's real jitter and pauses.
    """
    supplied = config.get("frame_times")
    if supplied is not None:
        values, origin = np.asarray(supplied, dtype=np.float64), "import configuration"
    elif "frame_times" in attrs:
        values, origin = np.asarray(attrs["frame_times"], dtype=np.float64), "frame_times"
    else:
        fps: float | None
        if config.get("fps") is not None:
            fps, origin = float(config["fps"]), "import frame rate"
        else:
            fps, origin = _rate_from(attrs)
        if fps is None or not math.isfinite(fps) or fps <= 0:
            raise ImagingChoiceRequired(
                "fps",
                "Imaging frame times are missing. Enter the acquisition frame rate.",
            )
        values = np.arange(count, dtype=np.float64) / fps
    if values.ndim != 1 or values.size != count:
        raise SourceOpenError("Imaging frame times do not match the number of frames.")
    if not np.all(np.isfinite(values)) or np.any(np.diff(values) <= 0):
        raise SourceOpenError("Imaging frame times must be finite and strictly increasing.")
    return values, origin


def _validate_axes(shape: tuple[int, ...], axes: str) -> None:
    if len(shape) != len(axes) or len(set(axes)) != len(axes):
        raise ImagingChoiceRequired(
            "axes", f"Imaging axes must name each of the {len(shape)} dimensions once."
        )
    if not {"T", "Y", "X"}.issubset(set(axes)) or set(axes) - set(_AXES):
        raise ImagingChoiceRequired("axes", "Imaging axes must include T, Y, X and may add C or Z.")


def _depth(shape: tuple[int, ...], axes: str, config: dict[str, Any]) -> int:
    """Return the chosen Z plane, asking when the stack has more than one."""
    if "Z" not in axes:
        return 0
    planes = shape[axes.index("Z")]
    chosen = config.get("z")
    if chosen is None and planes == 1:
        return 0
    if chosen is None:
        raise ImagingChoiceRequired(
            "z",
            f"This stack has {planes} depth planes. Choose one to show.",
            tuple(str(index) for index in range(planes)),
        )
    number = int(chosen)
    if not 0 <= number < planes:
        raise SourceOpenError(
            f"Imaging depth plane {number} is outside the stack (0-{planes - 1})."
        )
    return number


def _shape_info(shape: tuple[int, ...], axes: str) -> tuple[int, int, int, int]:
    """Return ``(frames, height, width, channels)`` and reject an empty stack."""
    count, height, width = (shape[axes.index(axis)] for axis in "TYX")
    channels = shape[axes.index("C")] if "C" in axes else 1
    if 0 in (count, height, width, channels):
        raise SourceOpenError("Imaging stack has an empty time, channel or image dimension.")
    return count, height, width, channels


def _seconds(value: str, unit: str) -> float:
    """Convert an OME time quantity without assuming an unrecognized unit."""
    scales = {"s": 1.0, "ms": 1e-3, "µs": 1e-6, "us": 1e-6, "ns": 1e-9, "min": 60.0, "h": 3600.0}
    if unit not in scales:
        raise ImagingChoiceRequired(
            "fps", f"Unsupported OME time unit {unit!r}. Enter the acquisition frame rate."
        )
    return float(value) * scales[unit]


def _ome_plane_times(pixels: Any, axes: str, depth: int, count: int) -> np.ndarray | None:
    """Use per-plane OME ``DeltaT`` for the chosen depth and the first channel.

    Channels of a two-photon acquisition are recorded simultaneously, so one
    channel's times stand for all of them; the first is the one every file has.
    """
    if pixels is None:
        return None
    wanted = {"C": 0, "Z": depth}
    values: dict[int, float] = {}
    saw_delta = False
    for plane in pixels.iter():
        if not plane.tag.endswith("Plane") or plane.get("DeltaT") is None:
            continue
        saw_delta = True
        if any(axis in axes and int(plane.get(f"The{axis}", "0")) != wanted[axis] for axis in "CZ"):
            continue
        index = int(plane.get("TheT", "0"))
        if not 0 <= index < count:
            continue
        timestamp = _seconds(plane.get("DeltaT", "0"), plane.get("DeltaTUnit", "s"))
        if index in values and values[index] != timestamp:
            raise SourceOpenError("OME plane timestamps disagree for the selected imaging plane.")
        values[index] = timestamp
    if not saw_delta:
        return None
    if len(values) != count:
        raise SourceOpenError("OME plane timestamps are incomplete for the selected imaging plane.")
    return np.asarray([values[index] for index in range(count)], dtype=np.float64)


def _scanimage_layout(handle: tifffile.TiffFile, pages: int) -> tuple[str, tuple[int, ...], float]:
    """Return axes, page shape and frame rate for a ScanImage acquisition.

    ScanImage writes one page per channel per plane, channel fastest, and keeps
    the channel count and scan rate in its frame data rather than in the TIFF
    structure, so tifffile sees a flat ``IYX`` series. Pages after the last
    complete time point belong to an aborted acquisition and are not shown.
    """
    data = (handle.scanimage_metadata or {}).get("FrameData") or {}
    if not data:
        data = tifffile.matlabstr2py(handle.pages.first.software) or {}
    saved = data.get("SI.hChannels.channelSave", 1)
    channels = len(np.ravel(saved)) if not isinstance(saved, int | float) else 1
    volumes = bool(data.get("SI.hFastZ.enable", False))
    slices = int(
        data.get("SI.hStackManager.actualNumSlices", data.get("SI.hStackManager.numSlices", 1))
    )
    slices = slices if volumes and slices > 1 else 1
    key = "SI.hRoiManager.scanVolumeRate" if slices > 1 else "SI.hRoiManager.scanFrameRate"
    rate = float(data.get(key, 0.0) or 0.0)
    frames = pages // (channels * slices)
    if slices > 1:
        return "TZCYX", (frames, slices, channels), rate
    return "TCYX", (frames, channels), rate


class HDF5ImagingLoader(ImagingSource):
    """Read one HDF5 hyperslab at a time without materializing the stack."""

    def __init__(self) -> None:
        self._file: h5py.File | None = None
        self._dataset: h5py.Dataset | None = None
        self._selection: list[Any] = []
        self._axes = ""

    @classmethod
    def display_name(cls) -> str:
        """Label this source by its data kind."""
        return "Two-photon imaging (HDF5)"

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Claim common HDF5 extensions without opening the file."""
        return 0.8 if path.suffix.lower() in {".h5", ".hdf5"} else 0.0

    def open(self, path: Path, config: dict[str, Any]) -> ImagingMetadata:
        """Choose a dataset and resolve axes and timing from metadata/config."""
        self.close()
        try:
            handle = h5py.File(path, "r")
            self._file = handle
            dataset, chosen = self._dataset_for(handle, config)
            axes = _text(config.get("axes", dataset.attrs.get("axes", ""))).upper()
            if not axes and dataset.ndim == 3:
                axes = "TYX"
            shape = tuple(int(length) for length in dataset.shape)
            _validate_axes(shape, axes)
            count, height, width, channels = _shape_info(shape, axes)
            selection: list[Any] = [slice(None)] * len(shape)
            if "Z" in axes:
                selection[axes.index("Z")] = _depth(shape, axes, config)
            attrs = dict(handle.attrs)
            attrs.update(dataset.attrs)
            table = self._timestamp_table(handle, dataset, count, config)
            if table is not None:
                attrs["frame_times"] = table
            times, origin = _times(count, config, attrs)
            self._dataset, self._selection, self._axes = dataset, selection, axes
            return ImagingMetadata(
                count, height, width, str(dataset.dtype), times, origin, chosen, channels
            )
        except SourceOpenError:
            self.close()
            raise
        except (OSError, KeyError, TypeError, ValueError) as error:
            self.close()
            raise SourceOpenError(f"Could not read HDF5 imaging stack: {error}") from error

    @staticmethod
    def _dataset_for(handle: h5py.File, config: dict[str, Any]) -> tuple[h5py.Dataset, str]:
        """Return the configured dataset, or the only plausible one."""
        candidates: list[str] = []

        def collect(name: str, value: h5py.Group | h5py.Dataset) -> None:
            if isinstance(value, h5py.Dataset) and 3 <= value.ndim <= 5:
                candidates.append(name)

        handle.visititems(collect)
        chosen = str(config.get("dataset", ""))
        if not chosen:
            if len(candidates) != 1:
                raise ImagingChoiceRequired(
                    "dataset",
                    "This file holds several image datasets. Choose the one to show."
                    if candidates
                    else "This file holds no three- to five-dimensional dataset.",
                    tuple(candidates),
                )
            chosen = candidates[0]
        dataset = handle.get(chosen)
        if not isinstance(dataset, h5py.Dataset):
            raise SourceOpenError(f"Imaging dataset {chosen!r} was not found.")
        if not (
            np.issubdtype(dataset.dtype, np.integer) or np.issubdtype(dataset.dtype, np.floating)
        ):
            raise SourceOpenError("Imaging dataset must contain real numeric pixels.")
        return dataset, chosen

    @staticmethod
    def _timestamp_table(
        handle: h5py.File, dataset: h5py.Dataset, count: int, config: dict[str, Any]
    ) -> np.ndarray | None:
        """Read a per-frame timestamp dataset named in config or beside the images."""
        path = config.get("timestamps_path")
        if path:
            return np.asarray(handle[str(path)][:], dtype=np.float64)
        for name in ("frame_times", "timestamps", "time"):
            candidate = dataset.parent.get(name)
            if isinstance(candidate, h5py.Dataset) and candidate.ndim == 1:
                if len(candidate) == count:
                    return np.asarray(candidate[:], dtype=np.float64)
        return None

    def read_frame(self, index: int, channel: int = 0) -> np.ndarray:
        """Read a single plane by HDF5 hyperslab."""
        dataset = self._dataset
        if dataset is None:
            raise SourceOpenError("HDF5 imaging source is closed.")
        selection = list(self._selection)
        selection[self._axes.index("T")] = index
        if "C" in self._axes:
            selection[self._axes.index("C")] = channel
        elif channel != 0:
            raise SourceOpenError(f"HDF5 imaging stack has no channel {channel}.")
        plane = np.asarray(dataset[tuple(selection)])
        if [axis for axis in self._axes if axis in "YX"] == ["X", "Y"]:
            plane = plane.T
        if plane.ndim != 2:
            raise SourceOpenError("Selected HDF5 frame is not a 2D plane.")
        return plane

    def close(self) -> None:
        """Close the HDF5 handle."""
        if self._file is not None:
            self._file.close()
        self._file = None
        self._dataset = None


class TIFFImagingLoader(ImagingSource):
    """Read one TIFF page at a time; no full-stack ``asarray`` call."""

    def __init__(self) -> None:
        self._file: tifffile.TiffFile | None = None
        self._series: Any = None
        self._frame_count = 0
        self._channel_count = 1
        self._page_shape: tuple[int, ...] = ()
        self._page_axes = ""
        self._depth = 0

    @classmethod
    def display_name(cls) -> str:
        """Label this source by its data kind."""
        return "Two-photon imaging (TIFF)"

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Claim TIFF extensions without opening the file."""
        return 0.9 if path.suffix.lower() in {".tif", ".tiff"} else 0.0

    def open(self, path: Path, config: dict[str, Any]) -> ImagingMetadata:
        """Validate that one TIFF page holds one plane of one time point."""
        self.close()
        try:
            handle = tifffile.TiffFile(path)
            self._file = handle
            series = self._series_for(handle, config)
            axes = str(series.axes).upper()
            shape = tuple(int(size) for size in series.shape)
            attrs: dict[str, Any] = {}
            if handle.is_scanimage and axes in {"IYX", "QYX", "TYX"}:
                axes, page_shape, rate = _scanimage_layout(handle, len(series.pages))
                shape = page_shape + shape[-2:]
                if rate > 0:
                    attrs["fps"] = rate
            else:
                axes = "TYX" if axes in {"QYX", "IYX"} else axes
            if not axes.endswith("YX"):
                raise SourceOpenError(f"TIFF axes {axes!r} do not expose 2D grayscale pages.")
            _validate_axes(shape, axes)
            count, height, width, channels = _shape_info(shape, axes)
            page_shape = shape[:-2]
            if len(series.pages) < int(np.prod(page_shape)):
                raise SourceOpenError("TIFF series does not expose one page per plane.")
            depth = _depth(shape, axes, config)
            if handle.ome_metadata:
                attrs.update(self._ome_timing(handle.ome_metadata, axes, depth, count))
            times, origin = _times(count, config, attrs)
            self._series, self._frame_count, self._channel_count = series, count, channels
            self._page_shape, self._page_axes, self._depth = page_shape, axes[:-2], depth
            return ImagingMetadata(
                count, height, width, str(series.dtype), times, origin, "", channels
            )
        except SourceOpenError:
            self.close()
            raise
        except (OSError, IndexError, ValueError, tifffile.TiffFileError) as error:
            self.close()
            raise SourceOpenError(f"Could not read TIFF imaging stack: {error}") from error

    @staticmethod
    def _series_for(handle: tifffile.TiffFile, config: dict[str, Any]) -> Any:
        """Return the configured series, asking when the file has several."""
        if "series" not in config and len(handle.series) > 1:
            raise ImagingChoiceRequired(
                "series",
                "This TIFF holds several image series. Choose the one to show.",
                tuple(
                    f"{index}: {item.axes} {item.shape}"
                    for index, item in enumerate(handle.series[:20])
                ),
            )
        series = handle.series[int(config.get("series", 0))]
        if not (
            np.issubdtype(series.dtype, np.integer) or np.issubdtype(series.dtype, np.floating)
        ):
            raise SourceOpenError("TIFF imaging series must contain real numeric pixels.")
        return series

    @staticmethod
    def _ome_timing(ome: str, axes: str, depth: int, count: int) -> dict[str, Any]:
        """Return per-plane times, or a constant increment, from OME-XML."""
        root = ET.fromstring(ome)
        pixels = next((node for node in root.iter() if node.tag.endswith("Pixels")), None)
        timing: dict[str, Any] = {}
        plane_times = _ome_plane_times(pixels, axes, depth, count)
        if plane_times is not None:
            timing["frame_times"] = plane_times
        elif pixels is not None and pixels.get("TimeIncrement"):
            timing["TimeIncrement"] = _seconds(
                pixels.get("TimeIncrement", "0"), pixels.get("TimeIncrementUnit", "s")
            )
        return timing

    def read_frame(self, index: int, channel: int = 0) -> np.ndarray:
        """Decode one TIFF page, including supported compression codecs."""
        if (
            self._series is None
            or not 0 <= index < self._frame_count
            or not 0 <= channel < self._channel_count
        ):
            raise SourceOpenError("TIFF imaging frame is unavailable.")
        chosen = {"T": index, "C": channel, "Z": self._depth}
        try:
            page = int(
                np.ravel_multi_index(
                    tuple(chosen[axis] for axis in self._page_axes), self._page_shape
                )
            )
            return np.asarray(self._series.pages[page].asarray())
        except (OSError, ValueError, KeyError, ImportError) as error:
            detail = str(error)
            if "imagecodecs" in detail.lower():
                detail = "This compressed TIFF page needs the optional imagecodecs package."
            raise SourceOpenError(f"Could not decode TIFF page {index}: {detail}") from error

    def close(self) -> None:
        """Close the TIFF file handle."""
        if self._file is not None:
            self._file.close()
        self._file = None
        self._series = None
        self._frame_count = 0
        self._channel_count = 1
        self._page_shape = ()
        self._page_axes = ""
        self._depth = 0
