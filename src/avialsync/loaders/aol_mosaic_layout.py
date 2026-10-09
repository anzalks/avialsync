"""Where each ribbon ROI's tile sits in an AOL mosaic, in display orientation.

Three layouts, best evidence first:

``branches``
    The dendritic tree as the microscope controller reconstructs it: one
    column per traced branch, its segments stacked top to bottom in scan
    order, a column as wide as its widest segment and the mosaic as tall as
    the longest branch. Population patches, which belong to no branch, are
    packed after the tree into a near-square block of columns. Branch
    membership comes from ``thin_mask.mat``: its ``branch_projection`` holds
    one image per branch whose length is the sum of that branch's segment
    lengths, and segments are numbered branch by branch.
``analysis``
    The lab's ROI-analysis mosaic (``mosaic_info/source_roi_map``), on which
    its cell masks are drawn; cell crops must use this one.
``grid``
    A square grid, tiles across then down, when the trial carries neither.

All coordinates are as MATLAB, and the lab's figures, show them: h5py reads
MATLAB's column-major arrays transposed, so a stored ``(lines, length)`` plane
is a ``length``-tall, ``lines``-wide tile here.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import h5py
import numpy as np

from avialsync.loaders.aol_microscope_trial import MicroscopeTrial, analysis_file

logger = logging.getLogger(__name__)

LAYOUTS = ("branches", "analysis", "grid")


@dataclass(frozen=True)
class MosaicLayout:
    """Tile origins and the mosaic size for one trial's ROIs."""

    kind: str
    origins: dict[int, tuple[int, int]]
    size: tuple[int, int]
    #: ROI numbers per branch column, for labels and tests; empty unless ``branches``.
    branches: tuple[tuple[int, ...], ...] = field(default=())


def _tile(trial: MicroscopeTrial) -> tuple[int, int]:
    """Display ``(height, width)`` of one ribbon tile."""
    return trial.width, trial.lines


