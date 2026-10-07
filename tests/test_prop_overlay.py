"""Prop overlays draw only declared geometry and label inferred projections."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFont, QPen

from avialsync.ui.prop_overlay import draw_props


@pytest.fixture(autouse=True)
def _application(qapp: object) -> None:
    """Label placement measures text, which needs a running application."""


class RecordingPainter:
    """Capture geometry and line style without depending on platform rasterisation."""

    def __init__(self, viewport: QRect | None = None) -> None:
        self._viewport = viewport or QRect(0, 0, 1280, 1024)
        self.pen = QPen()
        self.lines: list[tuple[int, int, int, int, Qt.PenStyle]] = []
        self.rectangles: list[tuple[int, int, Qt.PenStyle]] = []
        self.labels: list[str] = []

    def setPen(self, pen: QPen) -> None:
        self.pen = QPen(pen)

    def setBrush(self, _brush: object) -> None:
        pass

    def font(self) -> QFont:
        return QFont()

    def viewport(self) -> QRect:
        return self._viewport

    def drawPolygon(self, _polygon: object) -> None:
        pass

    def drawRect(self, x: int, y: int, _width: int, _height: int) -> None:
        self.rectangles.append((x + 4, y + 4, self.pen.style()))

    def drawText(self, *args: object) -> None:
        self.labels.append(str(args[-1]))

    def drawLine(self, *args: object) -> None:
        if len(args) == 4:  # geometry; a label's leader line is drawn with points
            x, y, x2, y2 = args
            self.lines.append((x, y, x2, y2, self.pen.style()))

    def drawRoundedRect(self, *_args: object) -> None:
        pass

    def setFont(self, _font: QFont) -> None:
        pass

    def save(self) -> None:
        pass

    def restore(self) -> None:
        pass


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


def test_a_column_full_of_labels_finishes_painting() -> None:
    """Colliding labels in a small pane overlap rather than stalling the paint."""
    painter = RecordingPainter(QRect(0, 0, 120, 60))
    drawings = [(f"Step {index}", ((50.0, 30.0, True),), False) for index in range(40)]
    draw_props(painter, drawings, 1.0, 0.0, 0.0)
    assert len(painter.labels) == 40
