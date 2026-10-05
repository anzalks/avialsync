"""Scrub evidence changes only when its source data changes (D-170)."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

from avialsync.ui.scrub_bar import ScrubBar
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
