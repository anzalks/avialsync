"""Run one plain-data artifact write in a registered background job."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

logger = logging.getLogger(__name__)


class ArtifactWriteWorker(QObject):
    """Execute a prepared writer without touching a widget or mutable store."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, write: Callable[[], Path]) -> None:
        super().__init__()
        self._write = write
        self._cancelled = False

    def cancel(self) -> None:
        """Skip work that has not started yet."""
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        """Write the artifact and report its path or failure."""
        if self._cancelled:
            self.error.emit("Cancelled")
            return
        try:
            path = self._write()
        except Exception as exc:  # noqa: BLE001 - one job boundary reports every write failure
            logger.warning("Artifact write failed", exc_info=exc)
            self.error.emit(str(exc))
            return
        self.finished.emit(path)
