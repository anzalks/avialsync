"""Drawing one frame of a stimulus grid: picture rows, labels and sensor bands (D-210)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from avialsync.core.timeline import TimeMap
from avialsync.engine.display_pipeline import to_display_array
from avialsync.engine.pyav_reader import PyAVReader
from avialsync.engine.stimulus_grid_bands import (
    GridBand,
    band_areas,
    draw_band_background,
    draw_band_cursor,
)
from avialsync.engine.stimulus_grid_imaging import ImagingRow
from avialsync.engine.stimulus_grid_layout import (
    _COLUMN_LABEL_HEIGHT,
    _LEFT_GUTTER,
    _RIGHT_GUTTER,
    _TOP_BAND,
    GridLabels,
    GridLayout,
    GridRow,
    GridVideo,
)
from avialsync.engine.stimulus_grid_trace import GridTrace

#: What each row reads from: a camera's reader, mapping and coverage, or an imaging row.
RowReader = tuple[PyAVReader, TimeMap, tuple[float, float]] | ImagingRow


def _render_frame(
    videos: Sequence[GridRow],
    events: Sequence[float],
    readers: dict[int, RowReader],
    layout: GridLayout,
    relative_time: float,
    before: float,
    after: float,
    labels: GridLabels,
    *,
    bands: Sequence[GridBand] = (),
    background: QImage | None = None,
) -> QImage:
    """Compose every row's picture with the shared timing region."""
    static = background or _render_background(
        videos, events, layout, before, after, labels, bands, ()
    )
    image = static.copy()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    for index, row in enumerate(videos):
        reader = readers[index]
        for event_index, event_time in enumerate(events):
            cell = layout.cell_rect(index, event_index)
            master_time = event_time + relative_time
            if isinstance(reader, ImagingRow):
                _draw_picture(painter, cell, reader.image_at(master_time), labels.no_imaging)
            elif isinstance(row, GridVideo):
                _draw_camera_tile(painter, cell, row, *reader, master_time, labels)

    if bands:
        for number, area in enumerate(_band_areas(layout, bands)):
            label = labels.current if number == 0 else None
            draw_band_cursor(painter, area, before, after, relative_time, label)
    else:
        _draw_ruler(painter, layout, before, after, relative_time, labels)
    painter.end()
    return image


def _band_areas(layout: GridLayout, bands: Sequence[GridBand]) -> list[QRect]:
    width = layout.width - _LEFT_GUTTER - _RIGHT_GUTTER
    return band_areas(layout.height - layout.bottom_band, _LEFT_GUTTER, width, bands)


def _render_background(
    videos: Sequence[GridRow],
    events: Sequence[float],
    layout: GridLayout,
    before: float,
    after: float,
    labels: GridLabels,
    bands: Sequence[GridBand],
    traces: Sequence[Sequence[Sequence[GridTrace]]],
) -> QImage:
    """Cache labels and the sensor bands, which do not change between frames."""
    image = QImage(layout.width, layout.height, QImage.Format.Format_RGB888)
    image.fill(QColor("#101719"))
    painter = QPainter(image)
    _draw_grid_labels(painter, videos, events, layout, labels)
    areas = _band_areas(layout, bands)
    for number, (band, area) in enumerate(zip(bands, areas, strict=True)):
        band_traces = traces[number] if number < len(traces) else ((),) * len(band.streams)
        draw_band_background(
            painter,
            area,
            band,
            band_traces,
            before,
            after,
            labels.band.format(label=band.label, count=len(events)),
            labels.no_signal,
            ticks=number == len(bands) - 1,
        )
    painter.end()
    return image


def _draw_grid_labels(
    painter: QPainter,
    videos: Sequence[GridRow],
    events: Sequence[float],
    layout: GridLayout,
    labels: GridLabels,
) -> None:
    """Name each event column and picture row outside the image tiles."""
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

    for index, row in enumerate(videos):
        first_cell = layout.cell_rect(index, 0)
        painter.setPen(QColor("#c3d1cd"))
        painter.drawText(
            QRect(8, first_cell.y(), _LEFT_GUTTER - 16, first_cell.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
            row.label,
        )


def _draw_picture(painter: QPainter, cell: QRect, image: QImage | None, missing: str) -> None:
    """Fit *image* into its cell, or say there is none at this instant."""
    if image is None or image.isNull():
        painter.fillRect(cell, QColor("#20292b"))
        painter.setPen(QColor("#c3d1cd"))
        painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, missing)
        return
    fitted = image.scaled(
        cell.width(),
        cell.height(),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    painter.drawImage(
        QRect(
            cell.x() + (cell.width() - fitted.width()) // 2,
            cell.y() + (cell.height() - fitted.height()) // 2,
            fitted.width(),
            fitted.height(),
        ),
        fitted,
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
    """Draw one decoded camera frame inside its tile."""
    if not bounds[0] <= master_time < bounds[1]:
        _draw_picture(painter, cell, None, labels.no_footage)
        return
    frame_index = reader.index_at_time(time_map.to_source(master_time))
    frame = reader.frame_at_index(frame_index)
    pixels, is_greyscale = to_display_array(frame, video.display_levels)
    pixels = np.ascontiguousarray(pixels)
    image_format = QImage.Format.Format_Grayscale8 if is_greyscale else QImage.Format.Format_RGB888
    tile = QImage(
        pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], image_format
    ).copy()
    _draw_picture(painter, cell, tile, labels.no_footage)


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
