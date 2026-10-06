"""Imaging viewer integration with the master clock and session document (D-190)."""

from pathlib import Path

import numpy as np
import pytest
import tifffile
from PySide6.QtCore import Qt
from shiboken6 import isValid

from avialsync.core.session import SessionState
from avialsync.loaders.imaging_loader import TIFFImagingLoader
from avialsync.ui.main_window import MainWindow

_TIMEOUT = 10_000


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    if isValid(win):
        win.close()


def _two_channel_stack(path: Path) -> np.ndarray:
    """Channel 0 brightens frame by frame; channel 1 is a fixed left/right split."""
    frames = []
    for index in range(6):
        green = np.full((24, 32), 100 + 100 * index, np.uint16)
        magenta = np.zeros((24, 32), np.uint16)
        magenta[:, 16:] = 1000
        frames.append(np.stack([green, magenta]))
    stack = np.stack(frames)
    tifffile.imwrite(path, stack, ome=True, metadata={"axes": "TCYX", "TimeIncrement": 0.1})
    return stack


def _open(window: MainWindow, qtbot, path: Path, config: dict | None = None) -> None:
    window.load_imaging(path, TIFFImagingLoader, config or {})
    qtbot.waitUntil(lambda: str(path) in window.imaging_pane.source_paths(), timeout=_TIMEOUT)
    qtbot.waitUntil(lambda: window.imaging_pane._worker is not None, timeout=_TIMEOUT)


def _picture(window: MainWindow, qtbot) -> np.ndarray:
    """Wait for the pane to show a fresh picture and return it as RGB."""
    pane = window.imaging_pane
    pane._image = None
    pane._rerender()
    qtbot.waitUntil(lambda: pane._image is not None, timeout=_TIMEOUT)
    image = pane._image.convertToFormat(pane._image.Format.Format_RGB888)
    data = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes())
    return data.reshape(image.height(), image.bytesPerLine())[:, : image.width() * 3].reshape(
        image.height(), image.width(), 3
    )


def test_imaging_follows_master_time_below_the_3d_view(window, qtbot, tmp_path):
    path = tmp_path / "calcium.tif"
    stack = np.stack([np.full((24, 32), index * 100, np.uint16) for index in range(4)])
    tifffile.imwrite(path, stack, photometric="minisblack")
    _open(window, qtbot, path, {"fps": 10.0})
    pane = window.imaging_pane
    assert pane.isVisible() and window.imaging_splitter.isVisible()
    assert window.imaging_splitter.widget(0) is window.tracking_3d_pane
    assert window.imaging_splitter.widget(1) is pane
    assert window.sidebar.btn_open_imaging.isVisible()
    window.player.seek(0.25)
    qtbot.waitUntil(lambda: pane.status_label.text().startswith("Frame 3/4"), timeout=_TIMEOUT)
    pane._on_frame_failed(str(path), pane._last_index, "damaged page")
    assert pane._image is None
    assert pane.frame_label.text() == "Imaging frame unavailable"
    # The session bounds clamp a seek to the stack, so ask the pane directly
    # for a time another, longer source could put the playhead at.
    pane.set_cursor(5.0)
    assert pane.frame_label.text() == "No imaging data at this time"


def test_channels_overlay_and_each_can_be_hidden(window, qtbot, tmp_path):
    path = tmp_path / "two_channel.ome.tif"
    _two_channel_stack(path)
    _open(window, qtbot, path)
    controls = window.imaging_pane.controls
    assert [c.color for c in controls.view().channels] == ["green", "magenta"]
    rgb = _picture(window, qtbot)
    assert rgb[:, 20:, 0].min() > 200, "magenta half carries red"
    assert rgb[:, :10, 0].max() == 0, "the green-only half carries none"
    controls._rows[1].shown.setChecked(False)
    rgb = _picture(window, qtbot)
    assert rgb[..., 0].max() == 0 and rgb[..., 2].max() == 0, "only green remains"
    controls._rows[0].shown.setChecked(False)
    qtbot.waitUntil(lambda: "No channel is shown" in window.imaging_pane.frame_label.text())


