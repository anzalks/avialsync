"""Persist a DANDI NWB asset URL off the UI thread for session restore."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.errors import FileUnreadableError
from avialsync.loaders.nwb_storage import create_remote_link


class DANDILinkWorker(QObject):
    """Create the small link file before the ordinary drop scanner opens it."""

    finished = Signal(str)
    error = Signal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(str(create_remote_link(self._url)))
        except (FileUnreadableError, OSError, ValueError) as error:
            self.error.emit(str(error))