def grid_layout(trial: MicroscopeTrial) -> MosaicLayout:
    """A ``ceil(sqrt(N))`` square grid, across then down, as the lab's analysis lays it."""
    tile_h, tile_w = _tile(trial)
    side = math.ceil(math.sqrt(max(trial.scanned_roi_count, max(trial.roi_numbers, default=1))))
    origins = {
        roi: (((roi - 1) // side) * tile_h, ((roi - 1) % side) * tile_w)
        for roi in trial.roi_numbers
    }
    return MosaicLayout("grid", origins, (side * tile_h, side * tile_w))


def mosaic_roi_map(folder: Path) -> np.ndarray | None:
    """The lab's per-pixel ribbon ROI map in display orientation, if the trial has one."""
    source = analysis_file(folder)
    if source is None:
        return None
    try:
        with h5py.File(source, "r") as handle:
            if "mosaic_info/source_roi_map" not in handle:
                return None
            return np.asarray(handle["mosaic_info/source_roi_map"][()]).T
    except (OSError, KeyError, ValueError):
        logger.warning("Could not read the tile map in %s", source, exc_info=True)
        return None


def analysis_layout(trial: MicroscopeTrial) -> MosaicLayout | None:
    """The lab's analysis mosaic, when the trial has one that fits its tiles."""
    roi_map = mosaic_roi_map(trial.folder)
    if roi_map is None:
        return None
    tile_h, tile_w = _tile(trial)
    origins: dict[int, tuple[int, int]] = {}
    for roi in trial.roi_numbers:
        rows, columns = np.nonzero(roi_map == roi)
        if not len(rows):
            return None
        top, left = int(rows.min()), int(columns.min())
        if (int(rows.max()) - top + 1, int(columns.max()) - left + 1) != (tile_h, tile_w):
            return None
        origins[roi] = (top, left)
    return MosaicLayout("analysis", origins, (int(roi_map.shape[0]), int(roi_map.shape[1])))


def _branch_lengths(folder: Path) -> list[int] | None:
    """Each traced branch's total segment length, in scan order."""
    path = folder / "thin_mask.mat"
    if not path.is_file():
        return None
    try:
        with h5py.File(path, "r") as handle:
            stored = handle.get("branch_projection")
            if not isinstance(stored, h5py.Dataset) or stored.dtype != h5py.ref_dtype:
                return None
            lengths = []
            for reference in np.asarray(stored[()]).reshape(-1):
                target = handle[reference] if reference else None
                if not isinstance(target, h5py.Dataset) or target.ndim != 2:
                    return None
                # Stored (lines, length) like the planes; the length is the long side.
                lengths.append(int(target.shape[1]))
            return lengths
    except (OSError, KeyError, ValueError):
        logger.warning("Could not read branch structure in %s", path, exc_info=True)
        return None


def first_population_roi(folder: Path) -> int | None:
    """First ROI that is a population patch rather than a branch segment, if recorded."""
    source = analysis_file(folder)
    if source is None:
        return None
    try:
        with h5py.File(source, "r") as handle:
            for name in ("hybrid_layout/first_population_roi", "hybrid_info/first_population_roi"):
                stored = handle.get(name)
                if isinstance(stored, h5py.Dataset) and stored.size:
                    value = float(np.asarray(stored[()]).reshape(-1)[0])
                    return int(value) if math.isfinite(value) and value > 0 else None
    except (OSError, KeyError, ValueError):
        logger.warning("Could not read population start in %s", source, exc_info=True)
    return None


def _assign_branches(lengths: list[int], rois: list[int], tile_h: int) -> list[list[int]] | None:
    """Walk ROIs in scan order, closing a branch whenever its length is used up."""
    branches: list[list[int]] = []
    queue = iter(rois)
    for total in lengths:
        members: list[int] = []
        used = 0
        while used < total:
            roi = next(queue, None)
            if roi is None:
                return None
            members.append(roi)
            used += tile_h
        if used != total:
            return None
        branches.append(members)
    return branches if next(queue, None) is None else None


def branch_layout(trial: MicroscopeTrial) -> MosaicLayout | None:
    """The controller-style tree mosaic, when ``thin_mask.mat`` records the branches."""
    lengths = _branch_lengths(trial.folder)
    if not lengths:
        return None
    tile_h, tile_w = _tile(trial)
    every_roi = list(range(1, trial.scanned_roi_count + 1))
    branches = _assign_branches(lengths, every_roi, tile_h)
    if branches is None:
        logger.info("Branch lengths in %s do not partition the ROIs.", trial.folder)
        return None
    population_start = first_population_roi(trial.folder)
    tree = [b for b in branches if population_start is None or b[0] < population_start]
    population = [roi for b in branches if b not in tree for roi in b]

    origins: dict[int, tuple[int, int]] = {}
    height = max((len(b) * tile_h for b in tree), default=0)
    for column, members in enumerate(tree):
        for row, roi in enumerate(members):
            origins[roi] = (row * tile_h, column * tile_w)
    width = len(tree) * tile_w
    if population:
        # Patches pack into columns, a new one whenever the next would overrun:
        # the block is sized to be as square as its pixel count allows.
        ideal_side = math.ceil(math.sqrt(len(population) * tile_h * tile_w))
        per_column = max(1, math.ceil(ideal_side / tile_h))
        for index, roi in enumerate(population):
            column, row = divmod(index, per_column)
            origins[roi] = (row * tile_h, width + column * tile_w)
        height = max(height, min(len(population), per_column) * tile_h)
        width += math.ceil(len(population) / per_column) * tile_w
    kept = {roi: origins[roi] for roi in trial.roi_numbers if roi in origins}
    columns = tuple(tuple(b) for b in tree) + ((tuple(population),) if population else ())
    return MosaicLayout("branches", kept, (height, width), columns)


def choose_layout(trial: MicroscopeTrial, prefer: str = "branches") -> MosaicLayout:
    """The preferred layout when the trial supports it, else the next best."""
    order = {
        "branches": (branch_layout, analysis_layout),
        "analysis": (analysis_layout, branch_layout),
    }.get(prefer, ())
    for build in order:
        layout = build(trial)
        if layout is not None:
            return layout
    return grid_layout(trial)