def test_brightness_contrast_and_auto_levels_change_only_the_picture(window, qtbot, tmp_path):
    path = tmp_path / "levels.tif"
    stack = np.stack([np.tile(np.arange(32, dtype=np.uint16) * 100, (24, 1)) for _ in range(3)])
    tifffile.imwrite(path, stack, photometric="minisblack")
    _open(window, qtbot, path, {"fps": 5.0})
    pane = window.imaging_pane
    before = _picture(window, qtbot)[0, :, 0].astype(int)
    assert pane.view_for(str(path)).channels[0].measured, "the reference window is kept"
    row = pane.controls._rows[0]
    row.brightness.setValue(50)
    brighter = _picture(window, qtbot)[0, :, 0].astype(int)
    assert brighter.mean() > before.mean()
    row.contrast.setValue(60)
    steeper = _picture(window, qtbot)[0, :, 0].astype(int)
    assert np.count_nonzero((steeper > 0) & (steeper < 255)) < np.count_nonzero(
        (before > 0) & (before < 255)
    )
    pane.auto_button.click()
    assert row.brightness.value() == 0 and row.contrast.value() == 0
    np.testing.assert_allclose(_picture(window, qtbot)[0, :, 0], before, atol=1)
    status = pane.status_label.text()
    assert status.startswith("Frame 1/3")


def test_the_moving_average_is_centred_and_undoable(window, qtbot, tmp_path):
    path = tmp_path / "ramp.ome.tif"
    _two_channel_stack(path)
    _open(window, qtbot, path)
    pane = window.imaging_pane
    pane.controls._rows[1].shown.setChecked(False)
    window.player.seek(0.25)  # frame 2, green value 300
    raw = _picture(window, qtbot)[0, 0, 1]
    pane.controls.average.setValue(1)  # one frame either side
    qtbot.waitUntil(lambda: "mean of 3" in pane.status_label.text(), timeout=_TIMEOUT)
    # Frames 1-3 average to frame 2's own value: centred, so no shift in time.
    assert _picture(window, qtbot)[0, 0, 1] == raw
    assert window.document.undo(window._mutations)
    assert pane.controls.average.value() == 0
    assert pane.controls.average.text() == "Off"
    assert pane.view_for(str(path)).average == 1
    assert window.document.undo(window._mutations)
    assert pane.view_for(str(path)).channels[1].visible


def test_session_keeps_choices_mapping_and_display(qtbot, window, tmp_path):
    path = tmp_path / "calcium.tif"
    stack = np.stack([np.full((24, 32), index * 100, np.uint16) for index in range(4)])
    tifffile.imwrite(path, stack, photometric="minisblack")
    _open(window, qtbot, path, {"fps": 10.0})
    pane = window.imaging_pane
    pane.controls._rows[0].color.setCurrentIndex(pane.controls._rows[0].color.findData("green"))
    pane.controls.average.setValue(2)
    pane.offset_spin.setValue(0.05)
    assert pane.source_config(str(path))[2].offset == 0.05
    assert window.document.undo(window._mutations)
    assert pane.source_config(str(path))[2].offset == 0.0
    pane.offset_spin.setValue(0.05)

    restored = SessionState.from_dict(window._build_session_state().to_dict())
    entry = restored.imaging[0]
    assert entry.path == str(path)
    assert entry.import_config["fps"] == 10.0
    assert entry.offset == 0.05
    assert entry.display["average"] == 5
    assert entry.display["channels"][0]["color"] == "green"

    window._on_imaging_remove_requested(str(path))
    assert not pane.source_paths()
    assert window.document.undo(window._mutations)
    qtbot.waitUntil(lambda: str(path) in pane.source_paths(), timeout=_TIMEOUT)
    assert pane.view_for(str(path)).average == 5, "undoing a removal brings its display back"
    window.close()

    reopened = MainWindow()
    qtbot.addWidget(reopened)
    reopened.show()
    reopened._restore_session(restored)
    qtbot.waitUntil(lambda: str(path) in reopened.imaging_pane.source_paths(), timeout=_TIMEOUT)
    assert reopened.imaging_pane.metadata_for(str(path)).frame_count == 4
    assert reopened.imaging_pane.view_for(str(path)).channels[0].color == "green"
    assert reopened.imaging_pane.controls.average.value() == 2
    assert reopened.imaging_pane.offset_spin.value() == 0.05
    reopened.close()


