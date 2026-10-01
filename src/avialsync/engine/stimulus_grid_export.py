"""Render event-aligned video comparisons as one encoded movie."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, field
from fractions import Fraction
from heapq import merge
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from avialsync.core.errors import ExportError
from avialsync.core.timeline import TimeMap
from avialsync.engine.display_pipeline import DisplayLevels, to_display_array
from avialsync.engine.pyav_reader import PyAVReader
from avialsync.engine.stimulus_grid_trace import (
    GridSignal,
    GridTrace,
    draw_signal_trace,
)
from avialsync.engine.stimulus_grid_trace import (
    read_signal_traces as _read_signal_traces,
)
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
_COLUMN_LABEL_HEIGHT = 28
_RULER_BAND = 62
_SIGNAL_BAND = 230
_GAP = 1
logger = logging.getLogger(__name__)
_OUTPUT_TICKS_PER_SECOND = 1_000_000


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

    def cell_rect(self, camera_index: int, event_index: int) -> QRect:
        """Return the image bounds for one camera and event."""
        return QRect(
            _LEFT_GUTTER + event_index * (self.cell_width + _GAP),
            _TOP_BAND + _COLUMN_LABEL_HEIGHT + camera_index * (self.cell_height + _GAP),
            self.cell_width,
            self.cell_height,
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


def plan_grid(
    video_count: int,
    event_count: int,
    before: float,
    after: float,
    *,
    has_signal: bool = False,
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
    bottom_band = _SIGNAL_BAND if has_signal else _RULER_BAND
    available = MAX_OUTPUT_WIDTH - _LEFT_GUTTER - _RIGHT_GUTTER - _GAP * (event_count - 1)
    height_for_cells = (
        MAX_OUTPUT_HEIGHT - _TOP_BAND - _COLUMN_LABEL_HEIGHT - bottom_band - video_count * _GAP
    ) // video_count
    width_for_height = int(height_for_cells * 16 / 9)
    cell_width = min(_MAX_CELL_WIDTH, available // event_count, width_for_height)
    if cell_width < 96:
        raise ExportError("Too many cameras or events to fit in the export grid.")
    cell_height = round(cell_width * 9 / 16)
    width = _LEFT_GUTTER + event_count * cell_width + (event_count - 1) * _GAP + _RIGHT_GUTTER
    height = _TOP_BAND + _COLUMN_LABEL_HEIGHT + video_count * (cell_height + _GAP) + bottom_band
    if height > MAX_OUTPUT_HEIGHT:
        raise ExportError("Too many cameras to fit in the export grid.")
    width += width % 2
    height += height % 2
    return GridLayout(width, height, cell_width, cell_height, bottom_band)


def export_stimulus_grid(
    videos: Sequence[GridVideo],
    event_times: Sequence[float],
    before: float,
    after: float,
    destination: Path,
    labels: GridLabels,
    *,
    fps: int = 30,
    playback_speed: float = 1.0,
    signal: GridSignal | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> None:
    """Encode cameras as rows and selected event windows as columns.

    Every column advances through the same relative-time window. Each source
    frame transition is retained at its mapped presentation time; ``fps`` sets
    the base cadence between transitions. Missing coverage is explicit.
    """
    if fps < 1 or fps > 120:
        raise ExportError("Output frame rate must be between 1 and 120 fps.")
    if not np.isfinite(playback_speed) or not 0.01 <= playback_speed <= 10.0:
        raise ExportError("Playback speed must be between 0.01x and 10x.")
    if not videos:
        raise ExportError("At least one video is required.")
    if not event_times or len(event_times) > MAX_GRID_EVENTS:
        raise ExportError(f"Select between 1 and {MAX_GRID_EVENTS} stimulus events.")
    events = tuple(float(time) for time in event_times)
    if not all(np.isfinite(time) for time in events) or any(
        right <= left for left, right in zip(events, events[1:], strict=False)
    ):
        raise ExportError("Stimulus event times must be finite and strictly increasing.")
    layout = plan_grid(len(videos), len(events), before, after, has_signal=signal is not None)
    duration = before + after
    output_duration = duration / playback_speed
    destination.parent.mkdir(parents=True, exist_ok=True)
    traces = _read_signal_traces(signal, events, before, after, layout.width) if signal else ()

    with ExitStack() as stack:
        readers: dict[int, tuple[PyAVReader, TimeMap, tuple[float, float]]] = {}
        for video_index, video in enumerate(videos):
            reader = stack.enter_context(PyAVReader(video.path, max_cached_frames=2))
            reader.stream.thread_type = "SLICE"
            time_map = video.time_map
            bounds = _reader_bounds(reader, time_map)
            readers[video_index] = (reader, time_map, bounds)

        def frames() -> Iterator[tuple[np.ndarray, float]]:
            for output_time in _frame_schedule(readers, events, before, after, fps, playback_speed):
                if should_cancel is not None and should_cancel():
                    raise TranscodeCancelled
                relative_time = output_time * playback_speed - before
                image = _render_frame(
                    videos,
                    events,
                    readers,
                    layout,
                    relative_time,
                    before,
                    after,
                    labels,
                    signal=signal,
                    traces=traces,
                )
                yield _image_to_rgb(image), output_time

        def report_progress(seconds: float) -> None:
            if progress is not None:
                progress(min(1.0, seconds / output_duration))

        encode_video(
            destination,
            frames(),
            rate=Fraction(fps, 1),
            time_base=Fraction(1, _OUTPUT_TICKS_PER_SECOND),
            end_seconds=output_duration,
            progress=report_progress if progress is not None else None,
            should_cancel=should_cancel,
        )
        if progress is not None:
            progress(1.0)


def _frame_schedule(
    readers: dict[int, tuple[PyAVReader, TimeMap, tuple[float, float]]],
    events: Sequence[float],
    before: float,
    after: float,
    fps: int,
    playback_speed: float,
) -> Iterator[float]:
    """Merge each tile's real frame changes into one presentation timeline."""
    ticks_per_second = _OUTPUT_TICKS_PER_SECOND
    end_tick = int(round((before + after) * ticks_per_second / playback_speed))
    step_ticks = max(1, round(ticks_per_second / fps))
    # Rounded source PTS can land slightly beside a nominal cadence tick.
    # Treat them as one update instead of creating a near-zero duplicate frame.
    cadence_tolerance = max(10, round(step_ticks * 0.01))

    def tile_ticks(
        reader: PyAVReader, mapping: TimeMap, bounds: tuple[float, float], event: float
    ) -> Iterator[int]:
        start = mapping.to_source(event - before)
        end = mapping.to_source(event + after)
        times = reader.frame_times
        first = int(np.searchsorted(times, start, side="left"))
        stop = int(np.searchsorted(times, end, side="left"))
        for source_time in times[first:stop]:
            elapsed = (mapping.to_master(float(source_time)) - event + before) / playback_speed
            # The rendered instant must never precede this source frame's PTS.
            tick = int(np.ceil(elapsed * ticks_per_second - 1e-9))
            if 0 < tick < end_tick:
                yield tick
        coverage_end = (bounds[1] - event + before) / playback_speed
        tick = int(np.ceil(coverage_end * ticks_per_second - 1e-9))
        if 0 < tick < end_tick:
            yield tick

    timelines = (
        tile_ticks(reader, mapping, bounds, event)
        for reader, mapping, bounds in readers.values()
        for event in events
    )
    previous = 0
    yield 0.0
    for tick in merge(*timelines):
        if tick <= previous:
            continue
        while tick - previous > step_ticks + cadence_tolerance:
            previous += step_ticks
            yield previous / ticks_per_second
        previous = tick
        yield tick / ticks_per_second
    while end_tick - previous > step_ticks + cadence_tolerance:
        previous += step_ticks
        yield previous / ticks_per_second


