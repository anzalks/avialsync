"""Read and write physical-prop sidecars away from the GUI thread."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.errors import PropModelError
from avialsync.core.physical_props import Ladder
from avialsync.core.prop_file import read_props, write_ladder, write_removed
from avialsync.core.wheel_file import wheel_path


class PropFileReadWorker(QObject):
    """Discover independent prop records in a recording folder."""

    finished = Signal(object, object)
    error = Signal(str)

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self._folder = folder

    @Slot()
    def run(self) -> None:
        try:
            props, issues = read_props(self._folder)
        except OSError as error:
            self.error.emit(str(error))
        else:
            self.finished.emit(props, issues)


class PropFileWriteWorker(QObject):
    """Write one immutable accepted revision atomically."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, folder: Path, name: str, ladder: Ladder | None) -> None:
        super().__init__()
        self._folder = folder
        self._name = name
        self._ladder = ladder

    @Slot()
    def run(self) -> None:
        try:
            if wheel_path(self._folder, self._name).exists():
                raise PropModelError("A wheel sidecar already uses this prop name.")
            path = (
                write_ladder(self._folder, self._ladder)
                if self._ladder is not None
                else write_removed(self._folder, self._name)
            )
        except (OSError, ValueError, PropModelError) as error:
            self.error.emit(str(error))
        else:
            self.finished.emit(path)
