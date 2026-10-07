"""Read and write physical-prop sidecars away from the GUI thread."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.errors import PropModelError
from avialsync.core.physical_props import PhysicalProp
from avialsync.core.prop_file import PropKind, read_props, write_prop, write_removed
from avialsync.core.wheel import Wheel


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

    def __init__(
        self,
        folder: Path,
        name: str,
        prop: PhysicalProp | Wheel | None,
        *,
        kind: PropKind = "ladder",
        overwrite_existing: bool = True,
    ) -> None:
        super().__init__()
        self._folder = folder
        self._name = name
        self._prop = prop
        self._kind = kind
        self._overwrite_existing = overwrite_existing

    @Slot()
    def run(self) -> None:
        try:
            path = (
                write_prop(self._folder, self._prop, overwrite_existing=self._overwrite_existing)
                if self._prop is not None
                else write_removed(
                    self._folder,
                    self._name,
                    kind=self._kind,
                    overwrite_existing=self._overwrite_existing,
                )
            )
        except (OSError, ValueError, PropModelError) as error:
            self.error.emit(str(error))
        else:
            self.finished.emit(path)