def test_every_typed_average_is_a_window_it_shows(window, qtbot, tmp_path):
    """Typing 2 used to snap back to 1: an even frame count has no centre."""
    path = tmp_path / "ramp.ome.tif"
    _two_channel_stack(path)
    _open(window, qtbot, path)
    box = window.imaging_pane.controls.average
    box.lineEdit().selectAll()
    qtbot.keyClicks(box.lineEdit(), "12")
    qtbot.keyClick(box.lineEdit(), Qt.Key.Key_Return)
    assert box.value() == 12
    assert window.imaging_pane.view_for(str(path)).average == 25
    box.lineEdit().selectAll()
    qtbot.keyClicks(box.lineEdit(), "2")
    qtbot.keyClick(box.lineEdit(), Qt.Key.Key_Return)
    assert box.value() == 2
    assert box.text() == "±2 frames"
    assert window.imaging_pane.view_for(str(path)).average == 5


def test_the_imaging_picture_zooms_like_the_video(window, qtbot, tmp_path):
    path = tmp_path / "ramp.ome.tif"
    _two_channel_stack(path)
    _open(window, qtbot, path)
    _picture(window, qtbot)
    view = window.imaging_pane.frame_label
    strip = view.zoom_controls
    assert strip.isVisible()
    assert [b.toolTip() for b in (strip.zoom_in_button, strip.zoom_out_button)] == [
        "Zoom in",
        "Zoom out",
    ]
    strip.zoom_in_button.click()
    assert view.zoom() == pytest.approx(1.25)
    strip.zoom_out_button.click()
    strip.zoom_out_button.click()
    assert view.zoom() == 1.0, "never smaller than the fitted picture"
    strip.zoom_in_button.click()
    strip.reset_zoom_button.click()
    assert view.zoom() == 1.0
    assert window.tracking_3d_pane.canvas.zoom_controls is not strip, "each pane zooms alone"


def test_a_stack_opens_with_a_default_reading_that_can_be_changed_and_undone(
    window, qtbot, tmp_path
):
    """No axis question: the data shows at once, and the pane corrects the reading."""
    import h5py

    from avialsync.loaders.imaging_loader import HDF5ImagingLoader

    path = tmp_path / "stack.h5"
    with h5py.File(path, "w") as handle:
        handle.create_dataset("images", data=np.zeros((6, 2, 8, 10), np.uint16))
    window.load_imaging(path, HDF5ImagingLoader, {"fps": 10.0})
    pane = window.imaging_pane
    qtbot.waitUntil(lambda: str(path) in pane.source_paths(), timeout=_TIMEOUT)
    assert pane.metadata_for(str(path)).axes == "TCYX"
    assert pane.layout_row.isVisible()
    assert pane.axes_choice.currentText() == "Time 6 · Channels 2"

    pane.axes_choice.activated.emit(pane.axes_choice.findData("CTYX"))
    qtbot.waitUntil(
        lambda: str(path) in pane.source_paths() and pane.metadata_for(str(path)).axes == "CTYX",
        timeout=_TIMEOUT,
    )
    assert pane.metadata_for(str(path)).frame_count == 2
    assert window.document.undo(window._mutations)
    qtbot.waitUntil(
        lambda: str(path) in pane.source_paths() and pane.metadata_for(str(path)).axes == "TCYX",
        timeout=_TIMEOUT,
    )
    assert pane.source_config(str(path))[1]["fps"] == 10.0, "other choices are kept"
