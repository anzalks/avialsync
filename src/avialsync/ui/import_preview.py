"""Hand a bounded worker preview to the text import wizard."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QThread, QTimer

from avialsync.core.errors import FileUnreadableError
from avialsync.core.source import TimeSeriesSource
from avialsync.engine.import_preview_worker import ImportPreviewWorker
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


def start_preview(
    window: MainWindow,
    path: Path,
    loader_cls: type[TimeSeriesSource],
    config: dict[str, Any],
) -> None:
    """Read a text prefix through the job registry before showing its wizard."""
    worker = ImportPreviewWorker(path)
    generation = window.session_runtime.generation

    def show_wizard(preview: bytes) -> None:
        if generation != window.session_runtime.generation:
            return
        from avialsync.ui.import_wizard import ImportWizard

        wizard = ImportWizard(path, preview, window)
        if wizard.exec() != ImportWizard.DialogCode.Accepted:
            return
        window._enqueue_import(path, loader_cls, {**config, **wizard.config()})

    def on_finished(preview: bytes) -> None:
        QTimer.singleShot(0, window, lambda: show_wizard(preview))

    def on_error(message: str) -> None:
        if generation == window.session_runtime.generation:
            window.report_failure(
                FileUnreadableError(message), doing=tr("previewing {name}").format(name=path.name)
            )

    def wire(_thread: QThread) -> None:
        worker.finished.connect(on_ui_thread(on_finished, window))
        worker.error.connect(on_ui_thread(on_error, window))

    window._run_job(
        worker, label=tr("Reading preview of {name}").format(name=path.name), configure=wire
    )
