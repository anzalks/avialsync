"""A dedicated, scrollable inspector tab for wheel placement and review (D-117).

The Add Wheel button here is an :class:`~avialsync.ui.action_button.ActionButton`
on the Edit menu's action, like the one in the Data Streams header, and the
Wheel model / Wheel bars out of sight check boxes follow View -> Overlays' own
actions: each action is the one author of its label, tooltip, enablement and
checked state (rules 13 and 15).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from avialsync.ui.action_button import ActionButton, ActionCheckBox
from avialsync.ui.i18n import tr
from avialsync.ui.wheel_panel import WheelPanel


class WheelTab(QWidget):
    """Keep wheel controls reachable without crowding source metadata."""

    def __init__(self, panel: WheelPanel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(tr("Wheels"))
        self.setAccessibleDescription(tr("Add, label, and review wheels in this recording"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.verticalScrollBar().setAccessibleName(tr("Scroll wheel controls"))
        scroll.horizontalScrollBar().setAccessibleName(tr("Scroll wheel controls sideways"))
        content = QWidget(scroll)
        column = QVBoxLayout(content)
        column.setContentsMargins(5, 5, 5, 5)
        self.add_button = ActionButton(content)
        column.addWidget(self.add_button)
        # View -> Overlays' own wheel entries, repeated here (rules 13 and 15).
        self.show_wheel = ActionCheckBox(content)
        self.show_hidden_bars = ActionCheckBox(content)
        column.addWidget(self.show_wheel)
        column.addWidget(self.show_hidden_bars)
        note = QLabel(tr("Select Add Wheel to start, or review a wheel already placed."), content)
        note.setWordWrap(True)
        column.addWidget(note)
        column.addWidget(panel)
        column.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

    def install_add_action(self, action: QAction) -> None:
        """Bind the tab button to the same action as the menu and transport."""
        self.add_button.set_action(action)
        self.add_button.setAccessibleDescription(
            tr("Describe a wheel, then label its bar endpoints in the videos")
        )

    def install_overlay_actions(self, wheel: QAction, hidden_bars: QAction) -> None:
        """Show or hide the wheel from here, through View -> Overlays' own actions."""
        self.show_wheel.set_action(wheel)
        self.show_wheel.setAccessibleDescription(tr("Show or hide every wheel over the video"))
        self.show_hidden_bars.set_action(hidden_bars)
        self.show_hidden_bars.setAccessibleDescription(
            tr("Also draw, faintly, the bars a camera cannot see")
        )
