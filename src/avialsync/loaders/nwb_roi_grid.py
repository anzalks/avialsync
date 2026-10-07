"""Every ROI of an NWB plane segmentation, tiled into one picture per frame (D-193).

A plane segmentation names cells by their masks. Shown one series at a time, a
file with hundreds of ROIs offers one field of view -- or, for patch-scanned
acquisitions that store a small window per cell, one cell. This source lays
every ROI out as a tile of one grid image, so the imaging pane shows them all at
the playhead with its levels, averaging, zoom and time mapping unchanged.

Each tile shows the best evidence the file holds, never a reconstruction:

* **Raw crops** when an image series on the same imaging plane covers every
  mask: the tile is that series' pixels around the ROI, frame by frame.
* **Response on the mask** otherwise: the ROI's mask, its pixels set to the
  ROI's value at that frame in the file's ``RoiResponseSeries`` (ΔF/F before
  fluorescence). This is a map of a measured trace, not imaging, and the source
  says so in its label and timing.

Pixels outside a mask, and the one-pixel gutters between tiles, are NaN: drawn
black and ignored by the automatic levels, so a window is measured on cells.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.errors import SourceOpenError
from avialsync.core.source import ImagingMetadata, ImagingSource
from avialsync.loaders import nwb_format, nwb_read
from avialsync.loaders.nwb_format import SeriesInfo
from avialsync.loaders.nwb_storage import children, is_dataset, is_group

__all__ = ["NWBRoiGridSource", "RoiGrid", "find_roi_grids"]

#: Response series preferred for the mask view, most interpretable first.
_RESPONSE_PARENTS = ("DfOverF", "Fluorescence")


@dataclass(frozen=True)
class RoiGrid:
    """One plane segmentation the grid can show, found without reading samples."""

    path: str
    name: str
    roi_count: int
    mode: str  # "raw" or "response"
    series: str  # the image or response series the tiles are read from


def _type(group: Any) -> str:
    value = group.attrs.get("neurodata_type", "")
    return value.decode() if isinstance(value, bytes) else str(value)


def _segmentations(handle: Any) -> Iterator[Any]:
    processing = handle.get("processing")
    if not is_group(processing):
        return
    for module in children(processing):
        if not is_group(module):
            continue
        for interface in children(module):
            if not is_group(interface) or _type(interface) != "ImageSegmentation":
                continue
            for table in children(interface):
                if is_group(table) and _type(table) == "PlaneSegmentation":
                    yield table


def _link_target(group: Any, name: str) -> Any:
    """The object an NWB link points at, or ``None``.

    Compared by identity, not by ``.name``: h5py names a linked group by the
    path it was reached through, so two links to one plane have two names.
    """
    try:
        return group[name]
    except (KeyError, ValueError, OSError):
        return None


def _region_table(handle: Any, region: Any) -> str | None:
    try:
        return str(handle[region.attrs["table"]].name)
    except (KeyError, TypeError, ValueError, OSError):
        return None


def _masks(table: Any) -> tuple[list[np.ndarray], list[tuple[int, int]]]:
    """Each ROI's mask cropped to its bounding box, and the box's top-left corner.

    ``pixel_mask`` rows are ``(x, y, weight)`` with x the column; ``image_mask``
    is one full-field array per ROI. Both are read once, at open.
    """
    if is_dataset(table.get("pixel_mask")) and is_dataset(table.get("pixel_mask_index")):
        pixels = np.asarray(table["pixel_mask"][()])
        ends = np.asarray(table["pixel_mask_index"][()], dtype=np.int64)
        starts = np.concatenate([[0], ends[:-1]])
        crops, corners = [], []
        for start, end in zip(starts, ends, strict=True):
            # Some writers list every pixel of a cell's patch and mark the cell
            # by weight; the box is the cell's, or a tile is mostly empty patch.
            weights = np.asarray(pixels["weight"][start:end], np.float32)
            inside = weights != 0
            rows = np.asarray(pixels["y"][start:end], dtype=np.int64)[inside]
            cols = np.asarray(pixels["x"][start:end], dtype=np.int64)[inside]
            if not len(rows):
                crops.append(np.full((1, 1), np.nan, np.float32))
                corners.append((0, 0))
                continue
            top, left = int(rows.min()), int(cols.min())
            crop = np.full((rows.max() - top + 1, cols.max() - left + 1), np.nan, np.float32)
            crop[rows - top, cols - left] = weights[inside]
            crops.append(crop)
            corners.append((top, left))
        return crops, corners
    if is_dataset(table.get("image_mask")):
        images = table["image_mask"]
        crops, corners = [], []
        for index in range(images.shape[0]):
            image = np.asarray(images[index], dtype=np.float32)
            rows, cols = np.nonzero(image)
            if not len(rows):
                crops.append(np.full((1, 1), np.nan, np.float32))
                corners.append((0, 0))
                continue
            top, left = int(rows.min()), int(cols.min())
            crop = image[top : rows.max() + 1, left : cols.max() + 1].copy()
            crop[crop == 0] = np.nan
            crops.append(crop)
            corners.append((top, left))
        return crops, corners
    raise SourceOpenError(f"{table.name} stores no pixel or image masks.")


def _response_series(
    handle: Any, contents: nwb_format.FileContents, table_path: str
) -> SeriesInfo | None:
    """The response series whose ROIs are rows of *table_path*, ΔF/F first."""
    found = []
    for info in contents.of_kind("signal"):
        group = handle[info.path]
        region = group.get("rois")
        if is_dataset(region) and _region_table(handle, region) == table_path:
            parent = info.path.rstrip("/").split("/")[-2] if info.path.count("/") > 1 else ""
            rank = _RESPONSE_PARENTS.index(parent) if parent in _RESPONSE_PARENTS else 99
            found.append((rank, info.path, info))
    return min(found, key=lambda item: item[:2])[2] if found else None


def _raw_series(
    handle: Any,
    contents: nwb_format.FileContents,
    table: Any,
    extent: tuple[int, int],
) -> SeriesInfo | None:
    """An image series on the segmentation's plane whose frame covers every mask."""
    plane = _link_target(table, "imaging_plane")
    if plane is None:
        return None
    for info in contents.of_kind("imaging"):
        if len(info.frame_shape) != 2:
            continue
        if _link_target(handle[info.path], "imaging_plane") != plane:
            continue  # h5py and Zarr objects compare equal when they are one object
        if info.frame_shape[0] >= extent[0] and info.frame_shape[1] >= extent[1]:
            return info
    return None


