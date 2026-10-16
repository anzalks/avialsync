"""Accepted mappings retain nonlinear corrections, undo and dependency status."""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from avialsync.core.session import SyncProvenance
from avialsync.core.sync import fit_exact_index_mapping
from avialsync.loaders.video_standard import VideoStandardLoader
from avialsync.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot: QtBot) -> Iterator[MainWindow]:
    widget = MainWindow()
    qtbot.addWidget(widget)
    yield widget
    widget.close()


def record(reference: str, target: str) -> SyncProvenance:
    return SyncProvenance(
        reference_id=reference,
        reference_clock_id=reference,
        target_id=target,
        offset=0.0,
        drift_ms_per_hour=0.0,
        rms_residual=0.0,
        max_residual=0.0,
        matched_count=5,
        rejected_count=0,
        tolerance=0.001,
    )


def test_reference_edits_invalidate_every_dependent_clock_and_undo_restores_them(
    window: MainWindow,
) -> None:
    window._sync_provenance = [record("daq", "camera"), record("camera", "other")]
    window._record_mapping_change("daq", 0.1, 0.0)
    window._record_mapping_change("daq", 0.2, 0.0)
    assert all(entry.superseded_by for entry in window._sync_provenance)
    window.document.undo(window._mutations)
    assert all(not entry.superseded_by for entry in window._sync_provenance)


def test_nudging_exact_video_keeps_frame_mapping_and_undo_restores_accepted_state(
    window: MainWindow,
) -> None:
    from pathlib import Path

    path = str(Path("tests/fixtures/sample_session/camera_1.mp4").resolve())
    loader = VideoStandardLoader()
    loader.open(Path(path), {})
    window._on_video_opened(path, loader, path)
    frames = np.asarray(loader.frame_times())
    master = frames + 100.0
    proposal = fit_exact_index_mapping(
        master, frames, reference_id="daq", target_id=path, verified_shared_strobe=True
    )
    window._accept_sync_proposal(path, proposal)
    window.document.clear()
    window._on_video_offset_changed(path, 0.02)
    mapping = window.video_grid.panes[0].time_map
    assert mapping.has_exact_mapping
    assert mapping.to_master(float(frames[20])) == pytest.approx(master[20] - 0.02)
    window.document.undo(window._mutations)
    assert mapping.to_master(float(frames[20])) == pytest.approx(master[20])
    assert window._has_live_alignment(path)


def test_adjusted_exact_mapping_survives_session_save_and_reopen(
    window: MainWindow, qtbot: QtBot, tmp_path: Path
) -> None:
    from pathlib import Path

    from avialsync.core.session import SessionState

    path = str(Path("tests/fixtures/sample_session/camera_1.mp4").resolve())
    loader = VideoStandardLoader()
    loader.open(Path(path), {})
    window._on_video_opened(path, loader, path)
    frames = np.asarray(loader.frame_times())
    master = frames + 100.0
    window._accept_sync_proposal(
        path,
        fit_exact_index_mapping(
            master, frames, reference_id="daq", target_id=path, verified_shared_strobe=True
        ),
    )
    window._on_video_offset_changed(path, 0.02)
    session = tmp_path / "adjusted.avv"
    window._build_session_state().save(session)
    reopened = MainWindow()
    qtbot.addWidget(reopened)
    reopened._restore_session(SessionState.load(session))
    qtbot.waitUntil(lambda: path in reopened.video_grid.pane_paths(), timeout=10000)
    mapping = reopened.video_grid.panes[0].time_map
    assert mapping.has_exact_mapping
    assert mapping.to_master(float(frames[20])) == pytest.approx(master[20] - 0.02)
    reopened.close()


def test_manual_popup_adjustment_retains_exact_mapping(window: MainWindow, qtbot: QtBot) -> None:
    from pathlib import Path

    path = str(Path("tests/fixtures/sample_session/camera_1.mp4").resolve())
    loader = VideoStandardLoader()
    loader.open(Path(path), {})
    window._on_video_opened(path, loader, path)
    frames = np.asarray(loader.frame_times())
    window._accept_sync_proposal(
        path,
        fit_exact_index_mapping(
            frames + 100.0, frames, reference_id="daq", target_id=path, verified_shared_strobe=True
        ),
    )
    window._open_sync_wizard()
    wizard = window._sync_wizard
    assert wizard is not None
    wizard._mode_combo.setCurrentIndex(wizard._mode_combo.findData("manual"))
    wizard._manual_offset.setValue(0.02)
    wizard._use_manual_mapping()
    wizard.accept()
    mapping = window.video_grid.panes[0].time_map
    assert mapping.has_exact_mapping
    assert mapping.to_master(float(frames[20])) == pytest.approx(frames[20] + 99.98)


def test_manual_preview_cannot_be_accepted_after_the_target_was_removed(
    window: MainWindow, qtbot: QtBot
) -> None:
    from pathlib import Path

    path = str(Path("tests/fixtures/sample_session/camera_1.mp4").resolve())
    loader = VideoStandardLoader()
    loader.open(Path(path), {})
    window._on_video_opened(path, loader, path)
    window._open_sync_wizard()
    wizard = window._sync_wizard
    assert wizard is not None
    wizard._mode_combo.setCurrentIndex(wizard._mode_combo.findData("manual"))
    wizard._use_manual_mapping()
    window._on_video_remove_requested(path)
    wizard.accept()
    assert wizard.result() == 0
    assert wizard.proposal is None


def test_replacing_a_corrected_exact_mapping_undoes_to_the_evaluated_curve(
    window: MainWindow,
) -> None:
    path = str(Path("tests/fixtures/sample_session/camera_1.mp4").resolve())
    loader = VideoStandardLoader()
    loader.open(Path(path), {})
    window._on_video_opened(path, loader, path)
    frames = np.asarray(loader.frame_times())
    for placement in (100.0, 101.0):
        window._accept_sync_proposal(
            path,
            fit_exact_index_mapping(
                frames + placement,
                frames,
                reference_id="daq",
                target_id=path,
                verified_shared_strobe=True,
            ),
        )
        if placement == 100.0:
            window._on_video_offset_changed(path, 0.02)
    window.document.undo(window._mutations)
    mapping = window.video_grid.panes[0].time_map
    assert mapping.to_master(float(frames[20])) == pytest.approx(frames[20] + 99.98)
    window.document.redo(window._mutations)
    assert mapping.to_master(float(frames[20])) == pytest.approx(frames[20] + 101.0)
