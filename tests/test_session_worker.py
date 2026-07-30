"""Session persistence and annotation export run off the UI thread.

Architecture rule 3.  A session carrying accepted per-frame mappings can hold a
million timestamps, and annotation exports scale with marker count; neither may
be written on the thread that paints video.  These tests pin the worker contract
and prove the event loop keeps beating while a slow write runs.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QThread, QTimer

from avialview.core.session import SessionState, SyncProvenance, VideoEntry
from avialview.engine.session_worker import (
    ANNOTATION_HEADER,
    AnnotationExportWorker,
    AnnotationRow,
    SessionLoadWorker,
    SessionSaveWorker,
)
from avialview.ui.annotations import AnnotationStore, VideoFrame
from avialview.ui.main_window import MainWindow


@pytest.fixture
def state() -> SessionState:
    return SessionState(
        videos=[VideoEntry(path="/tmp/cam.mp4", offset=1.5)],
        t_start=0.0,
        t_end=60.0,
    )


def _run_in_thread(worker, qtbot) -> None:
    """Drive one worker on a real QThread and wait for it to finish."""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    with qtbot.waitSignal(thread.finished, timeout=10_000):
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.start()
    thread.wait()


# ── Save ──────────────────────────────────────────────────────────────


def test_save_worker_writes_the_session(qtbot, tmp_path: Path, state: SessionState) -> None:
    path = tmp_path / "s.avv"
    worker = SessionSaveWorker(state, path)
    done: list[str] = []
    worker.finished.connect(done.append)

    _run_in_thread(worker, qtbot)

    assert done == [str(path)]
    assert json.loads(path.read_text())["version"] == 6


def test_save_worker_reports_an_unwritable_path(qtbot, tmp_path: Path, state) -> None:
    worker = SessionSaveWorker(state, tmp_path / "missing-dir" / "s.avv")
    errors: list[str] = []
    worker.error.connect(errors.append)

    _run_in_thread(worker, qtbot)

    assert errors


def test_save_worker_runs_off_the_calling_thread(qtbot, tmp_path: Path, state) -> None:
    """The serialisation itself must execute on the worker thread, not the caller."""
    observed: list[int] = []
    original_save = SessionState.save

    def _record(self, path: Path) -> None:
        observed.append(threading.get_ident())
        original_save(self, path)

    state.save = _record.__get__(state)  # type: ignore[method-assign]  # per-instance probe
    worker = SessionSaveWorker(state, tmp_path / "s.avv")

    _run_in_thread(worker, qtbot)

    assert observed, "SessionState.save was never called."
    assert observed[0] != threading.get_ident()


# ── Load ──────────────────────────────────────────────────────────────


def test_load_worker_parses_the_session(qtbot, tmp_path: Path, state: SessionState) -> None:
    path = tmp_path / "s.avv"
    state.save(path)
    worker = SessionLoadWorker(path)
    results: list[tuple[str, object]] = []
    worker.finished.connect(lambda p, s: results.append((p, s)))

    _run_in_thread(worker, qtbot)

    assert len(results) == 1
    loaded = results[0][1]
    assert isinstance(loaded, SessionState)
    assert loaded.videos[0].offset == pytest.approx(1.5)


def test_load_worker_reports_a_corrupt_file(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "bad.avv"
    path.write_text("{not json", encoding="utf-8")
    worker = SessionLoadWorker(path)
    errors: list[str] = []
    worker.error.connect(errors.append)

    _run_in_thread(worker, qtbot)

    assert errors


def test_load_worker_reports_an_unsupported_version(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "future.avv"
    path.write_text(json.dumps({"version": 99}), encoding="utf-8")
    worker = SessionLoadWorker(path)
    errors: list[str] = []
    worker.error.connect(errors.append)

    _run_in_thread(worker, qtbot)

    assert errors and "version" in errors[0].lower()


# ── Annotation export ─────────────────────────────────────────────────


def test_annotation_rows_snapshot_every_marker_video_pair() -> None:
    store = AnnotationStore()
    store.add_point(
        1.0,
        label="stance",
        video_frames=[
            VideoFrame(path="/cam/a.mp4", frame_index=30, media_timestamp=1.0),
            VideoFrame(path="/cam/b.mp4", frame_index=31, media_timestamp=1.01),
        ],
    )
    store.add_point(2.0, label="swing")

    rows = store.export_rows()

    assert len(rows) == 3
    assert [row.video_path for row in rows] == ["/cam/a.mp4", "/cam/b.mp4", ""]
    assert rows[2].frame_index == ""


def test_annotation_rows_are_detached_from_the_store() -> None:
    """A worker must not see edits made while it writes."""
    store = AnnotationStore()
    store.add_point(1.0, label="original")
    rows = store.export_rows()

    store.clear()
    store.add_point(9.0, label="changed")

    assert [row.label for row in rows] == ["original"]


def test_annotation_export_worker_writes_the_expected_csv(qtbot, tmp_path: Path) -> None:
    rows = [AnnotationRow("stance", "", 1.0, "/cam/a.mp4", 30, 1.0)]
    path = tmp_path / "ann.csv"
    worker = AnnotationExportWorker(rows, path)
    done: list[tuple[str, int]] = []
    worker.finished.connect(lambda p, n: done.append((p, n)))

    _run_in_thread(worker, qtbot)

    assert done == [(str(path), 1)]
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].split(",") == list(ANNOTATION_HEADER)
    assert lines[1].startswith("stance,,1.0,/cam/a.mp4,30,1.0")


def test_annotation_export_worker_reports_an_unwritable_path(qtbot, tmp_path: Path) -> None:
    worker = AnnotationExportWorker([], tmp_path / "nope" / "ann.csv")
    errors: list[str] = []
    worker.error.connect(errors.append)

    _run_in_thread(worker, qtbot)

    assert errors


# ── UI thread stays responsive ────────────────────────────────────────


def test_ui_heartbeat_survives_a_large_session_write(qtbot, tmp_path: Path) -> None:
    """A one-million-pair mapping must not stall the Qt event loop.

    The heartbeat timer fires every 5 ms while the worker writes; if the write
    were on the UI thread the loop would deliver a long gap instead of ticks.
    """
    master = np.arange(1_000_000, dtype=np.float64) / 1000.0
    heavy = SessionState(
        sync_provenance=[
            SyncProvenance(
                reference_id="sensor:ttl",
                target_id="video:cam",
                offset=0.0,
                drift_ppm=0.0,
                rms_residual=0.0,
                max_residual=0.0,
                matched_count=len(master),
                rejected_count=0,
                tolerance=0.01,
                exact_master=master,
                exact_source=master + 0.5,
            )
        ]
    )

    gaps: list[float] = []
    last = [time.monotonic()]

    def _beat() -> None:
        now = time.monotonic()
        gaps.append(now - last[0])
        last[0] = now

    heartbeat = QTimer()
    heartbeat.setInterval(5)
    heartbeat.timeout.connect(_beat)
    heartbeat.start()

    worker = SessionSaveWorker(heavy, tmp_path / "big.avv")
    _run_in_thread(worker, qtbot)
    heartbeat.stop()

    assert gaps, "The event loop delivered no heartbeat at all."
    assert max(gaps) < 0.5, (
        f"UI thread stalled for {max(gaps) * 1000:.0f} ms during a session write; "
        "session IO must stay on a worker."
    )


def test_main_window_autosave_uses_a_worker(qtbot, tmp_path: Path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._session_path = tmp_path / "auto.avv"

    window._autosave()

    assert window._session_thread is not None
    with qtbot.waitSignal(window._session_thread.finished, timeout=10_000):
        pass
    assert (tmp_path / "auto.avv").exists()
    window.close()


def test_main_window_close_writes_the_final_autosave_synchronously(qtbot, tmp_path: Path) -> None:
    """Handing the last write to a thread would race widget destruction."""
    window = MainWindow()
    qtbot.addWidget(window)
    window._session_path = tmp_path / "final.avv"

    window.close()

    assert (tmp_path / "final.avv").exists()
    assert window._session_thread is None
