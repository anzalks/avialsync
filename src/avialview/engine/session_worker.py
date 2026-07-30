"""Background workers for session persistence.

Architecture rule 3: the UI thread never blocks.  Session save, load, and
autosave all write or parse a file whose size grows with the recording — a
million-frame exact mapping is not a "fast enough" operation, and on a slow or
network drive none of them are.

Each worker takes an immutable snapshot at construction time, so the UI thread
can keep mutating its own state while the job runs.  Annotation export lives in
``engine/export_worker.py`` alongside the other export jobs.
Callers must register them through ``MainWindow._run_job``: a ``QObject`` moved
to a ``QThread`` with no Python reference is collected before ``started`` fires
and its ``run`` slot never executes (RECOVERY_PLAN V-01/V-02).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from avialview.core.session import SessionState

logger = logging.getLogger(__name__)


class SessionSaveWorker(QObject):
    """Serialize and write .avv + sidecars off the UI thread."""

    finished = Signal()
    error = Signal(str)

    def __init__(self, state: SessionState, path: Path) -> None:
        super().__init__()
        self._state = state
        self._path = path

    @Slot()
    def run(self) -> None:
        try:
            self._state.save(self._path)
            self.finished.emit()
        except Exception as e:
            logger.exception("Failed to save session to %s", self._path)
            self.error.emit(str(e))


class SessionLoadWorker(QObject):
    """Read and parse .avv + sidecars off the UI thread.

    Only parsing moves here.  Applying the result — creating panes, starting
    imports — stays on the UI thread, where Qt object ownership belongs.
    """

    finished = Signal(object)  # SessionState
    error = Signal(str)

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    @Slot()
    def run(self) -> None:
        try:
            state = SessionState.load(self._path)
            self.finished.emit(state)
        except Exception as e:
            logger.exception("Failed to load session from %s", self._path)
            self.error.emit(str(e))
