"""User workflows spanning popup controls, recorded evidence and exported reports."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from avialsync.core.imaging_display import ImagingView
from avialsync.core.source import ImagingMetadata
from avialsync.core.sync import AlignmentMethod, fit_exact_index_mapping
from avialsync.core.timeline import TimeMap
from avialsync.core.triggers import TriggerKind
from avialsync.engine.sync_report import SyncReportWorker
from avialsync.engine.sync_worker import EventEvidenceSpec, SignalEvidenceSpec, SyncWorker
from avialsync.loaders.imaging_loader import TIFFImagingLoader
from avialsync.loaders.trigger_csv import TriggerCSVSource
from avialsync.ui.main_window import MainWindow
from avialsync.ui.sync_acceptance import collect_sync_evidence
from avialsync.ui.sync_wizard import SyncWizard
from avialsync.ui.trigger_dialog import TriggerEvidenceDialog


def test_timestamp_only_trigger_file_has_a_usable_suggestion_with_units(tmp_path: Path) -> None:
    path = tmp_path / "events.csv"
    path.write_text("time_ms\n1000\n2500\n4000\n")
    config = TriggerCSVSource.suggest_trains(path)[0]
    assert config["trains"][0]["mode"] == "timestamps"
    assert config["time_unit"] == "ms"
    source = TriggerCSVSource()
    source.open(path, config)
    times, _ = source.read_train("events")
    assert times == pytest.approx([1.0, 2.5, 4.0])


def test_trigger_dialog_preserves_and_exposes_threshold_and_debounce(
    qtbot: QtBot, tmp_path: Path
) -> None:
    suggestion = {
        "time_column": "t",
        "trains": [
            {
                "id": "ttl",
                "column": "ttl",
                "threshold": 2.5,
                "min_interval": 0.003,
                "kind": "sync_train",
            }
        ],
    }
    dialog = TriggerEvidenceDialog(tmp_path / "ttl.csv", suggestion, [])
    qtbot.addWidget(dialog)
    assert dialog.config()["trains"][0]["threshold"] == 2.5
    assert dialog.config()["trains"][0]["min_interval"] == 0.003
    dialog._table.cellWidget(0, 5).setCurrentIndex(1)
    assert dialog.config()["trains"][0]["mode"] == "timestamps"
    assert not dialog._table.cellWidget(0, 6).isEnabled()


def test_forced_exact_mode_extracts_pulses_rather_than_all_signal_samples(tmp_path: Path) -> None:
    from avialsync.core.pyramid import PyramidBuilder

    times = np.arange(0.0, 1.0, 0.001)
    values = np.zeros_like(times)
    rises = np.array([0.1, 0.24, 0.43, 0.67, 0.86])
    for rise in rises:
        values[(times >= rise) & (times < rise + 0.01)] = 1.0
    PyramidBuilder(tmp_path, "ttl").build_and_save(times, values)
    reference = SignalEvidenceSpec(
        "daq", tmp_path, "ttl", kind=TriggerKind.FRAME_STROBE, strobe_for="camera"
    )
    target = EventEvidenceSpec("camera", rises + 0.005, clock_id="camera", is_video_time_axis=True)
    worker = SyncWorker(reference, target, mode="exact_index")
    results = []
    worker.finished.connect(results.append)
    worker.run()
    assert results and results[0].fit.method == AlignmentMethod.EXACT
    assert results[0].fit.measurement_resolution == pytest.approx(0.001)


def test_coarse_sampled_ttl_cannot_claim_finer_precision(tmp_path: Path) -> None:
    from avialsync.core.pyramid import PyramidBuilder

    times = np.arange(0.0, 1.0, 0.01)
    values = np.zeros_like(times)
    rises = np.array([0.1, 0.24, 0.43, 0.67, 0.86])
    for rise in rises:
        values[(times >= rise) & (times < rise + 0.02)] = 1.0
    PyramidBuilder(tmp_path, "ttl").build_and_save(times, values)
    reference = SignalEvidenceSpec(
        "daq", tmp_path, "ttl", kind=TriggerKind.FRAME_STROBE, strobe_for="camera"
    )
    target = EventEvidenceSpec("camera", rises + 0.01, clock_id="camera", is_video_time_axis=True)
    worker = SyncWorker(reference, target, mode="auto", precision_requirement=0.001)
    results = []
    worker.finished.connect(results.append)
    worker.run()
    assert results and results[0].applicable
    assert results[0].fit.measurement_resolution >= 0.0099
    assert not results[0].fit.precision_verified


def test_landmark_pairs_preview_without_accepting_or_changing_the_recording(qtbot: QtBot) -> None:
    wizard = SyncWizard(
        [],
        [EventEvidenceSpec("camera_b", np.arange(100.0))],
        visual_references=[
            EventEvidenceSpec("camera_a", np.arange(100.0), is_video_time_axis=True)
        ],
    )
    qtbot.addWidget(wizard)
    wizard._mode_combo.setCurrentIndex(wizard._mode_combo.findData("landmarks"))
    wizard._landmarks.reference_time.setValue(10.0)
    wizard._landmarks.target_time.setValue(12.0)
    wizard._landmarks.add_pair()
    wizard._preview()
    qtbot.waitUntil(lambda: wizard._thread is None, timeout=5000)
    assert wizard.proposal is not None
    assert wizard.proposal.fit.offset == pytest.approx(2.0)
    assert wizard.proposal.applicable and not wizard.proposal.fit.precision_verified
    assert wizard.result() == 0


def test_proposal_report_round_trips_evidence_and_mapping(tmp_path: Path) -> None:
    times = np.array([0.0, 1.0, 2.5, 4.0])
    proposal = fit_exact_index_mapping(
        times + 100.0, times, reference_id="daq", target_id="camera", verified_shared_strobe=True
    )
    path = tmp_path / "alignment.json"
    worker = SyncReportWorker(path, proposal)
    finished = []
    worker.finished.connect(finished.append)
    worker.run()
    assert finished
    report = json.loads(path.read_text())
    assert not report["accepted"]
    alignment = report["alignments"][0]
    assert alignment["method"] == "exact"
    assert len(alignment["matches"]) == 4
    assert alignment["mapping"]["master_seconds"] == [100.0, 101.0, 102.5, 104.0]


def test_accepted_report_preserves_corrected_mapping_and_labels_its_sample(tmp_path: Path) -> None:
    from avialsync.ui.sync_acceptance import _provenance

    times = np.arange(1000, dtype=np.float64) / 30.0
    proposal = fit_exact_index_mapping(
        times + 100.0, times, reference_id="daq", target_id="camera", verified_shared_strobe=True
    )
    record = _provenance(proposal, "camera", proposal.fit.prepared_mapping)
    assert len(record.matches) == 500
    assert record.matches[0]["reference_time"] == pytest.approx(100.0)
    assert record.matches[-1]["reference_time"] == pytest.approx(times[-1] + 100.0)
    mapping = proposal.fit.to_time_map()
    mapping.adjust_mapping(mapping.offset + 0.02, 54.0)
    output = tmp_path / "accepted.json"
    worker = SyncReportWorker(output, records=(record,), mappings={"camera": mapping})
    errors: list[str] = []
    worker.error.connect(errors.append)
    worker.run()
    assert not errors
    report = json.loads(output.read_text())
    assert report["accepted"]
    alignment = report["alignments"][0]
    assert alignment["saved_match_count"] == 500
    assert not alignment["matches_complete"]
    restored = TimeMap.from_record(alignment["mapping"])
    assert restored.to_master(10.0) == pytest.approx(mapping.to_master(10.0))


def test_imaging_target_accepts_exact_mapping_undo_and_redo(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    path = str(tmp_path / "stack.tif")
    import tifffile

    tifffile.imwrite(path, np.zeros((4, 8, 8), dtype=np.uint16), photometric="minisblack")
    times = np.array([0.0, 0.1, 0.2, 0.3])
    info = ImagingMetadata(
        width=8,
        height=8,
        frame_count=4,
        frame_times=times,
        dtype="uint16",
        timing_source="fixture timestamps",
    )
    window.imaging_pane.add_source(path, TIFFImagingLoader, {}, info, 0.0, 0.0, ImagingView())
    window.sidebar.add_imaging(path, info, 0.0, 0.0)
    _, targets = collect_sync_evidence(window)
    report_action = next(
        action
        for action in window._align_menu.actions()
        if action.text() == "Export Alignment Report…"
    )
    assert not report_action.isEnabled()
    assert any(
        spec.source_id == path and spec.is_imaging_time_axis
        for spec in targets
        if isinstance(spec, EventEvidenceSpec)
    )
    proposal = fit_exact_index_mapping(
        times + 100.0, times, reference_id="daq", target_id=path, verified_shared_strobe=True
    )
    window._accept_sync_proposal(path, proposal)
    assert report_action.isEnabled()
    mapping = window.imaging_pane.source_config(path)[2]
    assert mapping.to_master(0.2) == pytest.approx(100.2)
    window.document.undo(window._mutations)
    assert not report_action.isEnabled()
    assert mapping.to_master(0.2) == pytest.approx(0.2)
    window.document.redo(window._mutations)
    assert report_action.isEnabled()
    assert mapping.to_master(0.2) == pytest.approx(100.2)
    window.close()
