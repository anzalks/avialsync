"""Bounded, off-thread file preview for the text import wizard."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

PREVIEW_BYTES = 64 * 1024


class ImportPreviewWorker(QObject):
    """Read only the bytes needed to inspect a text source's first rows."""

    finished = Signal(bytes)
    error = Signal(str)
    cancelled = Signal()

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Discard a preview no longer needed by the workspace."""
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        """Read a bounded prefix without involving the UI thread."""
        if self._cancel.is_set():
            self.cancelled.emit()
            return
        try:
            with self._path.open("rb") as source:
                preview = source.read(PREVIEW_BYTES)
        except OSError as error:
            self.error.emit(str(error))
            return
        if self._cancel.is_set():
            self.cancelled.emit()
            return
        self.finished.emit(preview)
