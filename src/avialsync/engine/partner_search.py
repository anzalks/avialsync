"""Registered worker that asks a session plugin for a loaded recording's partner."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.source import SessionSource


class PartnerSearchWorker(QObject):
    """Run :meth:`SessionSource.find_partner` off the UI thread and report its answer."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, finder: type[SessionSource], epoch: float) -> None:
        super().__init__()
        self.finder = finder
        self.epoch = epoch

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.finder.find_partner(self.epoch))
        except Exception as error:  # noqa: BLE001 - plugin boundary
            self.error.emit(f"{type(error).__name__}: {error}")
