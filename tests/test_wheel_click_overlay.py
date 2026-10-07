"""Wheel placement clicks remain visible as labelled marks over video."""

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QWidget

from avialsync.ui.video_overlay import PaintCanvas
from avialsync.ui.wheel_overlay import WheelDrawing


def test_a_new_end_click_is_painted_on_its_camera(qtbot) -> None:
    parent = QWidget()
    parent.video_size = (100, 100)
    qtbot.addWidget(parent)
    canvas = PaintCanvas(parent)
    canvas.resize(100, 100)
    canvas.set_wheel_source(lambda _t: WheelDrawing(clicks=(("1a", 50.0, 50.0),)))
    image = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)

    canvas.render(image)

    assert image.pixelColor(55, 50).alpha() > 0
    assert image.pixelColor(5, 5).alpha() == 0


def test_clicked_end_stays_visible_above_tracking(qtbot, monkeypatch) -> None:
    parent = QWidget()
    parent.video_size = (100, 100)
    qtbot.addWidget(parent)
    canvas = PaintCanvas(parent)
    canvas.resize(100, 100)
    canvas.set_wheel_source(lambda _t: WheelDrawing(clicks=(("1a", 50.0, 50.0),)))
    canvas.set_readers([object()])
    monkeypatch.setattr(
        canvas,
        "_draw_loose_readers",
        lambda painter, *_args: painter.fillRect(0, 0, 100, 100, QColor(0, 0, 0)),
    )
    image = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)

    canvas.render(image)

    assert image.pixelColor(55, 50).red() > image.pixelColor(5, 5).red()


def test_projected_end_has_a_distinct_visible_mark(qtbot) -> None:
    parent = QWidget()
    parent.video_size = (100, 100)
    qtbot.addWidget(parent)
    canvas = PaintCanvas(parent)
    canvas.resize(100, 100)
    canvas.set_wheel_source(
        lambda _t: WheelDrawing(projections=(("1a", 50.0, 50.0),), prompt="Click 1A here")
    )
    image = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)

    canvas.render(image)

    assert image.pixelColor(50, 45).alpha() > 0
    assert image.pixelColor(5, 80).alpha() == 0
