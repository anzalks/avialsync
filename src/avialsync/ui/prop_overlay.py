"""Draw observed ladder clicks and distinguish projected geometry (D-149).

Geometry is drawn first; every name is then placed by :class:`LabelLayout`
so labels sit beside their marks without covering each other, the marks, or
the pane's own header (D-166).
"""

from __future__ import annotations

from typing import TypeAlias

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF

from avialsync.ui.label_layout import LabelLayout

PropPixel: TypeAlias = tuple[float, float, bool] | None
PropDrawing: TypeAlias = tuple[str, tuple[PropPixel, ...], bool]

#: The label of a drawing shown as marked points without a caption. An empty
#: label instead means thin, unmarked mesh lines.
UNNAMED = " "

_COLOR = QColor(245, 195, 80)
_MESH = QColor(245, 195, 80, 170)
_FACE = QColor(245, 195, 80, 55)


def _label_anchor(visible: list[QPointF], points: tuple[PropPixel, ...]) -> tuple[QPointF, bool]:
    """Where a drawing's name belongs, and whether that place is a projection.

    A single mark is named at itself; a rung or edge at its right-hand end,
    so a ladder's names line up down one side; a long outline at its
    right-most point, outside the shape rather than across it.
    """
    known = [point for point in points if point is not None]
    if len(known) == 1 or len(points) <= 2:
        first = next(index for index, point in enumerate(points) if point is not None)
        if len(known) == 2:
            first = max(range(len(points)), key=lambda index: visible[index].x())
        point = points[first]
        assert point is not None
        return visible[first], not point[2]
    right = max(range(len(visible)), key=lambda index: visible[index].x())
    return visible[right], True


def draw_props(
    painter: QPainter,
    drawings: list[PropDrawing],
    scale: float,
    offset_x: float,
    offset_y: float,
    bounds: QRectF | None = None,
    avoid: tuple[QRectF, ...] = (),
) -> None:
    """Draw each declared step without joining across absent observations.

    *bounds* is the visible picture labels must stay inside, and *avoid* the
    pane chrome they must not cover; both default to the whole widget.
    """
    labels = LabelLayout(painter, bounds or QRectF(painter.viewport()), avoid)
    for label, points, closed in drawings:
        surface_face = not label and closed and len(points) == 4
        mesh_line = surface_face or not label or len(points) > 8
        screen: list[QPointF] = [
            QPointF(offset_x + point[0] * scale, offset_y + point[1] * scale)
            if point is not None
            else QPointF()
            for point in points
        ]
        if surface_face and all(point is not None for point in points):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_FACE)
            painter.drawPolygon(QPolygonF(screen))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        for index, point in enumerate(points):
            if point is None:
                continue
            x, y = round(screen[index].x()), round(screen[index].y())
            pen = QPen(_MESH if mesh_line else _COLOR, 1 if mesh_line else 2)
            if not point[2]:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if not mesh_line:
                painter.drawRect(x - 4, y - 4, 8, 8)
                labels.mark(screen[index])
            next_index = index + 1 if index + 1 < len(points) else 0 if closed else -1
            if next_index < 0 or points[next_index] is None:
                continue
            other = points[next_index]
            assert other is not None
            if not (point[2] and other[2]):
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
            end = screen[next_index]
            painter.drawLine(x, y, round(end.x()), round(end.y()))
            labels.line(screen[index], end)
        if label.strip() and any(point is not None for point in points):
            anchor, estimated = _label_anchor(screen, points)
            labels.label(anchor, label, _COLOR, dashed=estimated)
    labels.draw()
