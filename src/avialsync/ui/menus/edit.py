"""Build the Edit menu from live actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu, QMenuBar

from avialsync.ui.controllers import custom_marker_controller, identity_view, wheel_controller
from avialsync.ui.i18n import tr
from avialsync.ui.undo_adapter import install_edit_menu

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

Register = Callable[[QAction, str], QAction]


def build_edit_menu(window: MainWindow, menu: QMenuBar, _reg: Register) -> None:
    """Create undo and editing actions from live commands."""
    window._edit_menu = menu.addMenu(tr("Edit"))
    window._undo_actions = install_edit_menu(window, window._edit_menu)
    _reg(window._undo_actions.undo_action, "Edit")
    _reg(window._undo_actions.redo_action, "Edit")
    _edit_tracking(window, window._edit_menu, _reg)
    _edit_geometry(window, window._edit_menu, _reg)


def _edit_tracking(window: MainWindow, edit_menu: QMenu, _reg: Register) -> None:
    """Add point and identity repair commands."""
    # Fix Tracker. One QAction drives both the menu entry and the button in
    # the Data Streams header, so the label, the shortcut, and the checked
    # state have a single author (D-092, architecture rule 15).
    window._edit_menu.addSeparator()
    window._act_fix_tracker = window._edit_menu.addAction(tr("Fix Tracker"))
    window._act_fix_tracker.setCheckable(True)
    window._act_fix_tracker.setShortcut(QKeySequence("Ctrl+Shift+T"))
    window._act_fix_tracker.setToolTip(
        tr("Drag a tracked point where it belongs, in every video pane")
    )
    window._act_fix_tracker.toggled.connect(window._toggle_point_edit_mode)
    _reg(window._act_fix_tracker, "Edit")
    window.view_toolbar.install_fix_tracker_action(window._act_fix_tracker)

    # Fix Identities: the other half of the same job. Fix Tracker moves a
    # coordinate the model got wrong; this fixes a *label* it got wrong,
    # which is one statement about every frame from there on (D-141).
    window._act_fix_identities = window._edit_menu.addAction(tr("Fix Identities…"))
    window._act_fix_identities.setToolTip(
        tr("Find and undo places where the tracker exchanged two labels")
    )
    window._act_fix_identities.triggered.connect(window._open_identity_panel)
    _reg(window._act_fix_identities, "Edit")
    window._require(
        window._act_fix_identities,
        lambda: bool(identity_view.pose_sources(window)),
        tr("Import 2D tracking before fixing which point is which."),
    )


def _edit_geometry(window: MainWindow, edit_menu: QMenu, _reg: Register) -> None:
    """Add 3D marker and wheel placement commands."""
    # Add 3D Marker: name a point, click it in every camera, triangulate.
    # Checked while a placement is in progress; unchecking cancels it. Same
    # one-QAction-drives-menu-and-button shape as Fix Tracker (rule 15).
    window._act_add_marker = window._edit_menu.addAction(tr("Add 3D Marker"))
    window._act_add_marker.setCheckable(True)
    window._act_add_marker.setToolTip(
        tr("Name a new marker and click it once in each camera to place it in 3D")
    )
    window._act_add_marker.toggled.connect(
        lambda checked: custom_marker_controller.toggled(window, checked)
    )
    window._require(
        window._act_add_marker,
        lambda: len(window.video_grid.pane_paths()) >= 2,
        tr("Load at least two camera videos to place a 3D marker"),
    )
    _reg(window._act_add_marker, "Edit")
    window.view_toolbar.install_add_marker_action(window._act_add_marker)

    # Add Wheel: declare a running wheel, click both ends of a few of its
    # bars, and the rest are generated and turned by the encoder (D-113).
    # Checked while one is being placed; unchecking cancels it. Its numbers
    # are edited in the Wheels inspector tab, and nowhere else.
    window._act_add_wheel = window._edit_menu.addAction(tr("Add Wheel…"))
    window._act_add_wheel.setCheckable(True)
    window._act_add_wheel.setToolTip(
        tr("Click both ends of a few neighbouring bars to place a running wheel in 3D")
    )
    window._act_add_wheel.toggled.connect(lambda checked: wheel_controller.toggled(window, checked))
    window._require(
        window._act_add_wheel,
        lambda: len(window.video_grid.pane_paths()) >= 2,
        tr("Load at least two camera videos to place a wheel"),
    )
    _reg(window._act_add_wheel, "Edit")
    window.view_toolbar.install_add_wheel_action(window._act_add_wheel)
    window.wheel_tab.install_add_action(window._act_add_wheel)

    window._act_add_prop = edit_menu.addAction(tr("Add Physical Prop…"))
    window._act_add_prop.setToolTip(tr("Open the physical props inspector"))
    window._act_add_prop.triggered.connect(window.props_app.show)
    _reg(window._act_add_prop, "Edit")
