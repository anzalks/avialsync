"""Per-camera display levels for every video, 8-bit colour included (D-209)."""

from __future__ import annotations

import shutil
from pathlib import Path

import av
import numpy as np
import pytest
from shiboken6 import isValid

from avialsync.engine.display_pipeline import (
    DisplayLevels,
    SourceFormat,
    _apply_8bit,
    auto_levels_for_frame,
    build_lut,
    to_display_array,
)
from avialsync.ui import video_levels
from avialsync.ui.main_window import MainWindow

_EIGHT_BIT = SourceFormat("gray", 8, 1)


def _rgb_frame() -> av.VideoFrame:
    ramp = np.tile(np.arange(64, dtype=np.uint8)[None, :, None] * 4, (8, 1, 3))
    return av.VideoFrame.from_ndarray(np.ascontiguousarray(ramp), format="rgb24")


def test_eight_bit_colour_is_shown_through_its_levels() -> None:
    frame = _rgb_frame()
    raw, grey = to_display_array(frame)
    assert not grey
    shown, _grey = to_display_array(frame, DisplayLevels(black=0.25, white=0.75))
    assert shown.flags["C_CONTIGUOUS"] and shown.dtype == np.uint8
    np.testing.assert_array_equal(shown, build_lut(_EIGHT_BIT, DisplayLevels(0.25, 0.75))[raw])
    assert shown[0, 10, 0] == 0 and shown[0, 60, 0] == 255  # clipped below black, above white
    unchanged, _grey = to_display_array(frame, DisplayLevels())
    np.testing.assert_array_equal(unchanged, raw)


@pytest.mark.parametrize("shape", [(4, 6, 3), (3, 5, 3)])  # even and odd byte counts
def test_the_paired_lookup_matches_one_byte_at_a_time(shape: tuple[int, ...]) -> None:
    pixels = np.random.default_rng(0).integers(0, 256, shape, dtype=np.uint8)
    lut = build_lut(_EIGHT_BIT, DisplayLevels(0.1, 0.8, 1.7))
    np.testing.assert_array_equal(_apply_8bit(pixels, lut), lut[pixels])


def test_auto_measures_the_frame_itself() -> None:
    """Measured before levels: a picture already clipped cannot be measured back."""
    values = np.linspace(0.3, 0.6, 64 * 64).reshape(64, 64)
    grey = np.round(values * 255).astype(np.uint8)
    frame = av.VideoFrame.from_ndarray(np.dstack([grey, grey, grey]), format="rgb24")
    chosen = auto_levels_for_frame(frame, step=1)
    assert chosen.black == pytest.approx(0.3, abs=0.01)
    assert chosen.white == pytest.approx(0.6, abs=0.01)
    assert chosen.gamma == 1.0


@pytest.fixture
def window(qapp, qtbot, tmp_path: Path) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    video = tmp_path / "camera_1.mp4"
    shutil.copyfile(Path("tests/fixtures/videos/camera_1.mp4"), video)
    win._load_video(video)
    qtbot.waitUntil(lambda: bool(win.video_grid.panes), timeout=10_000)
    pane = win.video_grid.panes[0]
    qtbot.waitUntil(lambda: pane.source_format is not None, timeout=10_000)
    yield win
    if isValid(win):
        win.close()


def test_each_camera_has_a_levels_button_beside_its_zoom(window: MainWindow) -> None:
    pane = window.video_grid.panes[0]
    strip = pane.zoom_controls
    assert pane.levels_button.parent() is strip
    assert pane.levels_button.accessibleName() == "Display levels"
    assert not pane.levels_button.isChecked()
    # The inspector panel now shows for an 8-bit colour camera too.
    assert pane.source_format is not None and not pane.source_format.is_high_bit_depth
    path = window.video_grid.pane_paths()[0]
    window._select_video(path)
    assert not window.levels_panel.isHidden()


def test_a_popover_change_is_undoable_marked_and_saved(window: MainWindow, qtbot) -> None:
    pane = window.video_grid.panes[0]
    path = window.video_grid.pane_paths()[0]
    darker = DisplayLevels(black=0.2, white=0.9)
    pane.levels_requested.emit(darker)

    assert pane.display_levels() == darker
    assert pane.levels_button.isChecked(), "an adjusted camera says so"
    assert window.document.undo_label() == "Change display levels for camera_1.mp4"
    assert window._build_session_state().display_levels == {path: video_levels.to_dict(darker)}

    window.document.undo(window._mutations)
    assert pane.display_levels().is_identity
    assert not pane.levels_button.isChecked()
    assert window._build_session_state().display_levels == {}


