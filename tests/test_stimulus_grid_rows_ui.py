"""Choosing the stimulus grid's rows: what is offered, what is ticked, how big it comes out."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from shiboken6 import isValid

from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.stimulus_grid_export import GridVideo
from avialsync.loaders.aol_encoder_loader import AOLEncoderLoader
from avialsync.ui import stimulus_grid_sources as sources
from avialsync.ui.main_window import MainWindow
from avialsync.ui.stimulus_grid_dialog import StimulusChannelOption, StimulusGridDialog
from avialsync.ui.stimulus_grid_rows import (
    GridRowsPanel,
    PictureRowOption,
    SensorGroupOption,
    StreamOption,
)


def _pictures(imaging_aspect: float = 16 / 9) -> list[PictureRowOption]:
    camera = GridVideo(Path("cam.mp4"), "cam.mp4")
    side = GridVideo(Path("side.mp4"), "side.mp4")
    return [
        PictureRowOption("cam", "cam.mp4", camera, 4 / 3),
        PictureRowOption("side", "side.mp4", side, 4 / 3, checked=False),
        PictureRowOption("imaging", "tree", camera, imaging_aspect, kind="imaging"),
    ]


def _groups(tmp_path: Path) -> list[SensorGroupOption]:
    def stream(name: str) -> StreamOption:
        return StreamOption(name, ReaderReference(tmp_path, name), (230, 159, 0))

    return [
        SensorGroupOption("sensor:acc", "accelerometer", (stream("x"), stream("y"), stream("z"))),
        SensorGroupOption("sensor:ttl", "trigger box", (stream("ttl"),)),
    ]


def _item(panel: GridRowsPanel, key: str):
    return next(i for i in panel._top_items() if i.data(0, Qt.ItemDataRole.UserRole) == key)


def test_defaults_are_the_cameras_shown_the_viewers_imaging_and_no_bands(qtbot, tmp_path) -> None:
    panel = GridRowsPanel(_pictures(), _groups(tmp_path))
    qtbot.addWidget(panel)
    assert [row.label for row in panel.picture_rows()] == ["cam.mp4", "cam.mp4"]  # cam, imaging
    assert panel.bands() == []
    panel.check_group("sensor:ttl")
    assert [band.label for band in panel.bands()] == ["trigger box"]


def test_bands_carry_only_ticked_streams_and_the_trigger_threshold(qtbot, tmp_path) -> None:
    groups = _groups(tmp_path)
    panel = GridRowsPanel(_pictures(), groups)
    qtbot.addWidget(panel)
    accel = _item(panel, "sensor:acc")
    accel.setCheckState(0, Qt.CheckState.Checked)
    accel.child(1).setCheckState(0, Qt.CheckState.Unchecked)  # drop y
    panel.check_group("sensor:ttl")
    trigger = groups[1].streams[0].reference
    acc, ttl = panel.bands(trigger, 0.5)
    assert [s.label for s in acc.streams] == ["x", "z"] and acc.threshold is None
    assert ttl.threshold == 0.5 and ttl.threshold_stream == 0
    accel.child(0).setCheckState(0, Qt.CheckState.Unchecked)
    accel.child(2).setCheckState(0, Qt.CheckState.Unchecked)
    assert [band.label for band in panel.bands()] == ["trigger box"], "no streams, no band"


def test_rows_reorder_within_their_kind_and_are_remembered(qtbot, tmp_path) -> None:
    panel = GridRowsPanel(_pictures(), _groups(tmp_path))
    qtbot.addWidget(panel)
    panel.tree.setCurrentItem(_item(panel, "imaging"))
    panel.up_button.click()
    panel.up_button.click()
    keys = [i.data(0, Qt.ItemDataRole.UserRole) for i in panel._top_items()]
    assert keys[:3] == ["imaging", "cam", "side"]
    panel.tree.setCurrentItem(_item(panel, "side"))
    panel.down_button.click()  # would put a picture under a band: refused
    assert [i.data(0, Qt.ItemDataRole.UserRole) for i in panel._top_items()] == keys
    panel.check_group("sensor:acc")
    again = GridRowsPanel(_pictures(), _groups(tmp_path), panel.choices())
    qtbot.addWidget(again)
    assert [i.data(0, Qt.ItemDataRole.UserRole) for i in again._top_items()] == keys
    assert [band.label for band in again.bands()] == ["accelerometer"]


def test_the_estimate_warns_before_a_row_is_too_small_to_read(qtbot, tmp_path) -> None:
    panel = GridRowsPanel(_pictures(imaging_aspect=8.0), _groups(tmp_path))
    qtbot.addWidget(panel)
    assert panel.update_estimate(2, high_detail=False)
    assert "Too small" not in panel.estimate.text()
    assert panel.update_estimate(12, high_detail=False)
    assert "Too small to read: tree" in panel.estimate.text()
    for item in panel._top_items():
        item.setCheckState(0, Qt.CheckState.Unchecked)
    assert not panel.update_estimate(2, high_detail=False)


class _Reader:
    def coverage(self) -> tuple[float, float]:
        return 0.0, 5.0

    def query(self, _start: float, _end: float, max_points: int):
        times = np.linspace(0.0, 5.0, min(20, max_points))
        return times, times, times, np.zeros(len(times), dtype=bool)

    def available_sample_at(self, time: float) -> tuple[int, float] | None:
        return (0, time)


def test_the_dialog_shows_the_rows_and_ticks_the_trigger_channels_group(qtbot, tmp_path) -> None:
    groups = _groups(tmp_path)
    channels = [
        StimulusChannelOption("x", groups[0].streams[0].reference, _Reader(), "sensor:acc"),
        StimulusChannelOption("ttl", groups[1].streams[0].reference, _Reader(), "sensor:ttl"),
    ]
    panel = GridRowsPanel(_pictures(), groups)
    dialog = StimulusGridDialog(channels, None, panel)
    qtbot.addWidget(dialog)
    assert dialog.rows_panel is panel and panel.parent() is dialog
    assert [band.label for band in panel.bands()] == ["accelerometer"]
    ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
    assert not ok.isEnabled(), "no events yet"
    dialog.set_events((1.0, 2.0))
    assert ok.isEnabled()
    assert "Each event cell" in panel.estimate.text()
    dialog.channel_combo.setCurrentIndex(1)
    assert [band.label for band in panel.bands()] == ["accelerometer", "trigger box"]


@pytest.fixture
def window(qapp, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    if isValid(win):
        win.close()


def test_only_what_the_session_has_is_offered(window: MainWindow, qtbot, tmp_path) -> None:
    """No imaging loaded: no imaging row. One sensor file: one group of its channels."""
    video = tmp_path / "camera_1.mp4"
    shutil.copyfile(Path("tests/fixtures/videos/camera_1.mp4"), video)
    window._load_video(video)
    log = tmp_path / "encoder_log.txt"
    log.write_text(
        "".join(f"09:35:26:{index:03d} {index} {index * 3.0} 1.0\n" for index in range(50)),
        encoding="utf-8",
    )
    window._start_data_import(log, AOLEncoderLoader, {})
    qtbot.waitUntil(lambda: len(window.plot_pane.channels) == 2, timeout=10_000)
    qtbot.waitUntil(lambda: bool(window.video_grid.panes), timeout=10_000)

    cameras = sources.camera_rows(window)
    assert [(row.label, row.checked) for row in cameras] == [("camera_1.mp4", True)]
    assert sources.imaging_rows(window) == []
    groups, triggers = sources.sensor_groups(window)
    assert len(groups) == 1 and groups[0].label == "encoder_log.txt"
    assert {s.label for s in groups[0].streams} == {"encoder_velocity", "encoder_angle"}
    assert len({s.color for s in groups[0].streams}) == 2, "each stream its own colour"
    assert {t.group for t in triggers} == {groups[0].key}

    panel = GridRowsPanel(cameras, groups)
    qtbot.addWidget(panel)
    sources.remember(window, panel.choices())
    assert sources.remembered(window) is not None
    window.session_runtime.generation += 1  # a reset starts the next session afresh
    assert sources.remembered(window) is None


def test_an_imaging_stack_is_offered_as_the_viewer_shows_it(
    window: MainWindow, qtbot, tmp_path
) -> None:
    from avialsync.loaders.imaging_loader import TIFFImagingLoader
    from tests.test_stimulus_grid_rows import _stack

    path = _stack(tmp_path)
    window.load_imaging(path, TIFFImagingLoader, {"fps": 10.0})
    qtbot.waitUntil(lambda: str(path) in window.imaging_pane.source_paths(), timeout=10_000)
    rows = sources.imaging_rows(window)
    assert len(rows) == 1 and rows[0].checked and rows[0].kind == "imaging"
    assert rows[0].row.crop is None
    assert rows[0].aspect_ratio == pytest.approx(40 / 20)

    view = window.imaging_pane.frame_label
    qtbot.waitUntil(lambda: view._image is not None, timeout=10_000)
    view.zoom_by(2.0)
    zoomed = sources.imaging_rows(window)[0].row
    assert zoomed.crop is not None and zoomed.crop[2] < 1.0 and zoomed.crop[3] <= 1.0
