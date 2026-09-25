"""Bars drawn as solid cylinders in the orthographic 3D view (D-128)."""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QColor, QImage, QPainter

from avialsync.ui import cylinder_paint
from avialsync.ui.cylinder_paint import draw_cylinders
from avialsync.ui.tracking_3d_pane import Tracking3DCanvas
from tests.wheel_fixture import TRUTH

_GREY = QColor(200, 200, 200)


def _render(rise: float, width: float = 30.0) -> QImage:
    image = QImage(200, 200, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    draw_cylinders(
        painter,
        np.array([[40.0, 100.0]]),
        np.array([[160.0, 100.0]]),
        np.array([0.0]),
        np.array([rise]),
        np.array([1.0]),
        width,
        _GREY,
    )
    painter.end()
    return image


def test_a_bar_across_the_view_is_a_band_one_diameter_wide(qapp) -> None:
    image = _render(rise=0.0)
    assert image.pixelColor(100, 100).alpha() > 0
    assert image.pixelColor(100, 112).alpha() > 0, "inside the 15 px half-width"
    assert image.pixelColor(100, 122).alpha() == 0, "outside it"
    assert image.pixelColor(168, 100).alpha() == 0, "no end face seen edge-on"


def test_it_is_shaded_round_not_flat(qapp) -> None:
    image = _render(rise=0.0)
    middle = image.pixelColor(100, 100).lightness()
    edge = image.pixelColor(100, 112).lightness()
    assert middle > edge + 20, (middle, edge)


def test_a_bar_turned_toward_the_viewer_shows_its_round_ends(qapp) -> None:
    """The end circles foreshorten into ellipses as the bar turns (orthographic)."""
    across = _render(rise=0.0)
    turned = _render(rise=0.8)
    assert across.pixelColor(170, 100).alpha() == 0
    assert turned.pixelColor(170, 100).alpha() > 0, "the near face bulges past the end"
    assert turned.pixelColor(30, 100).alpha() > 0, "the far face rounds the other end"


def test_bars_are_painted_back_to_front(qapp, monkeypatch) -> None:
    painted: list[float] = []
    monkeypatch.setattr(
        cylinder_paint, "_draw_one", lambda _p, start, *_rest: painted.append(float(start[0]))
    )
    image = QImage(10, 10, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    draw_cylinders(
        painter,
        np.array([[1.0, 0.0], [2.0, 0.0], [3.0, 0.0]]),
        np.array([[1.0, 5.0], [2.0, 5.0], [3.0, 5.0]]),
        np.array([5.0, -5.0, 0.0]),
        np.array([5.0, -5.0, 0.0]),
        np.ones(3),
        4.0,
        _GREY,
    )
    painter.end()
    assert painted == [2.0, 3.0, 1.0], "farthest (smallest depth) first"


def _coverage(qtbot, wheels: list) -> int:
    canvas = Tracking3DCanvas()
    qtbot.addWidget(canvas)
    canvas._center = np.zeros(3)
    canvas._radius = 160.0
    canvas.set_wheel_source(lambda _t: wheels)
    image = QImage(300, 300, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    canvas.render_scene(painter, 300, 300)
    painter.end()
    background = image.pixelColor(2, 2).rgb()
    pixels = np.frombuffer(image.constBits(), dtype=np.uint32).reshape(300, 300)
    return int(np.count_nonzero(pixels != np.uint32(background)))


def test_the_3d_view_draws_solid_bars_once_a_diameter_is_set(qtbot) -> None:
    grid = _coverage(qtbot, [])
    lines = _coverage(qtbot, [(TRUTH.bar_ends(), False, None)]) - grid
    solid = _coverage(qtbot, [(TRUTH.bar_ends(), False, 6.0)]) - grid
    assert lines > 0
    assert solid > 3 * lines, (lines, solid)