def test_a_drag_on_one_slider_is_one_undo_step(window: MainWindow) -> None:
    pane = window.video_grid.panes[0]
    for black in (0.05, 0.1, 0.15, 0.2):
        pane.levels_requested.emit(DisplayLevels(black=black))
    assert window.document.undo_label() == "Change black point for camera_1.mp4"
    window.document.undo(window._mutations)
    assert pane.display_levels().is_identity


def test_saved_levels_come_back_when_the_camera_opens(qapp, qtbot, tmp_path: Path) -> None:
    win = MainWindow()
    qtbot.addWidget(win)
    video = tmp_path / "camera_1.mp4"
    shutil.copyfile(Path("tests/fixtures/videos/camera_1.mp4"), video)
    saved = {str(video): {"black": 0.1, "white": 0.8, "gamma": 1.2}}
    video_levels.restore(win, saved)
    win._load_video(video)
    qtbot.waitUntil(lambda: bool(win.video_grid.panes), timeout=10_000)
    pane = win.video_grid.panes[0]
    qtbot.waitUntil(lambda: not pane.display_levels().is_identity, timeout=10_000)
    assert pane.display_levels() == DisplayLevels(0.1, 0.8, 1.2)
    assert pane.levels_button.isChecked()
    win.close()


def test_the_decoded_picture_changes_with_the_levels(window: MainWindow, qtbot) -> None:
    """Levels used to stop at the pane: the decoder never received them (D-209)."""
    pane = window.video_grid.panes[0]
    # The fixture fades in from black; at 2 s its frame is mid-grey (mean ~60).
    pane.seek(2.0)
    qtbot.waitUntil(
        lambda: (
            pane.surface._buffer is not None
            and float(np.asarray(pane.surface._buffer).mean()) > 40.0
        ),
        timeout=10_000,
    )
    before = float(np.asarray(pane.surface._buffer).mean())
    pane.levels_requested.emit(DisplayLevels(black=0.0, white=0.4))
    qtbot.waitUntil(
        lambda: float(np.asarray(pane.surface._buffer).mean()) > before + 5.0, timeout=10_000
    )


def _open_popover(pane, qtbot):
    from PySide6.QtCore import Qt

    qtbot.mouseClick(pane.levels_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: pane.levels_popover.isVisible(), timeout=5_000)
    return pane.levels_popover_panel


def test_the_popover_opens_usable_and_its_buttons_work(window: MainWindow, qtbot) -> None:
    """Clicked with the mouse, as a user does: the menu-based popover opened 0x0
    and disabled, and tests that set slider values directly could not see it."""
    from PySide6.QtCore import Qt

    pane = window.video_grid.panes[0]
    pane.seek(2.0)
    qtbot.waitUntil(
        lambda: (
            pane.surface._buffer is not None
            and float(np.asarray(pane.surface._buffer).mean()) > 40.0
        ),
        timeout=10_000,
    )
    panel = _open_popover(pane, qtbot)
    assert panel.isEnabled() and panel.isVisible()
    assert pane.levels_popover.width() > 100 and pane.levels_popover.height() > 60

    # Clip the picture first. This fixture's frame carries pure black and pure
    # white (burned-in text), so measured from the recording Auto is full
    # range; measured from the clipped picture, as it used to be, it kept 0.4.
    pane.levels_requested.emit(DisplayLevels(white=0.4))
    assert pane.levels_button.isChecked()
    qtbot.mouseClick(panel._auto, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: pane.display_levels().is_identity, timeout=10_000)
    assert not pane.levels_button.isChecked()

    pane.levels_requested.emit(DisplayLevels(black=0.2))
    qtbot.mouseClick(panel._reset, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: pane.display_levels().is_identity, timeout=5_000)
    window.document.undo(window._mutations)
    assert pane.display_levels() == DisplayLevels(black=0.2), "Full range is undoable"


def test_dragging_a_popover_slider_changes_the_camera(window: MainWindow, qtbot) -> None:
    from PySide6.QtCore import QPoint, Qt

    pane = window.video_grid.panes[0]
    panel = _open_popover(pane, qtbot)
    slider = panel._white
    middle = QPoint(slider.width() // 2, slider.height() // 2)
    qtbot.mouseClick(slider, Qt.MouseButton.LeftButton, pos=middle)
    qtbot.waitUntil(lambda: not pane.display_levels().is_identity, timeout=5_000)
    assert pane.display_levels().white < 1.0
