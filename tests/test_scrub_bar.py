"""Scrub evidence changes only when its source data changes (D-170)."""

from __future__ import annotations

from PySide6.QtGui import QColor, QImage, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSlider

from avialsync.ui.scrub_bar import ScrubBar, _merge_spans
from avialsync.ui.theme import THEME_DARK, _apply, system_accent
from avialsync.ui.transport import Transport


def test_cursor_ticks_reuse_the_scrub_track(qtbot) -> None:
    """Moving the master cursor cannot rasterize coverage or markers again."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(960, 220)
    transport.show()
    qtbot.waitExposed(transport)
    transport.set_bounds(0.0, 10.0)
    transport.set_source_coverage("camera", 1.0, 9.0, "video")
    transport.set_annotation_markers([(3.0, None, "#e7a35b")])
    slider = transport.slider
    assert isinstance(slider, ScrubBar)
    slider.grab()
    built = slider.track_build_count
    assert built > 0, (slider.isVisible(), slider.geometry(), transport.geometry())

    for time in (2.0, 3.0, 4.0):
        transport.set_time(time)
        slider.grab()
    assert slider.track_build_count == built

    transport.set_source_coverage("camera", 1.0, 8.0, "video")
    slider.grab()
    assert slider.track_build_count == built + 1


def test_loop_and_theme_changes_invalidate_the_cached_track(qtbot) -> None:
    """A/B and palette changes repaint the evidence, then ticks reuse it."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(960, 220)
    transport.show()
    qtbot.waitExposed(transport)
    transport.set_bounds(0.0, 10.0)
    slider = transport.slider
    slider.grab()
    built = slider.track_build_count

    transport.set_ab_region(2.0, 5.0)
    slider.grab()
    assert slider.track_build_count == built + 1

    palette = QPalette(slider.palette())
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#e4a050"))
    slider.setPalette(palette)
    slider.grab()
    assert slider.track_build_count == built + 2


def test_scrub_bar_unions_overlapping_coverage_and_eliminates_double_groove(qtbot) -> None:
    """Overlapping sources never alpha-stack, and no native groove bleeds above the track."""
    assert _merge_spans(((0.0, 5.0), (2.0, 8.0), (0.0, 5.0), (9.0, 10.0))) == (
        (0.0, 8.0),
        (9.0, 10.0),
    )

    app = QApplication.instance()
    saved_palette = QPalette(app.palette())
    saved_dark = app.property("avialsync_theme_dark")
    try:
        _apply(app, THEME_DARK, persist=False)
        transport = Transport()
        qtbot.addWidget(transport)
        transport.resize(960, 120)
        transport.show()
        qtbot.waitExposed(transport)
        transport.set_bounds(0.0, 10.0)
        transport.set_time(5.0)
        slider = transport.slider
        assert isinstance(slider, ScrubBar)

        transport.set_source_coverage("cam_0", 0.0, 10.0, "video")
        single_img = slider.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)

        for idx in range(1, 12):
            transport.set_source_coverage(f"src_{idx}", 0.0, 10.0, "data")
        multi_img = slider.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)

        track = slider.track_rect()
        option = QStyleOptionSlider()
        slider.initStyleOption(option)
        handle = slider.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider
        )
        dpr = multi_img.devicePixelRatio()

        def px(image: QImage, x_logical: int, y_logical: int) -> QColor:
            return image.pixelColor(
                min(image.width() - 1, max(0, round(x_logical * dpr))),
                min(image.height() - 1, max(0, round(y_logical * dpr))),
            )

        right_sample_x = (handle.right() + track.right()) // 2
        left_sample_x = (track.left() + handle.left()) // 2
        center_y = track.center().y()

        # 12 overlapping spans must render identically to 1 span (no alpha stacking).
        assert px(single_img, right_sample_x, center_y) == px(multi_img, right_sample_x, center_y)

        # Above and below the 4 px track (away from the thumb), pixels match the background
        # with zero stray blue native-groove bleed.
        bg = px(multi_img, left_sample_x, 1)
        above = px(multi_img, left_sample_x, max(1, track.top() - 3))
        below = px(multi_img, left_sample_x, min(slider.height() - 2, track.bottom() + 3))
        assert abs(above.blue() - bg.blue()) <= 4
        assert abs(below.blue() - bg.blue()) <= 4

        # Played left side carries system_accent on the exact same center_y as right-side coverage.
        played = px(multi_img, left_sample_x, center_y)
        unplayed = px(multi_img, right_sample_x, center_y)
        accent = system_accent(slider.palette())
        assert played != unplayed
        assert abs(played.red() - accent.red()) <= 3
        assert abs(played.green() - accent.green()) <= 3
        assert abs(played.blue() - accent.blue()) <= 3
    finally:
        app.setPalette(saved_palette)
        app.setProperty("avialsync_theme_dark", saved_dark)
