"""Draw observed ladder clicks and distinguish projected geometry (D-149)."""

from __future__ import annotations

from typing import TypeAlias

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen

PropPixel: TypeAlias = tuple[float, float, bool] | None
PropDrawing: TypeAlias = tuple[str, tuple[PropPixel, ...], bool]


def draw_props(
    painter: QPainter,
    drawings: list[PropDrawing],
    scale: float,
    offset_x: float,
    offset_y: float,
) -> None:
    """Draw each declared step without joining across absent observations."""
    color = QColor(245, 195, 80)
    for label, points, closed in drawings:
        for index, point in enumerate(points):
            if point is None:
                continue
            x = round(offset_x + point[0] * scale)
            y = round(offset_y + point[1] * scale)
            pen = QPen(color, 2)
            if not point[2]:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(x - 4, y - 4, 8, 8)
            if index == 0:
                painter.drawText(x + 7, y - 6, label)
            next_index = index + 1 if index + 1 < len(points) else 0 if closed else -1
            if next_index < 0 or points[next_index] is None:
                continue
            other = points[next_index]
            assert other is not None
            if not (point[2] and other[2]):
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
            painter.drawLine(
                x,
                y,
                round(offset_x + other[0] * scale),
                round(offset_y + other[1] * scale),
            )
