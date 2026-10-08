"""Register pose preparation so cached-array access stays off the UI thread."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal, Slot

from avialsync.core.cache_leases import GenerationPin, pin_reader_directory
from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.errors import FileUnreadableError
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread
from avialsync.ui.tracking_3d_pane import PreparedTracking3D, prepare_tracking_3d

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


class Tracking3DPrepareWorker(QObject):
    """Open XYZ arrays and derive all orientation estimates in a worker."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(
        self, readers: tuple[MappedChannelReader, ...], pins: tuple[GenerationPin, ...]
    ) -> None:
        super().__init__()
        self._readers = readers
        self._pins = pins

    @Slot()
    def run(self) -> None:
        """Produce one immutable result for the current pose selection."""
        try:
            self.finished.emit(prepare_tracking_3d(self._readers))
        except Exception as error:  # noqa: BLE001 - job boundary reports unexpected file failures
            logger.exception("Could not prepare the 3D pose view")
            self.error.emit(str(error) or "Could not prepare the 3D pose view")


def start_pose_preparation(window: MainWindow, readers: list[MappedChannelReader]) -> None:
    """Install only the latest selection from a registered background job."""
    pane = window.tracking_3d_pane
    if not readers:
        pane.set_readers([])
        window._update_tracking_pane_visibility()
        return
    revision = pane.begin_prepare()
    session_generation = window.session_runtime.generation
    pins: list[GenerationPin] = []
    directories = {getattr(reader, "source_reader", reader).cache_dir for reader in readers}
    for directory in directories:
        pin = pin_reader_directory(directory)
        if pin is None:
            for held in pins:
                held.close()
            window.report_failure(
                FileUnreadableError(str(directory)), doing=tr("preparing 3D tracking")
            )
            pane.set_readers([])
            window._update_tracking_pane_visibility()
            return
        pins.append(pin)
    worker = Tracking3DPrepareWorker(tuple(readers), tuple(pins))

    def current() -> bool:
        return (
            revision == pane.prepare_revision
            and session_generation == window.session_runtime.generation
        )

    def on_finished(result: object) -> None:
        if not current() or not isinstance(result, PreparedTracking3D):
            return
        pane.set_prepared(result)
        pane.set_cursor(window.clock.state.t)
        window._update_tracking_pane_visibility()

    def on_error(message: str) -> None:
        if current():
            pane.set_readers([])
            window._update_tracking_pane_visibility()
            window.report_failure(FileUnreadableError(message), doing=tr("preparing 3D tracking"))

    def wire(_thread: QThread) -> None:
        worker.finished.connect(on_ui_thread(on_finished, window))
        worker.error.connect(on_ui_thread(on_error, window))

    window._run_job(worker, label=tr("Preparing 3D tracking"), configure=wire)