def find_roi_grids(path: Path, contents: nwb_format.FileContents | None = None) -> list[RoiGrid]:
    """Plane segmentations in *path* that the grid can show, with what it would show."""
    contents = contents or nwb_format.scan(path)
    grids: list[RoiGrid] = []
    with nwb_format.open_file(path) as handle:
        for table in _segmentations(handle):
            try:
                crops, corners = _masks(table)
            except SourceOpenError:
                continue
            extent = _extent(crops, corners)
            raw = _raw_series(handle, contents, table, extent)
            response = None if raw else _response_series(handle, contents, str(table.name))
            source = raw or response
            if source is None:
                continue
            grids.append(
                RoiGrid(
                    path=str(table.name),
                    name=str(table.name).rsplit("/", 1)[-1],
                    roi_count=len(crops),
                    mode="raw" if raw else "response",
                    series=source.path,
                )
            )
    return grids


def _extent(crops: list[np.ndarray], corners: list[tuple[int, int]]) -> tuple[int, int]:
    return (
        max(top + crop.shape[0] for crop, (top, _) in zip(crops, corners, strict=True)),
        max(left + crop.shape[1] for crop, (_, left) in zip(crops, corners, strict=True)),
    )


class NWBRoiGridSource(ImagingSource):
    """All ROIs of one plane segmentation, one tile each, in a single picture."""

    def __init__(self) -> None:
        self._context: Any = None
        self._handle: Any = None
        self._info: SeriesInfo | None = None
        self._mode = ""
        self._frames = np.empty(0, dtype=np.int64)
        self._crops: list[np.ndarray] = []
        self._corners: list[tuple[int, int]] = []
        self._columns = np.empty(0, dtype=np.int64)
        self._shape = (0, 0)
        self._grid = (0, 0)
        self._tile = (0, 0)

    @classmethod
    def display_name(cls) -> str:
        return "ROI Grid (NWB)"

    @classmethod
    def can_open(cls, path: Path) -> float:
        named = nwb_format.split_object_path(path)
        return 0.99 if named is not None and "/ImageSegmentation/" in named[1] else 0.0

    def label(self) -> str:
        """Say what the tiles are: raw pixels, or a trace drawn on masks."""
        if self._info is None:
            return "ROI Grid (NWB)"
        response = self._info.path.rstrip("/").split("/")[-2]
        what = "raw crops" if self._mode == "raw" else f"{response} on ROI masks"
        return f"{len(self._crops)} ROIs — {what}"

    def open(self, path: Path, config: dict[str, Any]) -> ImagingMetadata:
        named = nwb_format.split_object_path(path)
        if named is None:
            raise SourceOpenError("Choose a plane segmentation inside the NWB file.")
        container, table_path = named
        contents = nwb_format.scan(container)
        self._context = nwb_format.open_file(container)
        self._handle = self._context.__enter__()
        try:
            table = self._handle.get(table_path)
            if not is_group(table) or _type(table) != "PlaneSegmentation":
                raise SourceOpenError(f"{table_path} is not a plane segmentation.")
            self._crops, self._corners = _masks(table)
            raw = _raw_series(self._handle, contents, table, _extent(self._crops, self._corners))
            if raw is not None:
                self._mode, self._info = "raw", raw
                self._columns = np.arange(len(self._crops))
            else:
                response = _response_series(self._handle, contents, table_path)
                if response is None:
                    raise SourceOpenError(
                        f"{table_path} has no image series or ROI response to show."
                    )
                self._mode, self._info = "response", response
                region = np.asarray(self._handle[response.path]["rois"][()], dtype=np.int64)
                # Column j of the response is ROI region[j]; tiles follow the
                # response's column order, so tile j is column j.
                self._crops = [self._crops[row] for row in region]
                self._corners = [self._corners[row] for row in region]
                self._columns = np.arange(len(region))
            times = nwb_read.read_times(self._handle, self._info, 0, self._info.length)
            usable = np.isfinite(times)
            if len(times) > 1:
                usable[1:] &= times[1:] > np.maximum.accumulate(times[:-1])
            self._frames = np.flatnonzero(usable)
            if not len(self._frames):
                raise SourceOpenError(f"{self._info.name} has no frame with a usable timestamp.")
            self._layout()
            return ImagingMetadata(
                frame_count=len(self._frames),
                height=self._shape[0],
                width=self._shape[1],
                dtype="float32",
                frame_times=times[self._frames],
                timing_source=("NWB timestamps" if self._info.has_timestamps else "NWB frame rate"),
                dataset=table_path,
                channel_count=1,
            )
        except BaseException:
            self.close()
            raise

    def _layout(self) -> None:
        """Choose tile size and a grid near-square on screen, with 1 px gutters."""
        tile_h = max(crop.shape[0] for crop in self._crops) + 1
        tile_w = max(crop.shape[1] for crop in self._crops) + 1
        count = len(self._crops)
        columns = max(1, math.ceil(math.sqrt(count * tile_h / tile_w)))
        rows = math.ceil(count / columns)
        self._grid = (rows, columns)
        self._tile = (tile_h, tile_w)
        self._shape = (rows * tile_h - 1, columns * tile_w - 1)

    def read_frame(self, index: int, channel: int = 0) -> np.ndarray:
        """Compose frame *index*: every ROI's tile in reading order."""
        if self._info is None or self._handle is None:
            raise SourceOpenError("ROI grid is not open.")
        if not 0 <= index < len(self._frames) or channel != 0:
            raise IndexError(index if channel == 0 else channel)
        stored = int(self._frames[index])
        mosaic = np.full(
            (self._grid[0] * self._tile[0], self._grid[1] * self._tile[1]), np.nan, np.float32
        )
        if self._mode == "raw":
            frame = nwb_read.read_frames(self._handle, self._info, stored, stored + 1)[0]
            # The whole box around each cell, not only its mask: the neuropil
            # beside a cell is how its signal is judged.
            tiles = [
                frame[top : top + crop.shape[0], left : left + crop.shape[1]].astype(np.float32)
                for crop, (top, left) in zip(self._crops, self._corners, strict=True)
            ]
        else:
            values = nwb_read.read_values(self._handle, self._info, stored, stored + 1)[0]
            tiles = [
                crop * np.float32(values[column])
                for crop, column in zip(self._crops, self._columns, strict=True)
            ]
        tile_h, tile_w = self._tile
        for position, tile in enumerate(tiles):
            row, column = divmod(position, self._grid[1])
            top, left = row * tile_h, column * tile_w
            mosaic[top : top + tile.shape[0], left : left + tile.shape[1]] = tile
        return mosaic[: self._shape[0], : self._shape[1]]

    def close(self) -> None:
        if self._context is not None:
            self._context.__exit__(None, None, None)
        self._context = None
        self._handle = None
        self._info = None
