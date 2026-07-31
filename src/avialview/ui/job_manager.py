"""One owner for every background job, so the UI can never be trapped.

Three properties this exists to guarantee, in priority order:

1. **The window always closes.** Shutdown asks every job to cancel, waits a
   bounded moment, and then closes regardless. A hung ``ffprobe`` on a network
   share must not strand the user in an application they cannot quit. Cache
   writes are atomic (staged then renamed), so an abandoned job leaves the
   previous valid sidecar rather than a half-written one — that design is what
   makes abandoning safe.
2. **Work is visible.** Every job carries a human-readable label and a state.
   A job that stops reporting progress is marked *not responding* rather than
   just appearing to hang, so the user can tell the difference between "slow"
   and "stuck".
3. **Ownership is explicit.** A ``QObject`` moved to a ``QThread`` with no
   Python reference is collected before ``started`` fires and its ``run`` slot
   never executes (RECOVERY_PLAN V-01/V-02). Registering here is the only
   supported way to start background work in this application.

This is a ``QObject`` rather than a mixin on ``MainWindow`` deliberately: slots
inherited from a plain mixin lose ``sender()`` and get direct instead of queued
connections, which put widget construction on a worker thread (D-051). Both ends
of every connection here are real QObjects.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from PySide6.QtCore import QObject, QThread, QTimer, Signal


class BackgroundWorker(Protocol):
    """What :class:`JobManager` needs of a worker.

    A ``QObject`` with a ``run()`` slot. ``cancel()`` is optional; a worker
    without it simply cannot be asked to stop early, and shutdown abandons it
    rather than waiting.
    """

    def run(self) -> None: ...
    def moveToThread(self, thread: QThread, /) -> bool: ...


logger = logging.getLogger(__name__)

#: A job that has not reported progress for this long is shown as not
#: responding. It is not cancelled — a legitimate 1 GB import can be quiet for a
#: while — but the user is told, which is the difference between slow and stuck.
NOT_RESPONDING_AFTER_S = 20.0

#: How long shutdown waits for cancelled jobs before closing anyway. Long enough
#: for a cooperative worker to notice its cancel flag, short enough that a wedged
#: one does not hold the window open.
SHUTDOWN_GRACE_S = 3.0

_WATCHDOG_INTERVAL_MS = 1000


def drain_abandoned(timeout_ms: int = 2000) -> None:
    """Wait for abandoned threads to finish. For tests and orderly interpreter exit.

    Production never needs this — the window has already closed — but leaving
    running QThreads alive at interpreter shutdown makes Qt abort, which turns a
    clean test run into a crash report.
    """
    for job in list(_ABANDONED):
        job.thread.wait(timeout_ms)
        if job.thread.isFinished():
            _ABANDONED.remove(job)


#: Threads abandoned at shutdown, kept alive deliberately.
#:
#: Qt aborts the process with "QThread: Destroyed while thread is still running"
#: if a running QThread is garbage-collected, so dropping the reference to a
#: wedged job would crash on the way out — the exact opposite of closing
#: gracefully. These live until process exit; the OS reclaims them.
_ABANDONED: list[Job] = []


class JobState(Enum):
    """What a background job is doing, from the user's point of view."""

    RUNNING = "running"
    CANCELLING = "cancelling"
    NOT_RESPONDING = "not responding"


@dataclass
class Job:
    """One unit of background work, owned for its whole lifetime."""

    label: str
    worker: BackgroundWorker
    thread: QThread
    state: JobState = JobState.RUNNING
    started_at: float = field(default_factory=time.monotonic)
    last_progress_at: float = field(default_factory=time.monotonic)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def can_cancel(self) -> bool:
        """Whether the worker offers a cooperative cancel."""
        return callable(getattr(self.worker, "cancel", None))


