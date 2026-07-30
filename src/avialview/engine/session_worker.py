"""Background workers for loading and saving session states."""

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
    """Read and parse .avv + sidecars off the UI thread."""

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