def _reader_bounds(reader: PyAVReader, time_map: TimeMap) -> tuple[float, float]:
    """Include the last frame's presentation interval in source coverage."""
    times = reader.frame_times
    intervals = np.diff(times[-17:])
    positive = intervals[intervals > 0]
    if len(positive):
        final_interval = float(np.median(positive))
    else:
        nominal_rate = reader.stream.average_rate or reader.stream.base_rate
        final_interval = 1.0 / float(nominal_rate) if nominal_rate else 1.0 / 30.0
    return (
        time_map.to_master(float(times[0])),
        time_map.to_master(float(times[-1]) + final_interval),
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
    *,
    signal: GridSignal | None = None,
    traces: Sequence[GridTrace] = (),
) -> QImage:
    """Compose decoded tiles with frame badges and the shared timing region."""
    image = QImage(layout.width, layout.height, QImage.Format.Format_RGB888)
    image.fill(QColor("#101719"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    _draw_grid_labels(painter, videos, events, layout, labels)

    for video_index, video in enumerate(videos):
        reader, time_map, bounds = readers[video_index]
        for event_index, event_time in enumerate(events):
            _draw_camera_tile(
                painter,
                layout.cell_rect(video_index, event_index),
                video,
                reader,
                time_map,
                bounds,
                event_time + relative_time,
                labels,
            )

    if signal is not None:
        draw_signal_trace(
            painter,
            QRect(
                _LEFT_GUTTER,
                layout.height - layout.bottom_band + 29,
                layout.width - _LEFT_GUTTER - _RIGHT_GUTTER,
                145,
            ),
            traces,
            signal,
            before,
            after,
            relative_time,
            labels.no_signal,
            labels.current,
        )
    else:
        _draw_ruler(painter, layout, before, after, relative_time, labels)
    painter.end()
    return image


def _draw_grid_labels(
    painter: QPainter,
    videos: Sequence[GridVideo],
    events: Sequence[float],
    layout: GridLayout,
    labels: GridLabels,
) -> None:
    """Name each event column and camera row outside the image tiles."""
    painter.setPen(QColor("#f1f4f2"))
    painter.setFont(QFont("Arial", 11, QFont.Weight.DemiBold))
    painter.drawText(
        QRect(12, 0, layout.width - 24, _TOP_BAND),
        Qt.AlignmentFlag.AlignVCenter,
        labels.title,
    )

    for event_index, event_time in enumerate(events):
        x = layout.cell_rect(0, event_index).x()
        painter.setPen(QColor("#c3d1cd"))
        painter.setFont(QFont("Arial", 9))
        painter.drawText(
            QRect(x, _TOP_BAND, layout.cell_width, _COLUMN_LABEL_HEIGHT),
            Qt.AlignmentFlag.AlignCenter,
            labels.event.format(index=event_index + 1, time=event_time),
        )

    for video_index, video in enumerate(videos):
        first_cell = layout.cell_rect(video_index, 0)
        painter.setPen(QColor("#c3d1cd"))
        painter.drawText(
            QRect(8, first_cell.y(), _LEFT_GUTTER - 16, layout.cell_height),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            video.label,
        )


def _draw_camera_tile(
    painter: QPainter,
    cell: QRect,
    video: GridVideo,
    reader: PyAVReader,
    time_map: TimeMap,
    bounds: tuple[float, float],
    master_time: float,
    labels: GridLabels,
) -> None:
    """Draw one decoded camera frame and its absolute index inside the tile."""
    if bounds[0] <= master_time < bounds[1]:
        frame_index = reader.index_at_time(time_map.to_source(master_time))
        frame = reader.frame_at_index(frame_index)
        pixels, is_greyscale = to_display_array(frame, video.display_levels)
        pixels = np.ascontiguousarray(pixels)
        image_format = (
            QImage.Format.Format_Grayscale8 if is_greyscale else QImage.Format.Format_RGB888
        )
        tile = QImage(
            pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], image_format
        ).copy()
        fitted = tile.scaled(
            cell.width(),
            cell.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        image_rect = QRect(
            cell.x() + (cell.width() - fitted.width()) // 2,
            cell.y() + (cell.height() - fitted.height()) // 2,
            fitted.width(),
            fitted.height(),
        )
        painter.drawImage(image_rect, fitted)
        _draw_frame_badge(painter, image_rect, labels.frame.format(index=frame_index))
    else:
        painter.fillRect(cell, QColor("#20292b"))
        painter.setPen(QColor("#c3d1cd"))
        painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, labels.no_footage)


def _draw_frame_badge(painter: QPainter, cell: QRect, caption: str) -> None:
    """Keep the frame index readable against light and dark camera footage."""
    font = QFont("Arial", 12, QFont.Weight.DemiBold)
    painter.setFont(font)
    metrics = painter.fontMetrics()
    while metrics.horizontalAdvance(caption) > cell.width() - 20 and font.pointSize() > 6:
        font.setPointSize(font.pointSize() - 1)
        painter.setFont(font)
        metrics = painter.fontMetrics()
    badge_width = min(cell.width() - 8, metrics.horizontalAdvance(caption) + 12)
    badge = QRect(cell.x() + 4, cell.bottom() - 29, badge_width, 26)
    painter.fillRect(badge, QColor(16, 23, 25, 210))
    painter.setPen(QColor("#f1f4f2"))
    painter.drawText(badge.adjusted(6, 0, -3, 0), Qt.AlignmentFlag.AlignVCenter, caption)


def _draw_ruler(
    painter: QPainter,
    layout: GridLayout,
    before: float,
    after: float,
    relative_time: float,
    labels: GridLabels,
) -> None:
    """Draw one relative-time scale beneath the whole comparison grid."""
    y = layout.height - layout.bottom_band + 12
    left = _LEFT_GUTTER
    width = layout.width - _LEFT_GUTTER - _RIGHT_GUTTER
    painter.setFont(QFont("Arial", 9))
    painter.setPen(QPen(QColor("#879894"), 1))
    painter.drawLine(left, y, left + width, y)
    painter.setPen(QColor("#c3d1cd"))
    painter.drawText(
        QRect(left, y + 8, width, 20),
        Qt.AlignmentFlag.AlignCenter,
        labels.ruler.format(before=-before, after=after),
    )
    trigger_x = left + round(width * before / (before + after))
    current_x = left + round(width * (before + relative_time) / (before + after))
    painter.setPen(QPen(QColor("#ef665d"), 2))
    painter.drawLine(trigger_x, y - 8, trigger_x, y + 5)
    painter.setPen(QPen(QColor("#f1f4f2"), 1))
    painter.drawLine(current_x, y - 5, current_x, y + 5)
    painter.drawText(
        QRect(left, y + 30, width, 20),
        Qt.AlignmentFlag.AlignCenter,
        labels.current.format(time=relative_time),
    )


def _image_to_rgb(image: QImage) -> np.ndarray:
    """Copy a QImage's padded rows into the contiguous RGB array PyAV expects."""
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    data = np.frombuffer(rgb.constBits(), dtype=np.uint8, count=rgb.sizeInBytes())
    rows = data.reshape(rgb.height(), rgb.bytesPerLine())
    return rows[:, : rgb.width() * 3].reshape(rgb.height(), rgb.width(), 3).copy()
