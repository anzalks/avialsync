"""Shared geometry for near-square ROI grids (D-193)."""

from __future__ import annotations

import math

import numpy as np

from avialsync.core.errors import SourceOpenError


def geometry(
    crops: list[np.ndarray], gutter: int = 1
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """Return ``(rows, columns)``, padded tile size and output size for crops."""
    if not crops:
        raise SourceOpenError("An ROI grid needs at least one crop.")
    tile_h = max(crop.shape[0] for crop in crops) + gutter
    tile_w = max(crop.shape[1] for crop in crops) + gutter
    columns = max(1, math.ceil(math.sqrt(len(crops) * tile_h / tile_w)))
    rows = math.ceil(len(crops) / columns)
    return (rows, columns), (tile_h, tile_w), (rows * tile_h - gutter, columns * tile_w - gutter)


def pack(
    tiles: list[np.ndarray],
    grid: tuple[int, int],
    tile_size: tuple[int, int],
    output_size: tuple[int, int],
) -> np.ndarray:
    """Place same-order image crops into a NaN-padded tile grid."""
    mosaic = np.full((grid[0] * tile_size[0], grid[1] * tile_size[1]), np.nan, np.float32)
    for position, tile in enumerate(tiles):
        row, column = divmod(position, grid[1])
        top, left = row * tile_size[0], column * tile_size[1]
        mosaic[top : top + tile.shape[0], left : left + tile.shape[1]] = tile
    return mosaic[: output_size[0], : output_size[1]]


def mask_crop(mask: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
    """Crop a non-empty boolean mask to its bounding box and return top-left."""
    rows, columns = np.nonzero(mask)
    if not len(rows):
        return np.zeros((1, 1), dtype=bool), (0, 0)
    top, left = int(rows.min()), int(columns.min())
    return np.asarray(mask[top : rows.max() + 1, left : columns.max() + 1], dtype=bool), (top, left)
