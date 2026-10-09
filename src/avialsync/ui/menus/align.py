"""Build the Align menu from live actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu, QMenuBar

from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

Register = Callable[[QAction, str], QAction]


def _add_microscope_trial_action(window: MainWindow, menu: QMenu, register: Register) -> QAction:
    """Add the configured AOL trial search to the Align menu."""
    from avialsync.ui.controllers import aol_microscope_controller

    action = menu.addAction(tr("Find microscope trial…"))
    action.setToolTip(tr("Find the matching AOL microscope trial by its recorded start time"))
    action.triggered.connect(lambda: aol_microscope_controller.find_trial(window))
    register(action, "Align")
    window._require(
        action,
        lambda: aol_microscope_controller.can_find_trial(window),
        tr("Load an AOL camera session and set its microscope folder in Preferences."),
    )
    return action


def build_align_menu(window: MainWindow, menu: QMenuBar, _reg: Register) -> QMenu:
    """Create this menu and connect its actions to the window."""
    # ── Align ─────────────────────────────────────────────────────
    # Promoted out of File. Alignment is not a file operation -- it is the
    # reason this application exists, and it sat between Open Sensor Data
    # and Save Session (WP-10).
    window._align_menu = menu.addMenu(tr("Align"))

    window._act_synchronize = window._align_menu.addAction(tr("Synchronize TTL / events…"))
    act = window._act_synchronize
    act.setToolTip(tr("Fit an offset from events both recordings share"))
    act.triggered.connect(window._open_sync_wizard)
    _reg(act, "Align")
    window.sidebar.install_align_action(act)
    window._require(
        act,
        window._has_alignment_evidence,
        tr(
            "Load a video with frame timestamps, and either a TTL-bearing sensor "
            "channel or declared trigger train, to have shared evidence to fit."
        ),
    )

    window._act_find_microscope_trial = _add_microscope_trial_action(
        window, window._align_menu, _reg
    )

    act = window._align_menu.addAction(tr("Open Trigger Evidence…"))
    act.setToolTip(tr("Load a TTL or strobe file and say what each of its lines is"))
    act.triggered.connect(window._open_trigger_evidence)
    _reg(act, "Align")

    window._align_menu.addSeparator()
    act = window._align_menu.addAction(tr("Nudge selected source earlier"))
    act.setShortcut(QKeySequence("Ctrl+Shift+Left"))
    act.triggered.connect(lambda: window._nudge_alignment(-1))
    _reg(act, "Align")
    window._require(
        act,
        lambda: bool(window.video_grid._paths),
        tr("Load a video before nudging its alignment."),
    )

    act = window._align_menu.addAction(tr("Nudge selected source later"))
    act.setShortcut(QKeySequence("Ctrl+Shift+Right"))
    act.triggered.connect(lambda: window._nudge_alignment(+1))
    _reg(act, "Align")
    window._require(
        act,
        lambda: bool(window.video_grid._paths),
        tr("Load a video before nudging its alignment."),
    )

    return window._align_menu
