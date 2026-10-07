"""Every ROI of an NWB plane segmentation tiled in one imaging picture (D-193)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")

from avialsync.core.registry import LoaderRegistry  # noqa: E402
from avialsync.loaders.nwb_roi_grid import NWBRoiGridSource, find_roi_grids  # noqa: E402
from avialsync.loaders.nwb_session import NWBSessionSource  # noqa: E402
from tests.nwb_fixture import (  # noqa: E402
    IMAGING_FRAMES,
    IMAGING_SHAPE,
    ROI_IDS,
    NWBSpec,
    _imaging_frames,
    write_nwb,
)

_SEGMENTATION = "/processing/ophys/ImageSegmentation/PlaneSegmentation"


def _open(path: Path) -> tuple[NWBRoiGridSource, object]:
    source = NWBRoiGridSource()
    return source, source.open(path / _SEGMENTATION.lstrip("/"), {})


def _tile(mosaic: np.ndarray, source: NWBRoiGridSource, position: int) -> np.ndarray:
    tile_h, tile_w = source._tile
    row, column = divmod(position, source._grid[1])
    return mosaic[
        row * tile_h : (row + 1) * tile_h - 1, column * tile_w : (column + 1) * tile_w - 1
    ]


def test_rois_on_an_imaged_plane_tile_the_raw_pixels(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb")
    grids = find_roi_grids(path)
    assert [(g.path, g.roi_count, g.mode) for g in grids] == [(_SEGMENTATION, 3, "raw")]
    source, metadata = _open(path)
    try:
        assert metadata.frame_count == IMAGING_FRAMES
        assert source.label() == "3 ROIs — raw crops"
        frame = source.read_frame(2)
        expected = _imaging_frames("uint16")[2].astype(np.float32)
        for position in range(len(ROI_IDS)):
            assert np.array_equal(_tile(frame, source, position), expected)
    finally:
        source.close()


def test_rois_without_a_movie_show_their_response_on_the_mask(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb", NWBSpec(imaging=False))
    assert [g.mode for g in find_roi_grids(path)] == ["response"]
    source, metadata = _open(path)
    try:
        assert source.label() == "3 ROIs — DfOverF on ROI masks", "ΔF/F before fluorescence"
        assert metadata.height, metadata.width == IMAGING_SHAPE
        frame = source.read_frame(4)
        with h5py.File(path, "r", locking=False) as handle:
            values = handle["processing/ophys/DfOverF/RoiResponseSeries/data"][4]
        for position, value in enumerate(values):
            tile = _tile(frame, source, position)
            assert np.all(tile == np.float32(value)), "a map of the measured trace, nothing else"
    finally:
        source.close()


def test_patch_masks_tile_one_cell_each_cropped_to_the_cell(tmp_path: Path) -> None:
    """Patch-scanned files lay each ROI's window side by side; each tile is one patch."""
    path = write_nwb(tmp_path / "s.nwb", NWBSpec(imaging=False))
    height, width = IMAGING_SHAPE
    rows = []
    for roi in range(len(ROI_IDS)):
        for y in range(height):
            for x in range(width):
                inside = 2 <= y < height - 2 and 2 <= x < width - 2
                rows.append((roi * width + x, y, 1.0 if inside else 0.0))
    pixels = np.array(rows, dtype=[("x", "<u4"), ("y", "<u4"), ("weight", "<f4")])
    with h5py.File(path, "r+") as handle:
        table = handle[_SEGMENTATION]
        del table["image_mask"]
        table.create_dataset("pixel_mask", data=pixels)
        table.create_dataset(
            "pixel_mask_index", data=np.arange(1, len(ROI_IDS) + 1) * height * width
        )
    source, _metadata = _open(path)
    try:
        tile = _tile(source.read_frame(0), source, 1)
        height, width = IMAGING_SHAPE
        assert tile.shape == (height - 4, width - 4), "the tile fits the cell, not its patch"
        assert np.isfinite(tile).all()
    finally:
        source.close()


def test_the_session_offers_the_grid_beside_the_series(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb")
    layout = NWBSessionSource().scan(path, LoaderRegistry())
    grid = [item for item in layout.items if item.loader is NWBRoiGridSource]
    assert len(grid) == 1
    assert grid[0].path == path / _SEGMENTATION.lstrip("/")
    assert "3 ROIs (raw crops)" in grid[0].label
    assert LoaderRegistry().find_best_loader(grid[0].path) is NWBRoiGridSource
