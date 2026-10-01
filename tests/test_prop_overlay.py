"""Prop overlays draw only declared geometry and label inferred projections."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPen

from avialsync.ui.prop_overlay import draw_props


class RecordingPainter:
    """Capture geometry and line style without depending on platform rasterisation."""

    def __init__(self) -> None:
        self.pen = QPen()
        self.lines: list[tuple[int, int, int, int, Qt.PenStyle]] = []
        self.rectangles: list[tuple[int, int, Qt.PenStyle]] = []
        self.labels: list[str] = []

    def setPen(self, pen: QPen) -> None:
        self.pen = QPen(pen)

    def setBrush(self, _brush: Qt.BrushStyle) -> None:
        pass

    def drawRect(self, x: int, y: int, _width: int, _height: int) -> None:
        self.rectangles.append((x + 4, y + 4, self.pen.style()))

    def drawText(self, _x: int, _y: int, label: str) -> None:
        self.labels.append(label)

    def drawLine(self, x: int, y: int, x2: int, y2: int) -> None:
        self.lines.append((x, y, x2, y2, self.pen.style()))


def test_missing_endpoint_breaks_the_drawn_ladder_segment() -> None:
    painter = RecordingPainter()
    draw_props(
        painter,
        [("uneven", ((10.0, 20.0, True), None, (30.0, 40.0, True)), False)],
        2.0,
        3.0,
        5.0,
    )
    assert painter.rectangles == [
        (23, 45, Qt.PenStyle.SolidLine),
        (63, 85, Qt.PenStyle.SolidLine),
    ]
    assert painter.lines == []
    assert painter.labels == ["uneven"]


def test_projected_point_and_edges_are_dashed_while_clicked_edges_are_solid() -> None:
    painter = RecordingPainter()
    draw_props(
        painter,
        [
            (
                "rung",
                ((1.0, 2.0, True), (3.0, 4.0, True), (5.0, 6.0, False)),
                False,
            )
        ],
        1.0,
        0.0,
        0.0,
    )
    assert painter.rectangles == [
        (1, 2, Qt.PenStyle.SolidLine),
        (3, 4, Qt.PenStyle.SolidLine),
        (5, 6, Qt.PenStyle.DashLine),
    ]
    assert painter.lines == [
        (1, 2, 3, 4, Qt.PenStyle.SolidLine),
        (3, 4, 5, 6, Qt.PenStyle.DashLine),
    ]


def test_closed_outline_joins_only_its_declared_last_and_first_points() -> None:
    painter = RecordingPainter()
    draw_props(
        painter,
        [("outline", ((0.0, 0.0, True), (2.0, 0.0, True), (1.0, 1.0, True)), True)],
        1.0,
        0.0,
        0.0,
    )
    assert [(x, y, x2, y2) for x, y, x2, y2, _style in painter.lines] == [
        (0, 0, 2, 0),
        (2, 0, 1, 1),
        (1, 1, 0, 0),
    ]
