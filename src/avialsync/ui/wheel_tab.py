"""Embedded review controls for wheel placement (D-117, D-154).

Wheel creation starts from the kind-sensitive Add button in Props. The Wheel
model / Wheel bars out of sight check boxes follow View -> Overlays' own
actions: each action is the one author of its label, tooltip, enablement and
checked state (rules 13 and 15).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from avialsync.ui.action_button import ActionCheckBox
from avialsync.ui.design_tokens import spacing
from avialsync.ui.i18n import tr
from avialsync.ui.wheel_panel import WheelPanel


class WheelTab(QWidget):
    """Keep wheel controls reachable without crowding source metadata."""

    def __init__(
        self, panel: WheelPanel, parent: QWidget | None = None, *, scrollable: bool = True
    ) -> None:
        super().__init__(parent)
        self.setAccessibleName(tr("Wheels"))
        self.setAccessibleDescription(tr("Add, label, and review wheels in this recording"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self) if scrollable else None
        if scroll is not None:
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.verticalScrollBar().setAccessibleName(tr("Scroll wheel controls"))
            scroll.horizontalScrollBar().setAccessibleName(tr("Scroll wheel controls sideways"))
        content = QWidget(scroll or self)
        column = QVBoxLayout(content)
        column.setContentsMargins(spacing("s"), spacing("s"), spacing("s"), spacing("s"))
        # View -> Overlays' own wheel entries, repeated here (rules 13 and 15).
        self.show_wheel = ActionCheckBox(content)
        self.show_hidden_bars = ActionCheckBox(content)
        column.addWidget(self.show_wheel)
        column.addWidget(self.show_hidden_bars)
        note = QLabel(tr("Review a wheel being placed or one already saved."), content)
        note.setWordWrap(True)
        column.addWidget(note)
        column.addWidget(panel)
        column.addStretch()
        if scroll is not None:
            scroll.setWidget(content)
            layout.addWidget(scroll)
        else:
            layout.addWidget(content)

    def install_overlay_actions(self, wheel: QAction, hidden_bars: QAction) -> None:
        """Show or hide the wheel from here, through View -> Overlays' own actions."""
        self.show_wheel.set_action(wheel)
        self.show_wheel.setAccessibleDescription(tr("Show or hide every wheel over the video"))
        self.show_hidden_bars.set_action(hidden_bars)
        self.show_hidden_bars.setAccessibleDescription(
            tr("Also draw, faintly, the bars a camera cannot see")
        )
