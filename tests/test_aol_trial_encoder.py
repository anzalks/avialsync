"""The wheel speed a microscope controller logs into each trial's params.mat."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.registry import LoaderRegistry
from avialsync.loaders.aol_microscope_session import AOLMicroscopeTrialSource
from avialsync.loaders.aol_trial_encoder import SPEED_CHANNEL, AOLTrialEncoderSource
from avialsync.ui.main_window import MainWindow
from tests.test_aol_microscope_trial import _cell, _trial


def _wheel(folder: Path, times: np.ndarray, rpm: np.ndarray) -> None:
    """Add ``behaviour/encoder`` as the controller writes it: one-element cells."""
    with h5py.File(folder / "params.mat", "a") as handle:
        _cell(handle, "behaviour/encoder/wheel_speed_time", times[None, :])
        _cell(handle, "behaviour/encoder/wheel_speed", rpm[None, :])
        _cell(handle, "behaviour/encoder/wheel_angle", np.cumsum(rpm)[None, :])


def _read(item) -> tuple[np.ndarray, np.ndarray]:
    source = AOLTrialEncoderSource()
    source.open(item.path, dict(item.config))
    assert [channel.unit for channel in source.channels()] == ["rpm"]
    chunks = list(source.read_chunks(SPEED_CHANNEL))
    return np.concatenate([c[0] for c in chunks]), np.concatenate([c[1] for c in chunks])


def test_a_trial_offers_only_its_wheel_speed_on_its_start(tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    # A repeated stamp is one sample, not two.
    _wheel(folder, np.array([0.001, 0.002, 0.002, 0.003]), np.array([1.0, 2.0, 9.0, 3.0]))
    layout = AOLMicroscopeTrialSource().scan(folder, None)
    wheel = [item for item in layout.items if item.loader is AOLTrialEncoderSource]
    assert len(wheel) == 1
    assert wheel[0].source_epoch == layout.session_epoch == 1_700_000_000.0
    assert wheel[0].label.endswith("wheel speed")
    times, rpm = _read(wheel[0])
    np.testing.assert_allclose(times, [0.001, 0.002, 0.003])
    np.testing.assert_allclose(rpm, [1.0, 2.0, 3.0])


def test_trials_play_their_wheel_speed_back_to_back(tmp_path: Path) -> None:
    experiment = tmp_path / "experiment_1"
    experiment.mkdir()
    first = _trial(experiment / "12-00-00")
    second = _trial(experiment / "12-10-00", start_ms=1_700_000_600_000)
    # The first trial's last sample runs past its 29 ms slot and is dropped.
    _wheel(first, np.array([0.0, 0.01, 0.02, 0.035]), np.array([1.0, 1.0, 1.0, 7.0]))
    _wheel(second, np.array([0.0, 0.01]), np.array([2.0, 2.0]))
    layout = AOLMicroscopeTrialSource().scan(experiment, None)
    wheel = next(item for item in layout.items if item.loader is AOLTrialEncoderSource)
    times, rpm = _read(wheel)
    start = wheel.config["trial_starts"][1]
    np.testing.assert_allclose(times, [0.0, 0.01, 0.02, start, start + 0.01])
    np.testing.assert_allclose(rpm, [1.0, 1.0, 1.0, 2.0, 2.0])


def test_a_trial_without_a_wheel_offers_none(tmp_path: Path) -> None:
    layout = AOLMicroscopeTrialSource().scan(_trial(tmp_path / "12-00-00"), None)
    assert all(item.loader is not AOLTrialEncoderSource for item in layout.items)


def test_the_wheel_speed_loader_is_registered_for_restore_but_claims_no_drop(
    tmp_path: Path,
) -> None:
    registry = LoaderRegistry(plugin_dirs=[])
    assert AOLTrialEncoderSource in registry.loaders()
    folder = _trial(tmp_path / "12-00-00")
    assert registry.find_best_loader(folder / "params.mat") is not AOLTrialEncoderSource


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitUntil(lambda: not win._job_manager.jobs(), timeout=5000)
    yield win
    if isValid(win):
        win.close()


def test_the_wheel_speed_is_plotted_in_rpm(window: MainWindow, qtbot, tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    _wheel(folder, np.linspace(0.0, 0.02, 21), np.full(21, 4.0))
    layout = AOLMicroscopeTrialSource().scan(folder, None)
    wheel = next(item for item in layout.items if item.loader is AOLTrialEncoderSource)
    window._route_import_candidate(wheel.path, wheel.loader, dict(wheel.config))
    qtbot.waitUntil(
        lambda: SPEED_CHANNEL in {row.reader.channel_id for row in window.plot_pane.channels},
        timeout=10_000,
    )
    rows = {row.reader.channel_id: row for row in window.plot_pane.channels}
    assert set(rows) == {SPEED_CHANNEL}
    assert rows[SPEED_CHANNEL].visible


def test_an_open_encoder_log_is_the_speed_shown(tmp_path: Path) -> None:
    """Trials dropped onto a camera session that logs the wheel add no second speed."""
    from avialsync.core.source import SessionItem
    from avialsync.loaders.video_standard import VideoStandardLoader
    from tests.test_aol_time_matching import _experiment, _local

    experiment, videos = _experiment(tmp_path, cameras_under=tmp_path / "usb" / "camera_pc")
    trial = experiment / "12-00-06"
    _wheel(trial, np.array([0.0, 0.5]), np.array([1.0, 1.0]))
    camera = videos / "12-00-03" / "FaceCam.avi"
    loaded = [SessionItem(camera, VideoStandardLoader, source_epoch=_local("12-00-06", 0.03))]

    def offered() -> list[type]:
        claimed = AOLMicroscopeTrialSource().scan_together([trial], loaded, None)
        assert claimed is not None
        return [item.loader for item in claimed[0].items]

    assert AOLTrialEncoderSource in offered()
    (camera.parent / "encoder_log.txt").write_text("09:35:26:000 0 0.0 1.0\n", encoding="utf-8")
    assert AOLTrialEncoderSource not in offered()
