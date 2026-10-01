"""Render event-aligned video comparisons as one encoded movie."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from avialsync.core.errors import ExportError
from avialsync.core.timeline import TimeMap
from avialsync.engine.display_pipeline import DisplayLevels, to_display_array
from avialsync.engine.pyav_reader import PyAVReader
from avialsync.engine.transcode import (
    CancelCheck,
    ProgressCallback,
    TranscodeCancelled,
    encode_video,
)

MAX_GRID_EVENTS = 12
MAX_OUTPUT_WIDTH = 2560
MAX_OUTPUT_HEIGHT = 4320
_MAX_CELL_WIDTH = 640
_LEFT_GUTTER = 110
_RIGHT_GUTTER = 28
_TOP_BAND = 44
_CELL_LABEL_HEIGHT = 26
_ROW_LABEL_HEIGHT = 28
_BOTTOM_BAND = 62
_GAP = 6
logger = logging.getLogger(__name__)


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
    """Stable geometry for an event-by-camera comparison grid."""

    width: int
    height: int
    cell_width: int
    cell_height: int
    trigger_x: int


@dataclass(frozen=True)
class GridLabels:
    """Translated text templates supplied by the UI layer."""

    title: str
    event: str
    no_footage: str
    ruler: str
    current: str


def plan_grid(
    video_count: int,
    event_count: int,
    before: float,
    after: float,
) -> GridLayout:
    """Validate a grid request and calculate its fixed output dimensions."""
    if video_count < 1:
        raise ExportError("At least one video is required.")
    if not 1 <= event_count <= MAX_GRID_EVENTS:
        raise ExportError(f"Select between 1 and {MAX_GRID_EVENTS} stimulus events.")
    if not np.isfinite(before) or not np.isfinite(after) or before < 0 or after <= 0:
        raise ExportError("The before window must be non-negative and the after window positive.")
    duration = before + after
    if not np.isfinite(duration):
        raise ExportError("The combined stimulus window must be finite.")
    available = MAX_OUTPUT_WIDTH - _LEFT_GUTTER - _RIGHT_GUTTER - _GAP * (video_count - 1)
    height_for_cells = (
        MAX_OUTPUT_HEIGHT
        - _TOP_BAND
        - _BOTTOM_BAND
        - event_count * (_ROW_LABEL_HEIGHT + _CELL_LABEL_HEIGHT + _GAP)
    ) // event_count
    width_for_height = int(height_for_cells * 16 / 9)
    cell_width = max(96, min(_MAX_CELL_WIDTH, available // video_count, width_for_height))
    cell_height = max(64, round(cell_width * 9 / 16))
    width = _LEFT_GUTTER + video_count * cell_width + (video_count - 1) * _GAP + _RIGHT_GUTTER
    height = (
        _TOP_BAND
        + event_count * (_ROW_LABEL_HEIGHT + cell_height + _CELL_LABEL_HEIGHT + _GAP)
        + _BOTTOM_BAND
    )
    width += width % 2
    height += height % 2
    trigger_x = round(cell_width * before / duration)
    return GridLayout(width, height, cell_width, cell_height, trigger_x)


def export_stimulus_grid(
    videos: Sequence[GridVideo],
    event_times: Sequence[float],
    before: float,
    after: float,
    destination: Path,
    labels: GridLabels,
    *,
    fps: int = 30,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> None:
    """Encode selected event windows as rows and cameras as columns.

    Every row advances through the same relative-time window, so the trigger
    lands on one shared vertical line. Missing coverage is rendered explicitly
    rather than extending a camera's first or last frame into the window.
    """
    if fps < 1 or fps > 120:
        raise ExportError("Output frame rate must be between 1 and 120 fps.")
    if not videos:
        raise ExportError("At least one video is required.")
    if not event_times or len(event_times) > MAX_GRID_EVENTS:
        raise ExportError(f"Select between 1 and {MAX_GRID_EVENTS} stimulus events.")
    events = tuple(float(time) for time in event_times)
    if not all(np.isfinite(time) for time in events) or any(
        right <= left for left, right in zip(events, events[1:], strict=False)
    ):
        raise ExportError("Stimulus event times must be finite and strictly increasing.")
    layout = plan_grid(len(videos), len(events), before, after)
    duration = before + after
    frame_count = max(1, int(np.ceil(duration * fps)))
    destination.parent.mkdir(parents=True, exist_ok=True)

    with ExitStack() as stack:
        readers: dict[int, tuple[PyAVReader, TimeMap, tuple[float, float]]] = {}
        for video_index, video in enumerate(videos):
            reader = stack.enter_context(PyAVReader(video.path, max_cached_frames=2))
            reader.stream.thread_type = "SLICE"
            time_map = video.time_map
            source_times = reader.frame_times
            bounds = (
                time_map.to_master(float(source_times[0])),
                time_map.to_master(float(source_times[-1])),
            )
            readers[video_index] = (reader, time_map, bounds)

        def frames() -> Iterator[tuple[np.ndarray, float]]:
            for frame_index in range(frame_count):
                if should_cancel is not None and should_cancel():
                    raise TranscodeCancelled
                relative_time = frame_index / fps - before
                image = _render_frame(
                    videos, events, readers, layout, relative_time, before, after, labels
                )
                yield _image_to_rgb(image), frame_index / fps

        def report_progress(seconds: float) -> None:
            if progress is not None:
                progress(min(1.0, (seconds + 1.0 / fps) / duration))

        encode_video(
            destination,
            frames(),
            rate=Fraction(fps, 1),
            progress=report_progress if progress is not None else None,
            should_cancel=should_cancel,
        )


def _render_frame(
    videos: Sequence[GridVideo],
    events: Sequence[float],
    readers: dict[int, tuple[PyAVReader, TimeMap, tuple[float, float]]],
    layout: GridLayout,
    relative_time: float,
    before: float,
    after: float,
    labels: GridLabels,
) -> QImage:
    """Compose decoded tiles, event labels, a trigger line, and the time ruler."""
    image = QImage(layout.width, layout.height, QImage.Format.Format_RGB888)
    image.fill(QColor("#101719"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setPen(QColor("#f1f4f2"))
    painter.setFont(QFont("Arial", 11, QFont.Weight.DemiBold))
    painter.drawText(
        QRect(12, 0, layout.width - 24, _TOP_BAND),
        Qt.AlignmentFlag.AlignVCenter,
        labels.title,
    )

    for video_index, video in enumerate(videos):
        x = _LEFT_GUTTER + video_index * (layout.cell_width + _GAP)
        painter.setPen(QColor("#c3d1cd"))
        painter.drawText(
            QRect(x, _TOP_BAND, layout.cell_width, _CELL_LABEL_HEIGHT),
            Qt.AlignmentFlag.AlignVCenter,
            video.label,
        )

    for event_index, event_time in enumerate(events):
        row_y = _TOP_BAND + event_index * (
            _ROW_LABEL_HEIGHT + layout.cell_height + _CELL_LABEL_HEIGHT + _GAP
        )
        painter.setPen(QColor("#c3d1cd"))
        painter.setFont(QFont("Arial", 9))
        painter.drawText(
            QRect(8, row_y, _LEFT_GUTTER - 16, _ROW_LABEL_HEIGHT),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            labels.event.format(index=event_index + 1, time=event_time),
        )
        top = row_y + _ROW_LABEL_HEIGHT
        master_time = event_time + relative_time
        for video_index, video in enumerate(videos):
            x = _LEFT_GUTTER + video_index * (layout.cell_width + _GAP)
            reader, time_map, bounds = readers[video_index]
            if bounds[0] <= master_time <= bounds[1]:
                frame = reader.frame_at_time(time_map.to_source(master_time))
                pixels, is_greyscale = to_display_array(frame, video.display_levels)
                pixels = np.ascontiguousarray(pixels)
                image_format = (
                    QImage.Format.Format_Grayscale8 if is_greyscale else QImage.Format.Format_RGB888
                )
                tile = QImage(
                    pixels.data,
                    pixels.shape[1],
                    pixels.shape[0],
                    pixels.strides[0],
                    image_format,
                ).copy()
                fitted = tile.scaled(
                    layout.cell_width,
                    layout.cell_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                target = QRect(
                    x + (layout.cell_width - fitted.width()) // 2,
                    top + (layout.cell_height - fitted.height()) // 2,
                    fitted.width(),
                    fitted.height(),
                )
                painter.drawImage(target, fitted)
            else:
                painter.fillRect(
                    QRect(x, top, layout.cell_width, layout.cell_height), QColor("#20292b")
                )
                painter.setPen(QColor("#c3d1cd"))
                painter.drawText(
                    QRect(x, top, layout.cell_width, layout.cell_height),
                    Qt.AlignmentFlag.AlignCenter,
                    labels.no_footage,
                )
            painter.setPen(QPen(QColor("#ef665d"), 2))
            trigger_x = x + layout.trigger_x
            painter.drawLine(trigger_x, top, trigger_x, top + layout.cell_height)
            painter.setPen(QColor("#c3d1cd"))
            painter.drawText(
                QRect(x, top + layout.cell_height, layout.cell_width, _CELL_LABEL_HEIGHT),
                Qt.AlignmentFlag.AlignVCenter,
                f"{video.label}  ·  {relative_time:+.2f} s",
            )

    _draw_ruler(painter, layout, len(videos), before, after, relative_time, labels)
    painter.end()
    return image


def _draw_ruler(
    painter: QPainter,
    layout: GridLayout,
    video_count: int,
    before: float,
    after: float,
    relative_time: float,
    labels: GridLabels,
) -> None:
    """Draw matching relative-time scales beneath every camera column."""
    y = layout.height - _BOTTOM_BAND + 12
    painter.setFont(QFont("Arial", 9))
    for video_index in range(video_count):
        left = _LEFT_GUTTER + video_index * (layout.cell_width + _GAP)
        right = left + layout.cell_width
        painter.setPen(QPen(QColor("#879894"), 1))
        painter.drawLine(left, y, right, y)
        painter.setPen(QColor("#c3d1cd"))
        painter.drawText(
            QRect(left, y + 8, layout.cell_width, 20),
            Qt.AlignmentFlag.AlignCenter,
            labels.ruler.format(before=-before, after=after),
        )
        trigger_x = left + layout.trigger_x
        current_x = left + round(layout.cell_width * (before + relative_time) / (before + after))
        painter.setPen(QPen(QColor("#ef665d"), 2))
        painter.drawLine(trigger_x, y - 8, trigger_x, y + 5)
        painter.setPen(QPen(QColor("#f1f4f2"), 1))
        painter.drawLine(current_x, y - 5, current_x, y + 5)
        painter.drawText(
            QRect(left, y + 30, layout.cell_width, 20),
            Qt.AlignmentFlag.AlignCenter,
            labels.current.format(time=relative_time),
        )


def _image_to_rgb(image: QImage) -> np.ndarray:
    """Copy a QImage's padded rows into the contiguous RGB array PyAV expects."""
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    data = np.frombuffer(rgb.constBits(), dtype=np.uint8, count=rgb.sizeInBytes())
    rows = data.reshape(rgb.height(), rgb.bytesPerLine())
    return rows[:, : rgb.width() * 3].reshape(rgb.height(), rgb.width(), 3).copy()