class JobManager(QObject):
    """Owns every background worker/thread pair and reports their state."""

    #: Emitted whenever the set of jobs or any job's state changes.
    jobs_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._jobs: dict[QThread, Job] = {}
        self._shutting_down = False
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(_WATCHDOG_INTERVAL_MS)
        self._watchdog.timeout.connect(self._check_for_stalls)

    # ── Starting work ────────────────────────────────────────────────

    def start(
        self,
        label: str,
        worker: BackgroundWorker,
        configure: Callable[[QThread], None] | None = None,
    ) -> QThread:
        """Own *worker* on a new thread and start it.

        ``configure`` runs after the standard wiring and before the thread
        starts, so callers can connect their own result signals.
        """
        thread = QThread(self)
        worker.moveToThread(thread)
        job = Job(label=label, worker=worker, thread=thread)
        self._jobs[thread] = job

        thread.started.connect(worker.run)
        thread.finished.connect(self._on_thread_finished)
        thread.finished.connect(thread.deleteLater)

        for signal_name in ("progress", "finished", "error"):
            signal = getattr(worker, signal_name, None)
            if signal is not None and hasattr(signal, "connect"):
                signal.connect(self._note_progress)

        # Quit the thread when the worker reports it is done. Without this the
        # thread's event loop runs forever: the job never leaves the registry,
        # so the status bar stays busy and the still-running QThread makes Qt
        # abort at interpreter exit. Callers may connect their own handlers to
        # the same signals; queued slots still run.
        for signal_name in ("finished", "error", "cancelled"):
            signal = getattr(worker, signal_name, None)
            if signal is not None and hasattr(signal, "connect"):
                signal.connect(thread.quit)

        if configure is not None:
            configure(thread)

        if not self._watchdog.isActive():
            self._watchdog.start()
        thread.start()
        self.jobs_changed.emit()
        return thread

    # ── Reporting ────────────────────────────────────────────────────

    def jobs(self) -> list[Job]:
        """Every job currently owned, newest last."""
        return list(self._jobs.values())

    def is_busy(self) -> bool:
        return bool(self._jobs)

    def stalled_jobs(self) -> list[Job]:
        """Jobs that have gone quiet for longer than the watchdog allows."""
        return [job for job in self._jobs.values() if job.state is JobState.NOT_RESPONDING]

    def status_text(self) -> str:
        """A one-line summary for the transport status area."""
        jobs = self.jobs()
        if not jobs:
            return ""
        stalled = [job for job in jobs if job.state is JobState.NOT_RESPONDING]
        if stalled:
            names = ", ".join(job.label for job in stalled[:2])
            suffix = f" (+{len(stalled) - 2} more)" if len(stalled) > 2 else ""
            return f"Not responding: {names}{suffix}"
        if len(jobs) == 1:
            return f"{jobs[0].label}…"
        return f"{jobs[0].label} (+{len(jobs) - 1} more)…"

    # ── Cancelling and shutdown ──────────────────────────────────────

    def cancel_all(self) -> None:
        """Ask every cancellable job to stop; never blocks."""
        for job in self._jobs.values():
            self._request_cancel(job)
        self.jobs_changed.emit()

    def shutdown(self, grace_s: float = SHUTDOWN_GRACE_S) -> list[str]:
        """Stop everything and return the labels that had to be abandoned.

        Always returns within roughly *grace_s*. The window closes either way:
        being unable to quit is a worse failure than an abandoned background
        job, and atomic cache commits mean an abandoned one cannot corrupt a
        sidecar.
        """
        self._shutting_down = True
        self._watchdog.stop()
        for job in list(self._jobs.values()):
            self._request_cancel(job)
            job.thread.quit()

        deadline = time.monotonic() + max(0.0, grace_s)
        for job in list(self._jobs.values()):
            remaining_ms = int(max(0.0, deadline - time.monotonic()) * 1000)
            job.thread.wait(remaining_ms)

        still_running = [job for job in self._jobs.values() if job.thread.isRunning()]
        for job in still_running:
            # Detach and retain rather than destroy. Qt aborts the process if a
            # running QThread is garbage-collected, so dropping the reference
            # would turn a graceful close into a crash. QThread.terminate() is
            # not used: on a thread blocked in Python it deadlocks against the
            # GIL, which is worse than the job it was meant to stop. Every real
            # worker here is cooperative and will notice its cancel flag; a
            # thread stuck in a blocked syscall exits when that syscall does.
            job.thread.setParent(None)
            _ABANDONED.append(job)

        abandoned = [job.label for job in still_running]
        if abandoned:
            logger.warning(
                "Closing with %d background job(s) still running: %s. "
                "Cache commits are atomic, so the previous sidecar remains valid.",
                len(abandoned),
                ", ".join(abandoned),
            )
        self._jobs.clear()
        self.jobs_changed.emit()
        return abandoned

    # ── Internals ────────────────────────────────────────────────────

    def _request_cancel(self, job: Job) -> None:
        if not job.can_cancel():
            return
        job.state = JobState.CANCELLING
        try:
            job.worker.cancel()  # type: ignore[attr-defined]  # guarded by can_cancel()
        except RuntimeError:
            # The worker's C++ side is already gone; nothing left to cancel.
            logger.debug("Cancel skipped for finished job %s", job.label)

    def _note_progress(self, *_args: object) -> None:
        """Refresh the watchdog clock for whichever job reported."""
        sender = self.sender()
        for job in self._jobs.values():
            if job.worker is sender:
                job.last_progress_at = time.monotonic()
                if job.state is JobState.NOT_RESPONDING:
                    job.state = JobState.RUNNING
                    self.jobs_changed.emit()
                return

    def _check_for_stalls(self) -> None:
        changed = False
        for job in self._jobs.values():
            quiet_for = time.monotonic() - job.last_progress_at
            if job.state is JobState.RUNNING and quiet_for > NOT_RESPONDING_AFTER_S:
                job.state = JobState.NOT_RESPONDING
                logger.warning("Job %r has not reported for %.0fs", job.label, quiet_for)
                changed = True
        if changed:
            self.jobs_changed.emit()

    def _on_thread_finished(self) -> None:
        """Drop finished threads without relying on sender() identity (D-051)."""
        if self._shutting_down:
            return
        finished = [thread for thread in self._jobs if thread.isFinished()]
        for thread in finished:
            self._jobs.pop(thread, None)
        if not self._jobs:
            self._watchdog.stop()
        if finished:
            self.jobs_changed.emit()
