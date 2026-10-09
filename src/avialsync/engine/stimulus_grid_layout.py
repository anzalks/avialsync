"""Geometry of a stimulus grid: picture rows by event columns, sensor bands beneath (D-210)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRect

from avialsync.core.errors import ExportError
from avialsync.core.timeline import TimeMap
from avialsync.engine.display_pipeline import DisplayLevels
from avialsync.engine.stimulus_grid_bands import GridBand, GridStream, stack_height
from avialsync.engine.stimulus_grid_imaging import GridImaging
from avialsync.engine.stimulus_grid_trace import GridSignal

MAX_GRID_EVENTS = 12
MAX_OUTPUT_WIDTH = 2560
MAX_OUTPUT_HEIGHT = 4320
MAX_HIGH_DETAIL_WIDTH = 3840
MAX_HIGH_DETAIL_HEIGHT = 2160
_MAX_CELL_WIDTH = 640
_MAX_HIGH_DETAIL_CELL_WIDTH = 1920
_LEFT_GUTTER = 110
_RIGHT_GUTTER = 28
_TOP_BAND = 44
_COLUMN_LABEL_HEIGHT = 28
_RULER_BAND = 62
_SIGNAL_BAND = 230
_GAP = 1


@dataclass(frozen=True)
class GridVideo:
    """A video and detached snapshots of its timing and display settings."""

    path: Path
    label: str
    time_map: TimeMap = field(default_factory=TimeMap)
    display_levels: DisplayLevels = field(default_factory=DisplayLevels)

    def __post_init__(self) -> None:
        object.__setattr__(self, "time_map", self.time_map.copy())


@dataclass(frozen=True)
class GridLayout:
    """Stable geometry for camera rows and event columns."""

    width: int
    height: int
    cell_width: int
    cell_height: int
    bottom_band: int
    cell_heights: tuple[int, ...] = ()

    def cell_rect(self, camera_index: int, event_index: int) -> QRect:
        """Return the image bounds for one camera and event."""
        row_heights = self.cell_heights or (self.cell_height,) * (camera_index + 1)
        row_height = row_heights[camera_index]
        row_offset = sum(row_heights[:camera_index]) + camera_index * _GAP
        return QRect(
            _LEFT_GUTTER + event_index * (self.cell_width + _GAP),
            _TOP_BAND + _COLUMN_LABEL_HEIGHT + row_offset,
            self.cell_width,
            row_height,
        )


@dataclass(frozen=True)
class GridLabels:
    """Translated text templates supplied by the UI layer."""

    title: str
    event: str
    no_footage: str
    ruler: str
    current: str
    no_signal: str
    frame: str
    no_imaging: str = "No imaging data"
    band: str = "{label} · mean of {count} events"


#: A picture row: a camera, or an imaging stack as the viewer shows it.
GridRow = GridVideo | GridImaging


def band_for_signal(signal: GridSignal) -> GridBand:
    """The single trigger-channel band the grid has always drawn, as a band."""
    stream = GridStream(signal.reference, signal.label, (94, 215, 229))
    return GridBand(signal.label, (stream,), threshold=signal.threshold)


def plan_grid(
    video_count: int,
    event_count: int,
    before: float,
    after: float,
    *,
    has_signal: bool = False,
    high_detail: bool = False,
    cell_aspect_ratio: float = 16 / 9,
    cell_aspect_ratios: Sequence[float] | None = None,
    bands: Sequence[GridBand] = (),
) -> GridLayout:
    """Validate a grid request and calculate its fixed output dimensions.

    *video_count* counts every picture row, cameras and imaging alike. *bands*
    take their own heights below the rows; without any, *has_signal* reserves
    the single signal band the grid has always had, and otherwise a ruler.
    """
    if video_count < 1:
        raise ExportError("At least one video is required.")
    if not 1 <= event_count <= MAX_GRID_EVENTS:
        raise ExportError(f"Select between 1 and {MAX_GRID_EVENTS} stimulus events.")
    if not np.isfinite(before) or not np.isfinite(after) or before < 0 or after <= 0:
        raise ExportError("The before window must be non-negative and the after window positive.")
    duration = before + after
    if not np.isfinite(duration):
        raise ExportError("The combined stimulus window must be finite.")
    aspect_ratios = (
        (cell_aspect_ratio,) * video_count
        if cell_aspect_ratios is None
        else tuple(cell_aspect_ratios)
    )
    if len(aspect_ratios) != video_count or any(
        not np.isfinite(ratio) or ratio <= 0 for ratio in aspect_ratios
    ):
        raise ExportError("Each row must have a finite, positive aspect ratio.")
    max_width, max_height, max_cell_width = (
        (MAX_HIGH_DETAIL_WIDTH, MAX_HIGH_DETAIL_HEIGHT, _MAX_HIGH_DETAIL_CELL_WIDTH)
        if high_detail
        else (MAX_OUTPUT_WIDTH, MAX_OUTPUT_HEIGHT, _MAX_CELL_WIDTH)
    )
    if bands:
        bottom_band = stack_height(bands)
    else:
        bottom_band = _SIGNAL_BAND if has_signal else _RULER_BAND
    available = max_width - _LEFT_GUTTER - _RIGHT_GUTTER - _GAP * (event_count - 1)
    height_for_rows = max_height - _TOP_BAND - _COLUMN_LABEL_HEIGHT - bottom_band
    height_for_rows -= _GAP * (video_count - 1)
    width_for_height = int(height_for_rows / sum(1 / ratio for ratio in aspect_ratios))
    cell_width = min(max_cell_width, available // event_count, width_for_height)
    if cell_width < 96:
        raise ExportError("Too many rows, sensor bands or events to fit in the export grid.")
    cell_heights = tuple(round(cell_width / ratio) for ratio in aspect_ratios)
    cell_height = max(cell_heights)
    width = _LEFT_GUTTER + event_count * cell_width + (event_count - 1) * _GAP + _RIGHT_GUTTER
    height = (
        _TOP_BAND
        + _COLUMN_LABEL_HEIGHT
        + sum(cell_heights)
        + _GAP * (video_count - 1)
        + bottom_band
    )
    if height > max_height:
        raise ExportError("Too many rows or sensor bands to fit in the export grid.")
    width += width % 2
    height += height % 2
    return GridLayout(width, height, cell_width, cell_height, bottom_band, cell_heights)
