"""AOL trials through the real window: import review, imaging pane, pairing, wheel."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.loaders.aol_cell_roi_grid import AOLCellRoiGridSource
from avialsync.loaders.aol_encoder_loader import AOLEncoderLoader
from avialsync.loaders.aol_microscope_session import AOLMicroscopeTrialSource
from avialsync.loaders.aol_ribbon_scan import AOLRibbonScanSource
from avialsync.loaders.aol_roi_trace import AOLRoiTraceLoader
from avialsync.ui.batch_import_dialog import BatchImportDialog
from avialsync.ui.controllers import wheel_controller
from avialsync.ui.controllers.aol_microscope_controller import accept_trial_pair
from avialsync.ui.main_window import MainWindow
from tests.test_aol_microscope_trial import _analysis, _trial

_TIMEOUT = 10_000


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitUntil(lambda: not win._job_manager.jobs(), timeout=5000)
    yield win
    if isValid(win):
        win.close()


def _candidates(folder: Path) -> list[tuple[Path, type, dict]]:
    layout = AOLMicroscopeTrialSource().scan(folder, None)
    return [(item.path, item.loader, item.config) for item in layout.items]


def test_import_review_offers_every_trial_item_instead_of_skipping_it(
    window: MainWindow, tmp_path: Path
) -> None:
    """The imaging rows defaulted to Skip while their loaders were unregistered."""
    folder = _trial(tmp_path / "12-00-00")
    _analysis(folder)
    candidates = _candidates(folder)
    dialog = BatchImportDialog(candidates, window)
    chosen = {path: loader for path, loader, _config in dialog.get_selections()}
    assert chosen == {path: loader for path, loader, _config in candidates}
    assert set(chosen.values()) == {AOLRibbonScanSource, AOLCellRoiGridSource, AOLRoiTraceLoader}
    dialog.deleteLater()


def test_trial_imaging_reaches_the_imaging_pane(window: MainWindow, qtbot, tmp_path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    activity = _analysis(folder)
    for path, loader, config in _candidates(folder):
        window._route_import_candidate(path, loader, dict(config))
    paths = window.imaging_pane.source_paths
    qtbot.waitUntil(lambda: {str(folder), str(activity)} <= set(paths()), timeout=_TIMEOUT)


def test_accepting_a_pairing_places_the_trial_and_undo_restores_it(
    window: MainWindow, qtbot, tmp_path
) -> None:
    folder = _trial(tmp_path / "12-00-00")
    path, loader, config = _candidates(folder)[0]
    window._route_import_candidate(path, loader, dict(config))
    source_id = str(folder)
    qtbot.waitUntil(lambda: source_id in window.imaging_pane.source_paths(), timeout=_TIMEOUT)
    before = window._mutations.source_mapping(source_id)

    accept_trial_pair(window, {"status": "matched", "folder": source_id})
    offset, drift = window._mutations.source_mapping(source_id)
    assert offset == pytest.approx(-window.base_offset(source_id))
    assert drift == 0.0
    assert window.document.undo_label() is not None

    window.document.undo(window._mutations)
    assert window._mutations.source_mapping(source_id) == before


def test_encoder_angle_is_hidden_but_still_drives_the_wheel(
    window: MainWindow, qtbot, tmp_path
) -> None:
    log = tmp_path / "encoder_log.txt"
    log.write_text(
        "".join(f"09:35:26:{index:03d} {index} {index * 3.0} 1.0\n" for index in range(50)),
        encoding="utf-8",
    )
    window._start_data_import(log, AOLEncoderLoader, {})
    qtbot.waitUntil(
        lambda: (
            {row.reader.channel_id for row in window.plot_pane.channels}
            >= {"encoder_velocity", "encoder_angle"}
        ),
        timeout=_TIMEOUT,
    )
    rows = {row.reader.channel_id: row for row in window.plot_pane.channels}
    assert rows["encoder_velocity"].visible
    assert not rows["encoder_angle"].visible
    offered = {channel for _source, channel, _label in wheel_controller._channels(window)}
    assert "encoder_angle" in offered


def test_pairing_a_trial_moves_its_joined_experiment_by_its_joined_start(
    window: MainWindow, qtbot, tmp_path
) -> None:
    experiment = tmp_path / "experiment_1"
    experiment.mkdir()
    _trial(experiment / "12-00-00")
    second = _trial(experiment / "12-10-00", start_ms=1_700_000_600_000)
    layout = AOLMicroscopeTrialSource().scan(experiment, None)
    item = layout.items[0]
    assert item.config["trial_starts"] == pytest.approx([0.0, 0.029])
    window._route_import_candidate(item.path, item.loader, dict(item.config))
    source_id = str(experiment)
    qtbot.waitUntil(lambda: source_id in window.imaging_pane.source_paths(), timeout=_TIMEOUT)

    accept_trial_pair(window, {"status": "matched", "folder": str(second)})
    residual, _drift = window._mutations.source_mapping(source_id)
    # The second trial's zero is on camera frame zero (master 0 with no camera
    # loaded); back to back, the experiment's own zero is 29 ms before it.
    assert window.effective_offset(source_id, residual) == pytest.approx(0.029)


def test_frame_step_walks_imaging_frames_when_no_video_is_loaded(
    window: MainWindow, qtbot, tmp_path
) -> None:
    folder = _trial(tmp_path / "12-00-00")
    path, loader, config = _candidates(folder)[0]
    window._route_import_candidate(path, loader, dict(config))
    qtbot.waitUntil(lambda: str(folder) in window.imaging_pane.source_paths(), timeout=_TIMEOUT)
    times = window.imaging_pane.metadata_for(str(folder)).frame_times
    window.player.seek(float(times[0]) - window.base_offset(str(folder)), exact=True)
    start = window.clock.state.t
    window.transport.frame_step_requested.emit(1)
    assert window.clock.state.t > start
    window.transport.frame_step_requested.emit(-1)
    assert window.clock.state.t == pytest.approx(start, abs=1e-6)
