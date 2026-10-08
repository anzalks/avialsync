"""Every kind of target goes through one mapping path, on a master-time fit (D-201).

The reference here is a DAQ whose own clock was already placed -- offset 2 s,
drift 162 ms/h -- so a fit that read its raw times would land 2 s and a drift
away from the truth. Each test then follows the accepted mapping to where a
user meets it: the plotted data, a seek, an export, undo and redo, and a saved
session opened again.
"""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path

import numpy as np
import pytest
from shiboken6 import isValid

from avialsync.core.inspection import SourceInspection
from avialsync.core.pyramid import PyramidBuilder
from avialsync.core.session import SessionState
from avialsync.core.sync import (
    AlignmentMethod,
    SyncFit,
    SyncMatch,
    SyncProposal,
    prepare_display_summary,
)
from avialsync.core.timeline import TimeMap
from avialsync.core.triggers import TriggerKind
from avialsync.core.video_timing import frame_index_at
from avialsync.engine.sync_worker import SyncWorker
from avialsync.loaders.trigger_csv import LEVEL, TriggerCSVSource
from avialsync.loaders.video_standard import VideoStandardLoader
from avialsync.ui.controllers import export_controller
from avialsync.ui.main_window import MainWindow
from avialsync.ui.sync_acceptance import collect_sync_evidence
from avialsync.ui.sync_wizard import SyncWizard

VIDEO = Path("tests/fixtures/sample_session/camera_1.mp4").resolve()
DAQ_MAP = TimeMap(2.0, 162.0)
RATE = 1000.0


def _master_events(count: int = 60) -> np.ndarray:
    return 5.0 + np.cumsum(np.random.default_rng(7).uniform(0.8, 1.2, count))


