"""Visible export entry points in the inspector, backed by live File actions."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from avialsync.ui.action_button import ActionButton
from avialsync.ui.design_tokens import spacing
from avialsync.ui.empty_note import EmptyNote
from avialsync.ui.i18n import tr


class ExportPanel(QWidget):
    """Show every export command without duplicating action labels or state."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setAccessibleName(tr("Export options"))
        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        # The tab already names the page; margins match its sibling pages.
        gap = spacing("s", self)
        layout.setContentsMargins(gap, gap, gap, gap)
        layout.setSpacing(gap)
        description = QLabel(tr("Choose what to write from the current session."), content)
        description.setWordWrap(True)
        layout.addWidget(description)
        self._buttons: dict[str, ActionButton] = {}
        for key in ("changes", "snapshot", "clip", "stimulus-grid", "data-slice"):
            button = ActionButton(content)
            button.setAccessibleDescription(tr("Open the export options for this output"))
            layout.addWidget(button)
            self._buttons[key] = button
        self.empty_note = EmptyNote(
            tr("Open video or sensor data to make exports available here."), content
        )
        layout.addWidget(self.empty_note)
        layout.addStretch(1)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def bind(self, key: str, action: QAction) -> None:
        """Make one visible button follow its File command."""
        self._buttons[key].set_action(action)
        action.changed.connect(self._refresh_empty_note)
        self._refresh_empty_note()

    def button(self, key: str) -> ActionButton:
        """Expose a button for tests and accessibility inspection."""
        return self._buttons[key]

    def _refresh_empty_note(self) -> None:
        available = any(
            button.action and button.action.isEnabled() for button in self._buttons.values()
        )
        self.empty_note.setVisible(not available)
