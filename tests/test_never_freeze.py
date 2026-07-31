"""The UI must stay responsive, visible, and closeable under any workload.

This is the property V-09 was really about. A 2 500-line window is a review
hazard; an application you cannot quit while a network share hangs is a defect
the user actually hits.

Three guarantees:

1. **The window always closes.** ``closeEvent`` used to ``event.ignore()`` while
   any background job was running.
2. **Stuck work is visible.** A job that stops reporting is named as not
   responding, so "slow" and "stuck" look different.
3. **The UI thread is watched.** Blocking it is reported rather than merely felt.
"""

from __future__ import annotations

import threading
import time

import pytest
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QApplication

from avialview.ui.job_manager import JobManager, JobState, drain_abandoned
from avialview.ui.main_window import MainWindow
from avialview.ui.ui_heartbeat import REPORT_THRESHOLD_MS, UiHeartbeat


class _WedgedWorker(QObject):
    """A worker that ignores cancellation, like a blocked syscall."""

    finished = Signal()
    error = Signal(str)

    def __init__(self, release: threading.Event) -> None:
        super().__init__()
        self._release = release
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1  # recorded, and deliberately not acted on

    @Slot()
    def run(self) -> None:
        self._release.wait(timeout=30.0)
        self.finished.emit()


class _QuickWorker(QObject):
    finished = Signal()
    error = Signal(str)
    progress = Signal(int)

    @Slot()
    def run(self) -> None:
        self.progress.emit(50)
        self.finished.emit()


@pytest.fixture
def release():
    """Unblock and drain every wedged worker before the test process moves on.

    Abandoned threads are retained on purpose (Qt aborts if a running QThread is
    destroyed), so the suite has to let them finish or interpreter shutdown trips
    that same abort.
    """
    event = threading.Event()
    yield event
    event.set()
    drain_abandoned()


# ── 1. The window always closes ───────────────────────────────────────


def test_shutdown_returns_even_when_a_job_refuses_to_stop(qapp, qtbot, release) -> None:
    """A wedged job must not hold shutdown open."""
    manager = JobManager()
    worker = _WedgedWorker(release)
    manager.start("Probing camera_1.mp4", worker)
    qtbot.waitUntil(manager.is_busy, timeout=2_000)

    started = time.monotonic()
    abandoned = manager.shutdown(grace_s=0.3)
    elapsed = time.monotonic() - started

    assert abandoned == ["Probing camera_1.mp4"]
    assert elapsed < 3.0, f"shutdown blocked for {elapsed:.1f}s"
    assert worker.cancel_calls >= 1, "shutdown must ask before abandoning"


def test_shutdown_is_bounded_with_many_wedged_jobs(qapp, qtbot, release) -> None:
    """The grace period is a total budget, not per job."""
    manager = JobManager()
    for index in range(5):
        manager.start(f"job-{index}", _WedgedWorker(release))
    qtbot.waitUntil(lambda: len(manager.jobs()) == 5, timeout=2_000)

    started = time.monotonic()
    abandoned = manager.shutdown(grace_s=0.3)

    assert len(abandoned) == 5
    assert time.monotonic() - started < 3.0


def test_closing_the_window_is_not_refused_while_work_runs(
    qapp: QApplication, qtbot, release, tmp_path
) -> None:
    """The regression: closeEvent called event.ignore() and trapped the user."""
    window = MainWindow()
    qtbot.addWidget(window)
    window._job_manager.start("Importing sensors.csv", _WedgedWorker(release))
    qtbot.waitUntil(window._job_manager.is_busy, timeout=2_000)

    accepted = window.close()

    assert accepted, "the window refused to close while a job was running"
    assert not window.isVisible()


def test_closing_still_writes_the_final_autosave(qapp, qtbot, release, tmp_path) -> None:
    """Abandoning jobs must not skip the session write."""
    window = MainWindow()
    qtbot.addWidget(window)
    window._session_path = tmp_path / "final.avv"
    window._job_manager.start("Exporting clip", _WedgedWorker(release))

    window.close()

    assert (tmp_path / "final.avv").exists()


# ── 2. Stuck work is visible ──────────────────────────────────────────


def test_a_quiet_job_is_reported_as_not_responding(qapp, qtbot, release) -> None:
    import avialview.ui.job_manager as module

    manager = JobManager()
    manager.start("Probing a network share", _WedgedWorker(release))
    qtbot.waitUntil(manager.is_busy, timeout=2_000)

    # Collapse the watchdog window rather than waiting 20 real seconds.
    original = module.NOT_RESPONDING_AFTER_S
    module.NOT_RESPONDING_AFTER_S = 0.0
    try:
        manager._check_for_stalls()
    finally:
        module.NOT_RESPONDING_AFTER_S = original

    assert manager.stalled_jobs()
    assert "Not responding" in manager.status_text()
    assert "network share" in manager.status_text()
    manager.shutdown(grace_s=0.1)