@pytest.fixture
def window(qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    if isValid(win):
        win.close()


def _open_video(window: MainWindow) -> np.ndarray:
    loader = VideoStandardLoader()
    loader.open(VIDEO, {})
    window._on_video_opened(str(VIDEO), loader, str(VIDEO))
    frames = loader.frame_times()
    assert frames is not None
    return np.asarray(frames, dtype=np.float64)


def _pulse_train(edges: np.ndarray, pad: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    times = np.arange(edges[0] - pad, edges[-1] + pad, 1.0 / RATE)
    values = np.zeros_like(times)
    for edge in edges:
        values[(times >= edge) & (times < edge + 0.02)] = 1.0
    return times, values


def _add_sensor(
    window: MainWindow,
    path: Path,
    times: np.ndarray,
    values: np.ndarray,
    mapping: tuple[float, float] = (0.0, 0.0),
    *,
    build: bool = True,
) -> Path:
    """Complete a sensor import as the import worker would, with *mapping* restored."""
    cache = path.with_suffix(".cache")
    if build:
        cache.mkdir()
        PyramidBuilder(cache, "ttl").build_and_save(times, values)
        path.write_text("stand-in for the recording the cache was imported from\n")
    window._pending_sensor_mappings.setdefault(str(path), mapping)
    window._on_import_finished(
        str(path),
        str(cache),
        ["ttl"],
        (float(times[0]), float(times[-1])),
        SourceInspection(path=str(path)),
    )
    window.plot_pane.wait_for_pending_rows()
    return cache


def _spec(specs: list, **match: object):
    return next(
        spec for spec in specs if all(getattr(spec, key) == value for key, value in match.items())
    )


def _reopen(qtbot, window: MainWindow, tmp_path: Path, monkeypatch) -> MainWindow:
    """Save, close, and restore into a new window whose loads are driven by hand."""
    session = tmp_path / "session.avv"
    window._build_session_state().save(session)
    window.close()
    reopened = MainWindow()
    qtbot.addWidget(reopened)
    monkeypatch.setattr(reopened, "_load_video", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(reopened, "_start_data_import", lambda *_args, **_kwargs: None)
    reopened._restore_session(SessionState.load(session))
    return reopened


def test_a_mapped_reference_places_a_video_exactly_everywhere_it_is_used(
    qtbot, window: MainWindow, tmp_path: Path, monkeypatch
) -> None:
    frames = _open_video(window)
    master = frames + 100.0
    raw = DAQ_MAP.to_source_array(master)
    daq = tmp_path / "daq.csv"
    cache = _add_sensor(
        window, daq, raw, np.ones_like(raw), (DAQ_MAP.offset, DAQ_MAP.drift_ms_per_hour)
    )

    window._open_sync_wizard()
    wizard = window.findChildren(SyncWizard)[0]
    wizard._reference_combo.setCurrentIndex(
        next(i for i, spec in enumerate(wizard._references) if spec.clock_id == str(daq))
    )
    wizard._target_combo.setCurrentIndex(
        next(i for i, spec in enumerate(wizard._targets) if spec.source_id == str(VIDEO))
    )
    wizard._strategy_combo.setCurrentIndex(wizard._strategy_combo.findData("exact_index"))
    wizard._use_all_times_chk.setChecked(True)
    wizard._recorded_strobe.setChecked(True)
    wizard._preview_button.click()
    qtbot.waitUntil(lambda: wizard._thread is None, timeout=10_000)
    assert wizard.proposal is not None and wizard.proposal.fit.method is AlignmentMethod.EXACT
    wizard.accept()

    # Seek: the master time of exposure k shows frame k, for every frame.
    pane = window.video_grid.panes[0]
    np.testing.assert_allclose(pane.time_map.to_source_array(master), frames, atol=1e-9)
    for k in range(len(frames)):
        assert frame_index_at(frames, pane.time_map.to_source(master[k] + 1e-4)) == k
    # Plots: the reference's samples sit at master time, not at its raw clock.
    bounds = window.plot_pane.source_bounds(cache)
    assert bounds == pytest.approx((master[0], master[-1]), abs=1e-6)
    # Export: an A/B loop marked in master time trims the camera on its clock.
    assert export_controller._source_range(window, str(VIDEO), master[2], master[9]) == (
        pytest.approx(frames[2], abs=1e-9),
        pytest.approx(frames[9], abs=1e-9),
    )
    # Provenance keeps the raw DAQ time and its clock beside the master time.
    entry = window._sync_provenance[-1]
    assert entry.reference_clock_id == str(daq)
    assert entry.matches[3]["raw_reference_time"] == pytest.approx(raw[3])
    assert entry.matches[3]["reference_time"] == pytest.approx(master[3])
    assert entry.precision_verified

    reopened = _reopen(qtbot, window, tmp_path, monkeypatch)
    _open_video(reopened)
    pane = reopened.video_grid.panes[0]
    np.testing.assert_allclose(pane.time_map.to_source_array(master), frames, atol=1e-9)
    restored = reopened._sync_provenance[-1]
    assert restored.reference_clock_id == str(daq)
    assert restored.matches[3]["raw_reference_time"] == pytest.approx(raw[3])
    assert restored.precision_verified


def test_a_sensor_target_takes_a_piecewise_mapping_through_undo_and_reopen(
    qtbot, window: MainWindow, tmp_path: Path, monkeypatch
) -> None:
    master = _master_events()
    # A recorder whose clock wanders: no single rate fits it, interpolation does.
    box_edges = master * (1.0 + 60e-6) + 3.0 + 0.004 * np.sin(master / 9.0)
    daq = tmp_path / "daq.csv"
    box = tmp_path / "box.csv"
    _add_sensor(window, daq, *_pulse_train(DAQ_MAP.to_source_array(master)), (2.0, 162.0))
    box_cache = _add_sensor(window, box, *_pulse_train(box_edges))

    references, targets = collect_sync_evidence(window)
    reference = dataclasses.replace(
        _spec(references, clock_id=str(daq)), kind=TriggerKind.SYNC_TRAIN
    )
    found: list[SyncProposal] = []
    worker = SyncWorker(reference, _spec(targets, source_id=str(box)), mode="auto")
    worker.finished.connect(found.append)
    errors: list[str] = []
    worker.error.connect(errors.append)
    worker.run()
    assert errors == []
    proposal = found[0]
    assert proposal.fit.method is AlignmentMethod.PIECEWISE
    window._accept_sync_proposal(str(box), proposal)

    box_map = window.plot_pane._source_time_maps[box_cache]
    np.testing.assert_allclose(box_map.to_master_array(box_edges), master, atol=2e-3)
    entry = window._sync_provenance[-1]
    assert np.shares_memory(box_map._exact_master, entry.exact_master)
    assert "precision" in window.alignment_confidence(str(box))
    # Export: the data slice is written on the master clock.
    reader = next(c.reader for c in window.plot_pane.channels if c.reader.cache_dir == box_cache)
    times, _, _ = next(reader.iter_raw_chunks_with_gaps(t0=master[10], t1=master[12]))
    assert times[0] == pytest.approx(master[10], abs=2e-3)

    window.document.undo(window._mutations)
    assert not box_map.has_exact_mapping
    assert box_map.to_master(box_edges[5]) == pytest.approx(box_edges[5])
    window.document.redo(window._mutations)
    assert box_map.has_exact_mapping
    np.testing.assert_allclose(box_map.to_master_array(box_edges), master, atol=2e-3)

    reopened = _reopen(qtbot, window, tmp_path, monkeypatch)
    _add_sensor(reopened, daq, *_pulse_train(DAQ_MAP.to_source_array(master)), build=False)
    _add_sensor(reopened, box, *_pulse_train(box_edges), build=False)
    box_map = reopened.plot_pane._source_time_maps[box_cache]
    assert box_map.has_exact_mapping, "the piecewise mapping reopened as a straight line"
    np.testing.assert_allclose(box_map.to_master_array(box_edges), master, atol=2e-3)


def _write_trigger_csv(path: Path, edges: np.ndarray) -> dict[str, object]:
    times, values = _pulse_train(edges)
    rows = ["t,sync"] + [f"{t:.6f},{v:.0f}" for t, v in zip(times, values, strict=True)]
    path.write_text("\n".join(rows), encoding="utf-8")
    return {
        "time_column": "t",
        "trains": [
            {"id": "sync", "column": "sync", "kind": str(TriggerKind.SYNC_TRAIN), "mode": LEVEL}
        ],
    }


def test_a_trigger_file_target_is_placed_undone_and_reopened(
    qtbot, window: MainWindow, tmp_path: Path, monkeypatch
) -> None:
    master = _master_events()
    stim_edges = master * (1.0 - 20e-6) + 5.0
    daq = tmp_path / "daq.csv"
    _add_sensor(window, daq, *_pulse_train(DAQ_MAP.to_source_array(master)), (2.0, 162.0))
    stim = tmp_path / "stim.csv"
    window._start_trigger_read(TriggerCSVSource(), stim, _write_trigger_csv(stim, stim_edges))
    qtbot.waitUntil(lambda: str(stim) in window._trigger_trains, timeout=10_000)

    references, targets = collect_sync_evidence(window)
    found: list[SyncProposal] = []
    worker = SyncWorker(
        _spec(references, clock_id=str(daq)), _spec(targets, source_id=str(stim)), mode="affine"
    )
    worker.finished.connect(found.append)
    errors: list[str] = []
    worker.error.connect(errors.append)
    worker.run()
    assert errors == []
    window._accept_sync_proposal(str(stim), found[0])

    placed = window.trigger_mapping(str(stim))
    np.testing.assert_allclose(placed.to_master_array(stim_edges), master, atol=2e-3)
    window.document.undo(window._mutations)
    assert window.trigger_mapping(str(stim)).to_master(stim_edges[3]) == pytest.approx(
        stim_edges[3]
    )
    window.document.redo(window._mutations)
    np.testing.assert_allclose(
        window.trigger_mapping(str(stim)).to_master_array(stim_edges), master, atol=2e-3
    )

    reopened = _reopen(qtbot, window, tmp_path, monkeypatch)
    np.testing.assert_allclose(
        reopened.trigger_mapping(str(stim)).to_master_array(stim_edges), master, atol=2e-3
    )
    # Once placed, the file is reference evidence on the master clock too.
    qtbot.waitUntil(lambda: str(stim) in reopened._trigger_trains, timeout=10_000)
    references, _ = collect_sync_evidence(reopened)
    as_reference = next(spec for spec in references if spec.clock_id == str(stim))
    assert as_reference.accepted_mapping is not None
    assert as_reference.accepted_mapping.to_master(stim_edges[0]) == pytest.approx(
        master[0], abs=2e-3
    )


def test_the_wizard_offers_only_what_acceptance_can_place(
    window: MainWindow, tmp_path: Path
) -> None:
    _open_video(window)
    window._video_frame_times["not-yet-a-pane.mp4"] = [0.0, 0.1, 0.2, 0.3]
    _add_sensor(window, tmp_path / "daq.csv", *_pulse_train(_master_events()))
    # A row whose source the window never registered cannot be placed.
    window.plot_pane.load_channels(
        tmp_path / "daq.cache", ["ttl"], source_id=str(tmp_path / "unregistered.csv")
    )
    window.plot_pane.wait_for_pending_rows()

    references, targets = collect_sync_evidence(window)

    assert not any(getattr(spec, "is_video_time_axis", False) for spec in references)
    placeable = set(window.video_grid.pane_paths()) | set(window._sensor_cache_dirs)
    assert {spec.source_id for spec in targets} <= placeable
    assert str(VIDEO) in {spec.source_id for spec in targets}


def test_accepting_a_hundred_thousand_events_is_a_short_ui_operation(
    window: MainWindow, tmp_path: Path
) -> None:
    box = tmp_path / "box.csv"
    _add_sensor(window, box, *_pulse_train(_master_events()))
    count = 100_000
    times = np.linspace(0.0, 10_000.0, count)
    rejected = tuple((times + 0.05).tolist())
    proposal = SyncProposal(
        "daq",
        str(box),
        SyncFit(1.0, 0.0, 1e-4, 3e-4, count, count, count * 2, count, precision_requirement=0.001),
        tuple(SyncMatch(t, t + 1.0, 1e-4) for t in times.tolist()),
        0.01,
        rejected,
    )
    proposal = dataclasses.replace(proposal, display=prepare_display_summary(proposal))

    started = time.perf_counter()
    window._accept_sync_proposal(str(box), proposal)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.25, f"acceptance held the UI thread {elapsed * 1000:.0f} ms"
    assert len(window.transport.overview._ttl_events) <= 800
    assert len(window._overview_gaps) <= 800
    assert len(window._sync_provenance[-1].matches) <= 500
