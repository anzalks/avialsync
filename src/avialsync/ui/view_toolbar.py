"""The row under the video panes: what acts on the cameras and what is drawn on them.

Controls sit under the thing they act on. Flagging a frame, tracking
correction and hand-placed markers are all done on the video, and Snapshot, Fit All Videos
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

from avialsync.ui.action_button import ActionButton, ActionCheckBox
from avialsync.ui.design_tokens import ControlRole, apply_role
from avialsync.ui.i18n import tr

__all__ = ["ViewToolbar"]


class ViewToolbar(QWidget):
    """Flag Frame, Fix Tracker, Add 3D Marker | Snapshot, Fit All Videos, Fullscreen."""

    flag_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(tr("Video tools"))
        self.setAccessibleDescription(
            tr("Flag frames, correct tracking, place markers, and change how the videos are shown")
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(6)
        # Flag Frame marks the frame on screen: a video gesture, like the rest.
        self.flag_button = QPushButton(tr("Flag Frame"), self)
        self.flag_button.setToolTip(tr("Flag the current frame (M)"))
        # One look for the whole row: every video tool is a glyph (D-181).
        apply_role(self.flag_button, ControlRole.TOOL, "flag")
        self.flag_button.clicked.connect(self.flag_requested.emit)
        row.addWidget(self.flag_button)
        # Filled by the install_* methods once the window has built the
        # QActions; in the layout from the start so they do not shuffle the row.
        self.fix_tracker_button = ActionButton(self)
        self.add_marker_button = ActionButton(self)
        # Ticked, the panes draw what the model predicted instead of what the
        # accepted swaps make of it -- beside the other video controls, because
        # it changes what the video shows (D-141).
        self.original_tracker_box = ActionCheckBox(self)
        for button in (
            self.fix_tracker_button,
            self.add_marker_button,
            self.original_tracker_box,
        ):
            row.addWidget(button)
        row.addStretch(1)
        # Glyph buttons on the menu's own actions (D-174), which retires the
        # D-126 exception that kept these two as text buttons of their own.
        self.snapshot_button = ActionButton(self)
        self.fit_videos_button = ActionButton(self)
        self.fullscreen_button = ActionButton(self)
        for button in (self.snapshot_button, self.fit_videos_button, self.fullscreen_button):
            row.addWidget(button)

    def install_snapshot_action(self, action: QAction) -> None:
        """Show Snapshot as a glyph, driven by File → Export Snapshot…."""
        self.snapshot_button.set_action(action)
        self.snapshot_button.set_icon_only("snapshot")
        self.snapshot_button.setAccessibleDescription(tr("Export a figure of the current moment"))

    def install_fullscreen_action(self, action: QAction) -> None:
        """Show Fullscreen as a glyph, driven by View → Fullscreen."""
        self.fullscreen_button.set_action(action)
        self.fullscreen_button.set_icon_only("fullscreen")
        self.fullscreen_button.setAccessibleDescription(
            tr("Show the selected camera alone, or return to every camera")
        )

    def install_fix_tracker_action(self, action: QAction) -> None:
        """Show the Fix Tracker toggle, driven by the menu's own QAction."""
        self.fix_tracker_button.set_action(action)
        self.fix_tracker_button.set_icon_only("edit")
        self.fix_tracker_button.setAccessibleDescription(
            tr("Toggle dragging of tracked points in every video pane")
        )

    def install_original_tracker_action(self, action: QAction) -> None:
        """Show the Play original toggle, driven by the View menu's own QAction."""
        # No text of its own: the QAction's label is the one authority for what
        # this command is called, here and in the View menu (rule 15, D-092).
        self.original_tracker_box.set_action(action)
        self.original_tracker_box.setAccessibleDescription(
            tr("Draw the tracking the model predicted, ignoring accepted identity swaps")
        )

    def install_add_marker_action(self, action: QAction) -> None:
        """Show the Add 3D Marker toggle beside Fix Tracker, driven by its QAction."""
        self.add_marker_button.set_action(action)
        self.add_marker_button.set_icon_only("marker")
        self.add_marker_button.setAccessibleDescription(
            tr("Name a new marker, then click it once in each camera to place it in 3D")
        )

    def install_fit_videos_action(self, action: QAction) -> None:
        """Show Fit All Videos beside Fullscreen as a glyph, driven by its View QAction."""
        self.fit_videos_button.set_action(action)
        self.fit_videos_button.set_icon_only("fit")
        self.fit_videos_button.setAccessibleDescription(
            tr("Set every camera back to its whole frame, zoom 1.00x and no pan")
        )
