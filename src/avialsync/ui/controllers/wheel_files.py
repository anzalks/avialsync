"""Where a wheel is kept: written from the mutation funnel, read back as pose data loads.

Split from :mod:`avialsync.ui.controllers.wheel_controller` (D-113). The file
format is :mod:`avialsync.core.wheel_file`; this decides *when* and *where*:

* **Written only from the mutation funnel** (``WindowMutationTarget.set_wheel``),
  so reading a file back never echoes it straight out again -- D-099's rule.
* **Read back without rolling anything back**: a wheel already in the session
  wins over its file, because this runs again as each pose source registers.
* **A damaged file costs that wheel only** and is named once (rule 10).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from avialsync.core.wheel_file import read_wheels, write_removed, write_wheel
from avialsync.ui.controllers import calibration_controller as calibration
from avialsync.ui.controllers import rig_paths
from avialsync.ui.i18n import tr

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
    """Read the wheels kept beside whatever pose data is loaded now.

    What is already in the session wins over the file: this runs as each pose
    source registers, and a wheel edited since would otherwise be rolled back
    by its own older copy.
    """
    folder = rig_paths.pose3d_dir(window)
    if folder is None:
        return
    wheels, unreadable = read_wheels(folder)
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
