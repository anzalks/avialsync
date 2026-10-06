"""Open an NWB file, local or a DANDI asset by its address, the ordinary way."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from avialsync.core.errors import FileUnreadableError
from avialsync.engine.dandi_worker import DANDILinkWorker
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


def _ask_location(window: MainWindow) -> str:
    """A local NWB file or folder, or a DANDI asset URL; empty when cancelled."""
    dialog = QDialog(window)
    dialog.setWindowTitle(window._act_open_nwb.text().rstrip("…"))
    dialog.setAccessibleName(tr("Open NWB"))
    field = QLineEdit(dialog)
    field.setPlaceholderText(tr("A .nwb file or folder, or a DANDI asset URL"))
    field.setAccessibleName(tr("NWB file or DANDI asset URL"))
    browse = QPushButton(tr("Browse…"), dialog)
    browse.setAccessibleName(tr("Choose a local NWB file"))

    def choose() -> None:
        path, _ = QFileDialog.getOpenFileName(
            dialog, tr("Open NWB"), "", tr("NWB files (*.nwb);;All files (*)")
        )
        if path:
            field.setText(path)

    browse.clicked.connect(choose)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel, dialog
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    row = QHBoxLayout()
    row.addWidget(field, 1)
    row.addWidget(browse)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(tr("Open a local NWB file, or stream one from DANDI by its address:")))
    layout.addLayout(row)
    layout.addWidget(buttons)
    dialog.resize(520, dialog.sizeHint().height())
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return ""
    return field.text().strip()


def open_nwb(window: MainWindow) -> None:
    """Open a local NWB directly; register a DANDI address's link as a background job."""
    location = _ask_location(window)
    if not location:
        return
    if "://" not in location:
        window.open_path(Path(location).expanduser())
        return
    worker = DANDILinkWorker(location)

    def report_error(message: str) -> None:
        window.report_failure(FileUnreadableError(message), doing=tr("Opening NWB from DANDI"))

    def configure(_thread: QThread) -> None:
        worker.finished.connect(on_ui_thread(lambda path: window.open_path(Path(path)), window))
        worker.error.connect(on_ui_thread(report_error, window))

    window._run_job(worker, label=tr("Opening NWB from DANDI"), configure=configure)
