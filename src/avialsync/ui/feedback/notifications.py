"""Outcomes reported without taking the window away from the user (D-091).

A finished export, a generated proxy, a failed import: things worth saying that
are not worth a modal.  Success dismisses itself, because the user asked for it
and already knows.  Failure stays until it is dismissed, because the one thing
worse than a modal error is an error that disappears before it is read.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from avialsync.ui.theme import follow_palette, status_color

#: How long a success stays up. Long enough to read six words, short enough not
#: to accumulate.
_SUCCESS_DISMISS_MS = 6000


class NotificationStrip(QWidget):
    """One line of non-modal feedback, with optional details and an action."""

    #: Emitted when the user asks to see the full text behind a failure.
    details_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._details = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._details_button = QPushButton("Show details")
        self._details_button.setAccessibleName("Show the full error text")
        self._details_button.clicked.connect(self._emit_details)
        self._details_button.setVisible(False)

        self._dismiss = QPushButton("Dismiss")
        self._dismiss.setAccessibleName("Dismiss this message")
        self._dismiss.clicked.connect(self.clear)

        layout.addWidget(self._label)
        layout.addWidget(self._details_button)
        layout.addWidget(self._dismiss)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear)

        self.setVisible(False)

    # ── posting ──────────────────────────────────────────────────────

    def show_success(self, message: str) -> None:
        """Report something that worked. Dismisses itself."""
        self._post(message, "ok", details="")
        self._timer.start(_SUCCESS_DISMISS_MS)

    def show_warning(self, message: str, details: str = "") -> None:
        """Report a partial result. Stays until dismissed."""
        self._post(message, "warning", details)

    def show_error(self, message: str, details: str = "") -> None:
        """Report a failure. Stays until dismissed.

        Sticky on purpose: a failure that fades before it is read is worse than
        one that interrupts, and this is the alternative to the modal it
        replaces, not to silence.
        """
        self._post(message, "error", details)

    def _post(self, message: str, severity: str, details: str) -> None:
        self._timer.stop()
        self._details = details
        self._label.setText(message)
        self._details_button.setVisible(bool(details))

        def _style(palette: QPalette) -> str:
            return f"color: {status_color(palette, severity).name()};"

        follow_palette(self._label, _style)
        self.setVisible(True)

    # ── clearing ─────────────────────────────────────────────────────

    def clear(self) -> None:
        self._timer.stop()
        self.setVisible(False)
        self._label.setText("")
        self._details = ""
        self._details_button.setVisible(False)

    def _emit_details(self) -> None:
        if self._details:
            self.details_requested.emit(self._details)

    # ── for tests ────────────────────────────────────────────────────

    @property
    def message(self) -> str:
        return self._label.text()

    @property
    def details(self) -> str:
        return self._details

    @property
    def is_sticky(self) -> bool:
        """Whether this message will stay until dismissed."""
        return self.isVisible() and not self._timer.isActive()
