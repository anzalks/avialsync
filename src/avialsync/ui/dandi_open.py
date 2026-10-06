"""Open a DANDI NWB asset through the ordinary source import path."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QDialog, QInputDialog

from avialsync.core.errors import FileUnreadableError
from avialsync.engine.dandi_worker import DANDILinkWorker
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


def open_dandi(window: MainWindow) -> None:
    """Ask for an asset URL and register its link creation as a background job."""
    dialog = QInputDialog(window)
    dialog.setWindowTitle(tr("Open NWB from DANDI"))
    dialog.setLabelText(tr("Paste a DANDI NWB asset download URL:"))
    dialog.setAccessibleName(tr("DANDI NWB asset URL"))
    dialog.setAccessibleDescription(tr("An asset download URL from the DANDI Archive"))
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    url = dialog.textValue().strip()
    if not url:
        return
    worker = DANDILinkWorker(url)

    def report_error(message: str) -> None:
        window.report_failure(FileUnreadableError(message), doing=tr("Opening NWB from DANDI"))

    def configure(_thread: QThread) -> None:
        worker.finished.connect(on_ui_thread(lambda path: window.open_path(Path(path)), window))
        worker.error.connect(on_ui_thread(report_error, window))

    window._run_job(worker, label=tr("Opening NWB from DANDI"), configure=configure)
