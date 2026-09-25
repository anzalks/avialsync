"""Where a wheel is kept: written from mutations, read when a recording opens.

Split from :mod:`avialsync.ui.controllers.wheel_controller` (D-113). The file
format is :mod:`avialsync.core.wheel_file`; this decides *when* and *where*:

* **Written only from the mutation funnel** (``WindowMutationTarget.set_wheel``),
  so reading a file back never echoes it straight out again -- D-099's rule.
* **Read back without rolling anything back**: a wheel already in the session
  wins over its file, including when it was placed while a read was running.
* **A damaged file costs that wheel only** and is named once (rule 10).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread

from avialsync.core.wheel import Wheel
from avialsync.core.wheel_file import write_removed, write_wheel
from avialsync.engine.wheel_file_worker import WheelFileReadWorker
from avialsync.ui.controllers import calibration_controller as calibration
from avialsync.ui.controllers import rig_paths
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

__all__ = ["persist", "adopt"]


def persist(window: MainWindow, name: str) -> None:
    """Write wheel *name*'s file now, from the mutation funnel only (D-099's rule)."""
    folder = rig_paths.pose3d_dir(window)
    if folder is None:
        return
    wheel = window.wheels.get(name)
    try:
        written = write_wheel(folder, wheel) if wheel is not None else write_removed(folder, name)
    except OSError as error:
        logger.warning("Could not write wheel %s", name, exc_info=True)
        window.notifications.show_warning(
            tr("Wheel {name} could not be saved beside the data.").format(name=name),
            details=str(error),
        )
        return
    if written is not None and name not in window._announced_wheel_files:
        window._announced_wheel_files.add(name)
        window.notifications.show_success(
            tr("Wheel {name} is saved beside the 3D pose, as {file}.").format(
                name=name, file=written.name
            )
        )


def adopt(window: MainWindow) -> None:
    """Read saved wheels when a video or pose source identifies their folder.

    One job per folder in this session; later panes and pose files share its
    result. Existing in-memory edits win if the read finishes after an edit.
    """
    folder = rig_paths.pose3d_dir(window)
    if folder is None or folder in window._wheel_adopt_folders:
        return
    window._wheel_adopt_folders.add(folder)
    generation = window._session_generation
    worker = WheelFileReadWorker(folder)

    def on_finished(wheels: list[Wheel], unreadable: list[str]) -> None:
        if generation != window._session_generation:
            return
        _accept_read(window, wheels, unreadable)

    def on_error(message: str) -> None:
        if generation != window._session_generation:
            return
        window._wheel_adopt_folders.discard(folder)
        window.notifications.show_warning(
            tr("Saved wheels in {folder} could not be read.").format(folder=folder.name),
            details=message,
        )

    def _wire(_thread: QThread) -> None:
        worker.finished.connect(on_ui_thread(on_finished, window))
        worker.error.connect(on_ui_thread(on_error, window))

    window._run_job(worker, label=tr("Reading saved wheels"), configure=_wire)


def _accept_read(window: MainWindow, wheels: list[Wheel], unreadable: list[str]) -> None:
    """Merge a completed read without replacing any wheel already in memory."""
    for file_name in unreadable:
        if file_name not in window._announced_wheel_files:
            window._announced_wheel_files.add(file_name)
            window.notifications.show_warning(
                tr("{file} could not be read, so that wheel is not shown.").format(file=file_name)
            )
    current = {wheel.name: wheel for wheel in window.wheels}
    added = [wheel for wheel in wheels if wheel.name not in current]
    if not added:
        return
    calibration.calibration_quietly(window)
    window.wheels.load([*current.values(), *added])
