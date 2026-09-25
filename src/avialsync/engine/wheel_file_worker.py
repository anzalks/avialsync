"""Read wheel sidecars off the UI thread when a recording opens."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.wheel_file import read_wheels


class WheelFileReadWorker(QObject):
    """Read the wheels in one recording folder without touching widgets."""

    finished = Signal(object, object)
    error = Signal(str)

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self._folder = folder

    @Slot()
    def run(self) -> None:
        try:
            wheels, unreadable = read_wheels(self._folder)
        except OSError as error:
            self.error.emit(str(error))
            return
        self.finished.emit(wheels, unreadable)
