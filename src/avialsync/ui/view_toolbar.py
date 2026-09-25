"""The row under the video panes: what acts on the cameras and what is drawn on them.

Controls sit under the thing they act on. Flagging a frame, tracking
correction, hand-placed markers and wheels are all done on the video, and Snapshot, Fit All Videos
and Fullscreen change how the video is shown, so they live here -- not in the
Data Streams header, where they used to share one row with the lanes'
own controls.

Placement and toggles are :class:`~avialsync.ui.action_button.ActionButton`\\ s
on the Edit and View menus' own actions (rule 15); the window installs those
once it has built its menus.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from avialsync.ui.action_button import ActionButton
from avialsync.ui.i18n import tr

__all__ = ["ViewToolbar"]


class ViewToolbar(QWidget):
    """Flag Frame, Fix Tracker, Add 3D Marker, Add Wheel | Snapshot, Fit All Videos, Fullscreen."""

    flag_requested = Signal()
    snapshot_requested = Signal()
    fullscreen_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(tr("Video tools"))
        self.setAccessibleDescription(
            tr(
                "Flag frames, correct tracking, place markers and wheels, and change how the "
                "videos are shown"
            )
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(6)
        # Flag Frame marks the frame on screen: a video gesture, like the rest.
        self.flag_button = QPushButton(tr("Flag Frame"), self)
        self.flag_button.setToolTip(tr("Flag the current frame (M)"))
        self.flag_button.clicked.connect(self.flag_requested.emit)
        row.addWidget(self.flag_button)
        # Filled by the install_* methods once the window has built the
        # QActions; in the layout from the start so they do not shuffle the row.
        self.fix_tracker_button = ActionButton(self)
        self.add_marker_button = ActionButton(self)
        self.add_wheel_button = ActionButton(self)
        for button in (self.fix_tracker_button, self.add_marker_button, self.add_wheel_button):
            row.addWidget(button)
        row.addStretch(1)
        self.snapshot_button = QPushButton(tr("Snapshot"), self)
        self.snapshot_button.setToolTip(tr("Export snapshot (Ctrl+E)"))
        self.snapshot_button.clicked.connect(self.snapshot_requested.emit)
        row.addWidget(self.snapshot_button)
        self.fit_videos_button = ActionButton(self)
        row.addWidget(self.fit_videos_button)
        self.fullscreen_button = QPushButton(tr("Fullscreen Toggle"), self)
        self.fullscreen_button.setToolTip(tr("Toggle the active video pane fullscreen (F11)"))
        self.fullscreen_button.clicked.connect(self.fullscreen_requested.emit)
        row.addWidget(self.fullscreen_button)

    def install_fix_tracker_action(self, action: QAction) -> None:
        """Show the Fix Tracker toggle, driven by the menu's own QAction."""
        self.fix_tracker_button.set_action(action)
        self.fix_tracker_button.setAccessibleDescription(
            tr("Toggle dragging of tracked points in every video pane")
        )

    def install_add_marker_action(self, action: QAction) -> None:
        """Show the Add 3D Marker toggle beside Fix Tracker, driven by its QAction."""
        self.add_marker_button.set_action(action)
        self.add_marker_button.setAccessibleDescription(
            tr("Name a new marker, then click it once in each camera to place it in 3D")
        )

    def install_add_wheel_action(self, action: QAction) -> None:
        """Show Add Wheel beside Add 3D Marker, driven by the same menu QAction."""
        self.add_wheel_button.set_action(action)
        self.add_wheel_button.setAccessibleDescription(
            tr("Click both ends of two or three bars in at least two calibrated cameras")
        )

    def install_fit_videos_action(self, action: QAction) -> None:
        """Show Fit All Videos beside Fullscreen Toggle, driven by the View menu's QAction."""
        self.fit_videos_button.set_action(action)
        self.fit_videos_button.setAccessibleDescription(
            tr("Set every camera back to its whole frame, zoom 1.00x and no pan")
        )
