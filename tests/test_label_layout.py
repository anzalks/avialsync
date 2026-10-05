"""Overlay labels sit beside their marks without covering each other or pane chrome."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from avialsync.ui import label_layout
from avialsync.ui.label_layout import LabelLayout


def test_crowded_labels_stay_apart_inside_the_picture_and_off_the_header(
    qapp: object, monkeypatch
) -> None:
    placed: list[QRectF] = []
    original = LabelLayout._place

    def recording(self: LabelLayout, label: object, done: list[QRectF]) -> tuple[QRectF, bool]:
        rect, far = original(self, label, done)  # type: ignore[arg-type]
        placed.append(QRectF(rect))
        return rect, far

    monkeypatch.setattr(label_layout.LabelLayout, "_place", recording)
    image = QImage(400, 300, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    picture = QRectF(0, 40, 400, 220)
    header = QRectF(250, 0, 150, 80)
    layout = LabelLayout(painter, picture, (header,))
    # Eight marks in a tight cluster near the header, as corners and clicks are.
    for index in range(8):
        anchor = QPointF(300 + (index % 4) * 9, 90 + (index // 4) * 9)
        layout.mark(anchor)
        layout.label(anchor, f"corner {index + 1}", QColor(245, 195, 80))
    layout.draw()
    painter.end()

    assert len(placed) == 8
    for index, rect in enumerate(placed):
        assert picture.contains(rect)
        assert not rect.intersects(header)
        assert not any(rect.intersects(other) for other in placed[index + 1 :])
