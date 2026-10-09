"""AOL trials through the real window: import review, imaging pane, pairing, wheel."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.loaders.aol_encoder_loader import AOLEncoderLoader
from avialsync.loaders.aol_microscope_session import AOLMicroscopeTrialSource
from avialsync.loaders.aol_ribbon_scan import AOLRibbonScanSource
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
    assert set(chosen.values()) == {AOLRibbonScanSource}
    dialog.deleteLater()


def test_trial_imaging_reaches_the_imaging_pane(window: MainWindow, qtbot, tmp_path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    for path, loader, config in _candidates(folder):
        window._route_import_candidate(path, loader, dict(config))
    paths = window.imaging_pane.source_paths
    qtbot.waitUntil(lambda: str(folder) in paths(), timeout=_TIMEOUT)


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


def test_import_review_draws_each_name_once(window: MainWindow, tmp_path: Path) -> None:
    """The name label sits over its table item; painting both smeared the text."""
    folder = _trial(tmp_path / "12-00-00")
    dialog = BatchImportDialog(_candidates(folder), window)
    item = dialog._table.item(0, 0)
    assert item.text()  # still there for readers and assistive technology
    assert item.foreground().color().alpha() == 0
    assert dialog._table.cellWidget(0, 0).text() == item.text()
    dialog.deleteLater()


def test_import_review_shows_only_what_a_trial_needs(window: MainWindow, tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    _analysis(folder)
    candidates = _candidates(folder)
    labels = {str(path): f"label {index}" for index, (path, _l, _c) in enumerate(candidates)}
    dialog = BatchImportDialog(candidates, window, labels=labels)
    for row, combo in enumerate(dialog._combos):
        loader = dialog._candidates[row][1]
        offered = {combo.itemData(index) for index in range(combo.count())}
        # Skip, or what the session found -- not every installed format.
        assert offered == {None, loader}
    # No row has a pose role or a Vicon calibration, so those columns are gone.
    assert dialog._table.isColumnHidden(2) and dialog._table.isColumnHidden(3)
    dialog.deleteLater()


def test_controller_stacks_open_with_their_session_names_and_no_axes_row(
    window: MainWindow, qtbot, tmp_path
) -> None:
    folder = _trial(tmp_path / "12-00-00")
    path, loader, config = _candidates(folder)[0]
    window.session_runtime.item_labels[str(path)] = "12-00-00 — reconstructed tree"
    window._route_import_candidate(path, loader, dict(config))
    qtbot.waitUntil(lambda: str(folder) in window.imaging_pane.source_paths(), timeout=_TIMEOUT)
    pane = window.imaging_pane
    assert pane.source_choice.currentText() == "12-00-00 — reconstructed tree"
    assert pane.layout_row.isHidden()


def test_picking_a_stack_outside_the_playhead_brings_it_into_view(
    window: MainWindow, qtbot, tmp_path
) -> None:
    first = _trial(tmp_path / "12-00-00")
    second = _trial(tmp_path / "12-10-00", start_ms=1_700_000_600_000)
    from avialsync.ui.controllers import drop_controller

    for folder in (first, second):
        layout = AOLMicroscopeTrialSource().scan(folder, None)
        drop_controller.apply_session_layout(window, layout)
        item = layout.items[0]
        window._route_import_candidate(item.path, item.loader, dict(item.config))
    pane = window.imaging_pane
    qtbot.waitUntil(lambda: str(second) in pane.source_paths(), timeout=_TIMEOUT)
    window.player.seek(300.0, exact=True)  # between the two trials: neither has data
    pane.source_choice.setCurrentIndex(pane.source_choice.findData(str(second)))
    pane.source_choice.activated.emit(pane.source_choice.currentIndex())
    _loader, _config, mapping = pane.source_config(str(second))
    first_frame = float(pane.metadata_for(str(second)).frame_times[0])
    assert mapping.to_source(window.clock.state.t) == pytest.approx(first_frame, abs=1e-6)


def test_trials_are_drawn_on_the_timeline_and_the_plots(window: MainWindow, tmp_path) -> None:
    experiment = tmp_path / "experiment_1"
    experiment.mkdir()
    _trial(experiment / "12-00-00")
    _trial(experiment / "12-10-00", start_ms=1_700_000_600_000)
    layout = AOLMicroscopeTrialSource().scan(experiment, None)
    from avialsync.ui.controllers import drop_controller

    drop_controller.apply_session_layout(window, layout)
    overview = window.transport.overview
    assert "Trials" in overview.lane_labels()
    assert [name for _s, _e, name in overview._segments] == ["12-00-00", "12-10-00"]
    # Converted from Unix seconds, so about 1e-7 s of float rounding is expected.
    assert overview._segments[1][0] == pytest.approx(0.029, abs=1e-6)
    bounds = window.plot_pane._interactions._segment_bounds
    assert bounds == pytest.approx((0.0, 0.029, 0.051), abs=1e-6)


def test_the_viewer_states_the_frame_rate_the_file_gives(
    window: MainWindow, qtbot, tmp_path
) -> None:
    from avialsync.ui.imaging_card import frame_rate

    folder = _trial(tmp_path / "12-00-00")
    path, loader, config = _candidates(folder)[0]
    window._route_import_candidate(path, loader, dict(config))
    pane = window.imaging_pane
    qtbot.waitUntil(lambda: str(folder) in pane.source_paths(), timeout=_TIMEOUT)
    info = pane.metadata_for(str(folder))
    _loader, _config, mapping = pane.source_config(str(folder))
    pane.set_cursor(mapping.to_master(float(info.frame_times[0])) + 1e-6)
    qtbot.waitUntil(lambda: "fps" in pane.status_label.text(), timeout=_TIMEOUT)
    # Frames 12 ms apart in the fixture: 83.33 fps, from the file's own times.
    assert frame_rate(info) == pytest.approx(1 / 0.012)
    assert pane.status_label.text().endswith("· 83.33 fps")


def test_a_stack_with_a_pause_still_reports_its_acquisition_rate() -> None:
    import numpy as np

    from avialsync.core.source import ImagingMetadata
    from avialsync.ui.imaging_card import frame_rate

    # 18 Hz frames, then a minute of nothing, then 18 Hz again.
    times = np.concatenate([np.arange(10) / 18.0, 60.0 + np.arange(10) / 18.0])
    info = ImagingMetadata(20, 4, 4, "uint16", times, "fixture")
    assert frame_rate(info) == pytest.approx(18.0)
