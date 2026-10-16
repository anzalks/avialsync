"""Overlay labels carry a real dark halo and follow the font-size preference."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from avialsync.ui import theme
from avialsync.ui.marker_overlay import overlay_label_point_size
from avialsync.ui.video_overlay import PaintCanvas


def _dark_pixels(image: QImage) -> int:
    dark = 0
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = QColor(image.pixel(x, y))
            if pixel.lightness() < 60:
                dark += 1
    return dark


def test_a_label_on_its_own_colour_is_outlined(qapp: QApplication) -> None:
    """`drawText` ignores pen width, so the black copy sat under the coloured one."""
    cyan = QColor(0, 220, 220)
    image = QImage(120, 40, QImage.Format.Format_RGB32)
    image.fill(cyan)
    painter = QPainter(image)
    font = QFont()
    font.setPointSizeF(12)
    PaintCanvas._draw_point_label(painter, font, cyan, "mouseA_snout", 10.0, 20.0)
    painter.end()

    assert _dark_pixels(image) > 20


def test_label_size_follows_the_font_scale(qapp: QApplication) -> None:
    base = overlay_label_point_size()
    previous = theme._font_scales.get(id(qapp))
    theme._font_scales[id(qapp)] = 1.5
    try:
        assert overlay_label_point_size() == base * 1.5 / (previous or 1.0)
    finally:
        if previous is None:
            theme._font_scales.pop(id(qapp), None)
        else:
            theme._font_scales[id(qapp)] = previous
