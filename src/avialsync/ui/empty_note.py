"""What an empty page says: what fills it, and the action that does (D-176, R5).

A blank table reads as broken. Each inspector page that can be empty shows one
of these instead: a sentence naming what will appear and how, and -- when a
menu command fills it -- a button that *is* that command (rule 15).
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QPalette
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from avialsync.ui.action_button import ActionButton
from avialsync.ui.design_tokens import spacing

__all__ = ["WRAP_WIDTH_PX", "EmptyNote"]

#: The preferred width of wrapped guidance text: under the inspector's 280 px
#: default with room for its margins, so prose never sets a page's width.
WRAP_WIDTH_PX = 220


class EmptyNote(QWidget):
    """A wrapped, centred sentence and an optional action-backed button."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("empty_note")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(spacing("s"), spacing("l"), spacing("s"), spacing("l"))
        self.label = QLabel(text, self)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # A role, so the de-emphasis follows a theme switch (no stylesheet).
        self.label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.button = ActionButton(self)
        layout.addWidget(self.label)
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.setAccessibleName(text)

    def sizeHint(self) -> QSize:  # noqa: N802
        """Prefer a narrow page: the sentence wraps rather than widening it (R3)."""
        hint = super().sizeHint()
        hint.setWidth(min(hint.width(), max(self.minimumSizeHint().width(), WRAP_WIDTH_PX)))
        return hint

    def setText(self, text: str) -> None:  # noqa: N802 -- mirrors the QLabel it replaced
        self.label.setText(text)
        self.setAccessibleName(text)

    def text(self) -> str:
        return self.label.text()

    def set_action(self, action: QAction) -> None:
        """Offer *action*, the command that fills this page."""
        self.button.set_action(action)
