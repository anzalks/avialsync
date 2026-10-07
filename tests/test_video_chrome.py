"""Video pane chrome: the label contract, compact OSD, aspect-sized panes (D-174, DS-5)."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

from avialsync.core.source import VideoMetadata
from avialsync.ui import video_pane
from avialsync.ui.video_grid import VideoGrid
from avialsync.ui.video_timing import format_video_osd

pytest.importorskip("av")


def _pane(qtbot, width: int, detail: str) -> video_pane.VideoPane:
    pane = video_pane.VideoPane()
    qtbot.addWidget(pane)
    pane.resize(width, 300)
    pane.surface.set_frame(np.zeros((360, 640, 3), dtype=np.uint8))
    pane.set_label("camera_with_a_rather_long_name_from_the_rig.mp4")
    pane.set_osd_detail(detail)
    pane.show()
    qtbot.waitUntil(lambda: pane.surface.width() > 0)
    return pane


@pytest.mark.parametrize("detail", ["compact", "full"])
def test_label_area_avoids_the_declared_chrome(qtbot, detail: str) -> None:
    """A label anchored under the header lands outside every chrome rectangle."""
    pane = _pane(qtbot, 420, detail)
    try:
        canvas = pane.paint_canvas
        _area, chrome = canvas._label_area(1.0, 0.0, 0.0)
        declared = pane.chrome_rects()
        assert len(chrome) == len(declared) >= 2
        name_rect = QRectF(pane.lbl_name.geometry())
        osd_rect = QRectF(pane.lbl_osd.geometry())
        assert any(rect.contains(name_rect.center()) for rect in chrome)
        assert any(rect.contains(osd_rect.center()) for rect in chrome)
        # The zoom tools are reserved even while hidden, so labels never jump.
        pane.zoom_controls.hide()
        assert len(pane.chrome_rects()) == len(declared)
    finally:
        pane.close()


def test_osd_and_name_fit_three_cameras_in_1280_px(qtbot, qapp: QApplication) -> None:
    pane = _pane(qtbot, 1280 // 3, "compact")
    try:
        qapp.processEvents()
        assert pane.lbl_osd.geometry().right() <= pane.width()
        assert pane.lbl_name.geometry().right() < pane.lbl_osd.geometry().left()
        assert pane.lbl_osd.width() >= pane.lbl_osd.sizeHint().width(), "the timecode never clips"
        assert (
            "…"
            in pane.lbl_name.fontMetrics().elidedText(
                pane.lbl_name.fullText(), pane.lbl_name._mode, pane.lbl_name.width()
            )
            or pane.lbl_name.width() >= pane.lbl_name.sizeHint().width()
        )
    finally:
        pane.close()


def test_compact_osd_is_one_line_of_time_and_frame() -> None:
    text = format_video_osd(61.25, 30.0, VideoMetadata(), (37, 120), "compact")
    assert text == "00:01:01.250 · f 37 / 119"
    assert "\n" in format_video_osd(61.25, 30.0, VideoMetadata(), (37, 120), "full")


@pytest.mark.parametrize("count", [1, 2])
def test_one_or_two_cameras_are_sized_to_their_picture(qtbot, qapp, count: int) -> None:
    """F-11: no black field around a lone camera; the pane takes the picture's aspect."""
    grid = VideoGrid()
    qtbot.addWidget(grid)
    grid.resize(1200, 500)
    grid.show()
    panes = [grid.add_pane(f"/nonexistent/camera_{index}.mp4") for index in range(count)]
    for pane in panes:
        pane.surface.set_frame(np.zeros((360, 640, 3), dtype=np.uint8))
    qapp.processEvents()
    try:
        for pane in panes:
            assert pane.width() / pane.height() == pytest.approx(640 / 360, rel=0.02), (
                pane.geometry(),
                grid.layout().contentsMargins(),
                grid.size(),
            )
            assert pane.width() <= grid.width() and pane.height() <= grid.height()
        grid.add_pane("/nonexistent/camera_x.mp4")
        grid.add_pane("/nonexistent/camera_y.mp4")
        qapp.processEvents()
        assert panes[0].maximumWidth() == 16777215, "three or more cameras fill their cells"
    finally:
        grid.shutdown()


@pytest.mark.parametrize(
    ("pix_fmt", "bits"),
    [
        ("gray12le", 12),
        ("yuv420p10le", 10),
        ("yuv420p", 8),
        ("yuvj422p", 8),
        ("gray", 8),
        ("rgb48le", 16),
        ("gray16be", 16),
        ("", None),
    ],
)
def test_bit_depth_is_read_from_the_pixel_format(pix_fmt: str, bits: int | None) -> None:
    from avialsync.ui.video_timing import bit_depth_of

    assert bit_depth_of(pix_fmt) == bits


def test_overlay_names_resolution_and_bit_depth() -> None:
    """D-183: what the picture is, beside when it is, at both detail levels."""
    metadata = VideoMetadata(width=1440, height=1080, pixel_format="gray12le", codec="h264")
    compact = format_video_osd(1.0, 30.0, metadata, (30, 120), "compact")
    assert compact == "00:00:01.000 · f 30 / 119\n1440×1080 · 12-bit"
    full = format_video_osd(1.0, 30.0, metadata, (30, 120), "full")
    assert "Picture: 1440×1080 · 12-bit · gray12le" in full.splitlines()
    # A decoded frame's depth outranks the file's pixel format.
    assert "1440×1080 · 10-bit" in format_video_osd(1.0, 30.0, metadata, (30, 120), "compact", 10)


@pytest.mark.parametrize("detail", ["compact", "full"])
def test_overlay_text_wraps_inside_a_narrow_pane(qtbot, qapp: QApplication, detail: str) -> None:
    """Nothing in the overlay runs off the pane: lines wrap, the name elides."""
    pane = _pane(qtbot, 240, detail)
    try:
        pane.set_video_metadata(
            VideoMetadata(width=1440, height=1080, pixel_format="gray12le", codec="h264")
        )
        pane.set_osd_detail(detail)
        qapp.processEvents()
        osd = pane.lbl_osd
        assert osd.geometry().right() <= pane.width()
        assert osd.geometry().left() >= 0
        assert osd.height() >= osd.heightForWidth(osd.width()), "every wrapped line is shown"
        assert "1440×1080" in osd.text() and "12-bit" in osd.text()
    finally:
        pane.close()