def test_status_names_the_running_job(qapp, qtbot, release) -> None:
    manager = JobManager()
    manager.start("Importing sensors.csv", _WedgedWorker(release))
    qtbot.waitUntil(manager.is_busy, timeout=2_000)

    assert manager.status_text().startswith("Importing sensors.csv")

    manager.shutdown(grace_s=0.1)


def test_status_summarises_several_jobs(qapp, qtbot, release) -> None:
    manager = JobManager()
    manager.start("Importing a.csv", _WedgedWorker(release))
    manager.start("Importing b.csv", _WedgedWorker(release))
    qtbot.waitUntil(lambda: len(manager.jobs()) == 2, timeout=2_000)

    assert "+1 more" in manager.status_text()

    manager.shutdown(grace_s=0.1)


def test_status_is_empty_when_nothing_is_running(qapp) -> None:
    assert JobManager().status_text() == ""


def test_progress_clears_a_not_responding_state(qapp, qtbot) -> None:
    """A job that starts reporting again must stop being flagged."""
    manager = JobManager()
    worker = _QuickWorker()
    manager.start("Building pyramid", worker)
    qtbot.waitUntil(lambda: not manager.is_busy(), timeout=5_000)

    assert manager.status_text() == ""


def test_the_window_mirrors_job_state_into_its_status_area(qapp, qtbot, release) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window._job_manager.start("Generating proxy", _WedgedWorker(release))
    qtbot.waitUntil(lambda: "Generating proxy" in window.transport.status_text(), timeout=2_000)

    window.close()


# ── 3. The UI thread is watched ───────────────────────────────────────


def test_heartbeat_reports_a_blocked_ui_thread(qapp, qtbot) -> None:
    """Blocking the loop must be surfaced, not merely felt as lag."""
    heartbeat = UiHeartbeat()
    stalls: list[float] = []
    heartbeat.stalled.connect(stalls.append)
    heartbeat.start()

    # Block the UI thread the way a synchronous read would.
    time.sleep((REPORT_THRESHOLD_MS + 150) / 1000.0)
    qtbot.waitUntil(lambda: bool(stalls), timeout=3_000)
    heartbeat.stop()

    assert stalls[0] >= REPORT_THRESHOLD_MS
    assert heartbeat.worst_stall_ms >= REPORT_THRESHOLD_MS


def test_heartbeat_stays_quiet_on_a_responsive_loop(qapp, qtbot) -> None:
    heartbeat = UiHeartbeat()
    stalls: list[float] = []
    heartbeat.stalled.connect(stalls.append)
    heartbeat.start()

    qtbot.wait(400)
    heartbeat.stop()

    assert stalls == []


def test_heartbeat_reset_clears_history(qapp) -> None:
    heartbeat = UiHeartbeat()
    heartbeat._worst_ms = 999.0
    heartbeat._stall_count = 3

    heartbeat.reset()

    assert heartbeat.worst_stall_ms == 0.0
    assert heartbeat.stall_count == 0


def test_the_window_runs_a_heartbeat(qapp, qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window._heartbeat._timer.isActive()

    window.close()
    assert not window._heartbeat._timer.isActive()


# ── Ownership (the V-01/V-02 root cause) ──────────────────────────────


def test_a_registered_worker_actually_runs(qapp, qtbot) -> None:
    """A QObject moved to a QThread with no Python reference never starts."""
    manager = JobManager()
    worker = _QuickWorker()
    done: list[bool] = []
    worker.finished.connect(lambda: done.append(True))

    manager.start("quick", worker)

    qtbot.waitUntil(lambda: done == [True], timeout=5_000)


def test_finished_jobs_are_dropped_from_the_registry(qapp, qtbot) -> None:
    manager = JobManager()
    manager.start("quick", _QuickWorker())

    qtbot.waitUntil(lambda: not manager.is_busy(), timeout=5_000)

    assert manager.jobs() == []


def test_cancel_all_asks_every_job(qapp, qtbot, release) -> None:
    manager = JobManager()
    workers = [_WedgedWorker(release) for _ in range(3)]
    for index, worker in enumerate(workers):
        manager.start(f"job-{index}", worker)
    qtbot.waitUntil(lambda: len(manager.jobs()) == 3, timeout=2_000)

    manager.cancel_all()

    assert all(worker.cancel_calls >= 1 for worker in workers)
    assert all(job.state is JobState.CANCELLING for job in manager.jobs())
    manager.shutdown(grace_s=0.1)
