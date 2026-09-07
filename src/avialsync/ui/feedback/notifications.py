"""Outcomes reported without taking the window away from the user (D-091).

A finished export, a generated proxy, a failed import: things worth saying that
are not worth a modal.  Success dismisses itself, because the user asked for it
and already knows.  Failure stays until it is dismissed, because the one thing
worse than a modal error is an error that disappears before it is read.

Some messages are an *offer* rather than a report -- unsaved work found at
launch is the first -- so a message may carry one named action beside it.  The
callback is held here and replaced whenever a new message is posted, so the
button cannot still be wired to the last offer when it shows the next one.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from avialsync.ui.i18n import tr
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
        self._action_callback: Callable[[], None] | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        #: The one named action a message may offer. Public because the thing
        #: that posts the offer is also what tests drive.
        self.action_button = QPushButton("")
        self.action_button.clicked.connect(self._run_action)
        self.action_button.setVisible(False)

        self._details_button = QPushButton("Show details")
        self._details_button.setAccessibleName(tr("Show the full error text"))
        self._details_button.clicked.connect(self._emit_details)
        self._details_button.setVisible(False)

        self._dismiss = QPushButton("Dismiss")
        self._dismiss.setAccessibleName(tr("Dismiss this message"))
        self._dismiss.clicked.connect(self.clear)

        layout.addWidget(self._label)
        layout.addWidget(self.action_button)
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

    def show_warning(
        self,
        message: str,
        details: str = "",
        *,
        action_label: str = "",
        on_action: Callable[[], None] | None = None,
    ) -> None:
        """Report a partial result, or offer one. Stays until dismissed.

        Pass *action_label* and *on_action* together to put one named button
        beside the message -- "Restore" for unsaved work found at launch. The
        action is an offer, never a gate: dismissing the message declines it
        and must leave whatever it was offering exactly where it was.
        """
        self._post(message, "warning", details, action_label, on_action)

    def show_error(self, message: str, details: str = "") -> None:
        """Report a failure. Stays until dismissed.

        Sticky on purpose: a failure that fades before it is read is worse than
        one that interrupts, and this is the alternative to the modal it
        replaces, not to silence.
        """
        self._post(message, "error", details)

    def _post(
        self,
        message: str,
        severity: str,
        details: str,
        action_label: str = "",
        on_action: Callable[[], None] | None = None,
    ) -> None:
        self._timer.stop()
        self._details = details
        self._label.setText(message)
        self._details_button.setVisible(bool(details))
        # Unconditional, so a message with no action of its own cannot inherit
        # the previous message's.
        self._action_callback = on_action if action_label else None
        self.action_button.setText(action_label)
        self.action_button.setAccessibleName(action_label)
        self.action_button.setVisible(bool(action_label))

        def _style(palette: QPalette) -> str:
            return f"color: {status_color(palette, severity).name()};"

        follow_palette(self._label, _style)
        self.setVisible(True)

    # ── clearing ─────────────────────────────────────────────────────

    def clear(self) -> None:
        """Dismiss the current message.

        Declining an offer is not the same as acting on it: this drops the
        callback and says nothing to whoever posted it, so the thing being
        offered stays where it is.
        """
        self._timer.stop()
        self.setVisible(False)
        self._label.setText("")
        self._details = ""
        self._details_button.setVisible(False)
        self._action_callback = None
        self.action_button.setText("")
        self.action_button.setVisible(False)

    def _emit_details(self) -> None:
        if self._details:
            self.details_requested.emit(self._details)

    def _run_action(self) -> None:
        """Invoke the offer's callback, then take the message down.

        Read before clearing: ``clear`` drops the callback, so calling it first
        would make the button do nothing.
        """
        callback = self._action_callback
        self.clear()
        if callback is not None:
            callback()

    # ── for tests ────────────────────────────────────────────────────

    @property
    def message(self) -> str:
        return self._label.text()

    @property
    def details(self) -> str:
        return self._details

    @property
    def action_label(self) -> str:
        """The offered action's label, empty when the message offers none."""
        return self.action_button.text()

    @property
    def is_sticky(self) -> bool:
        """Whether this message will stay until dismissed."""
        return self.isVisible() and not self._timer.isActive()
