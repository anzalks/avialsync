"""Read the launch-time recovery snapshot away from the UI event loop."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal, Slot

from avialsync.core.errors import FileUnreadableError
from avialsync.ui import recovery
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


class RecoveryReadWorker(QObject):
    """Resolve and validate a prior session's recovery offer in a registered job."""

    finished = Signal(object)
    error = Signal(str)

    @Slot()
    def run(self) -> None:
        """Read the snapshot and its dismissal marker on this worker thread."""
        try:
            self.finished.emit(recovery.pending_recovery())
        except (OSError, RuntimeError, ValueError) as error:
            self.error.emit(str(error))


class RecoveryDismissWorker(QObject):
    """Hash and remember a declined recovery snapshot off the UI thread."""

    finished = Signal()
    error = Signal(str)

    def __init__(self, snapshot: recovery.RecoverySnapshot) -> None:
        super().__init__()
        self._snapshot = snapshot

    @Slot()
    def run(self) -> None:
        """Persist the dismissal marker through the recovery module."""
        try:
            recovery.dismiss_recovery(self._snapshot)
            self.finished.emit()
        except (OSError, RuntimeError, ValueError) as error:
            self.error.emit(str(error))


def start_recovery_dismiss(window: MainWindow, snapshot: recovery.RecoverySnapshot) -> None:
    """Register dismissal work so hashing a large session cannot stall a click."""
    window._run_job(RecoveryDismissWorker(snapshot), label=tr("Remembering recovery choice"))


def start_recovery_check(window: MainWindow) -> None:
    """Read the launch snapshot as a registered job after the window is built."""
    worker = RecoveryReadWorker()
    revision = window.session_runtime.recovery_revision

    def on_finished(result: object) -> None:
        if revision != window.session_runtime.recovery_revision:
            return
        snapshot = result if isinstance(result, recovery.RecoverySnapshot) else None
        window.session_runtime.pending_recovery = snapshot
        window._refresh_action_availability()
        present_pending_recovery(window, snapshot)

    def on_error(message: str) -> None:
        if revision != window.session_runtime.recovery_revision:
            return
        window.report_failure(FileUnreadableError(message), doing=tr("checking for unsaved work"))

    def wire(_thread: QThread) -> None:
        worker.finished.connect(on_ui_thread(on_finished, window))
        worker.error.connect(on_ui_thread(on_error, window))

    window._run_job(worker, label=tr("Checking for unsaved work"), configure=wire)


def present_pending_recovery(
    window: MainWindow, snapshot: recovery.RecoverySnapshot | None
) -> bool:
    """Offer an already-read snapshot without file access on the UI callback."""
    from avialsync.ui.controllers import session_controller

    if snapshot is None or not session_controller.offers_recovery_at_launch():
        return False
    when = time.strftime("%H:%M on %d %b", time.localtime(snapshot.recovered_at))
    if snapshot.describes_untitled_session:
        message = tr("Unsaved work from {when} is available.").format(when=when)
    else:
        message = tr("Work from {when} is newer than {name}.").format(
            when=when, name=Path(str(snapshot.session_path)).name
        )
    window.notifications.show_warning(
        message,
        action_label=tr("Restore"),
        on_action=lambda: session_controller.restore_pending_recovery(window, snapshot),
        on_dismiss=lambda: start_recovery_dismiss(window, snapshot),
    )
    return True
