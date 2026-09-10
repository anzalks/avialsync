"""Outcomes reported without taking the window away from the user (D-091).

A finished export, a generated proxy, a failed import: things worth saying that
are not worth a modal.  Success dismisses itself, because the user asked for it
and already knows.  Failure stays until it is dismissed, because the one thing
worse than a modal error is an error that disappears before it is read.

Some messages are an *offer* rather than a report -- unsaved work found at
launch is the first -- so a message may carry one named action beside it.

**The strip shows one message at a time and queues the rest (D-107).**  It used
to hold exactly one, replacing it unconditionally on every post, which made the
docstring above false in two ways that mattered.  An unread failure was evicted
by whatever succeeded next.  And the recovery offer -- posted once at startup,
with no other entry point anywhere in the application -- was evicted by any
plugin error or autoload notice that happened to land behind it, taking the
only in-session route back to the user's unsaved work with it.

Two rules make that impossible rather than unlikely:

1. **A sticky message is never displaced.**  Warnings, errors, and offers stay
   until the user dismisses them; anything posted meanwhile waits its turn.
2. **A transient success never holds up a failure.**  A success is a report of
   something the user asked for and already knows, so an incoming sticky
   message takes the strip from it immediately rather than waiting out its
   timer.  Successes queue behind stickies, never the other way round.

The pending count is shown beside the message, so a queue is never a silent
one: the user can see that dismissing this reveals another.
"""

from __future__ import annotations

import dataclasses
from collections import deque
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from avialsync.ui.i18n import tr
from avialsync.ui.theme import follow_palette, status_color

#: How long a success stays up. Long enough to read six words, short enough not
#: to accumulate.
_SUCCESS_DISMISS_MS = 6000

#: Severity that dismisses itself. Everything else waits for the user.
_TRANSIENT = "ok"

#: How many unshown messages are kept. A burst larger than this means something
#: is looping, and the oldest are the least likely to still be worth reading --
#: but the bound exists so a runaway producer cannot grow the queue without
#: limit, not because 32 is a meaningful number of things to tell someone.
_MAX_QUEUED = 32


@dataclasses.dataclass(frozen=True)
class _Pending:
    """One message waiting for, or occupying, the strip."""

    message: str
    severity: str
    details: str
    action_label: str
    on_action: Callable[[], None] | None

    @property
    def is_transient(self) -> bool:
        return self.severity == _TRANSIENT

    def same_as(self, other: _Pending) -> bool:
        """Whether *other* says the same thing.

        Compared on text and severity alone: two identical failures arriving
        from two panes are one thing worth saying once, and an offer is never
        posted twice with different callbacks.
        """
        return self.message == other.message and self.severity == other.severity


class NotificationStrip(QWidget):
    """One line of non-modal feedback at a time, with the rest queued behind it."""

    #: Emitted when the user asks to see the full text behind a failure.
    details_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current: _Pending | None = None
        self._queue: deque[_Pending] = deque()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        #: How many more are waiting. Hidden when nothing is, so the ordinary
        #: single-message case looks exactly as it did.
        self._pending_label = QLabel("")
        self._pending_label.setVisible(False)

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
        layout.addWidget(self._pending_label)
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
        self._post(message, _TRANSIENT, details="")

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
        """Queue a message, and show it now if the strip is free to."""
        posted = _Pending(message, severity, details, action_label, on_action)
        if self._already_says(posted):
            return

        if self._current is None:
            self._show(posted)
        elif self._current.is_transient and not posted.is_transient:
            # Rule 2: a self-dismissing success does not make a failure wait.
            # The success is dropped rather than requeued -- it reports work
            # the user asked for and has already seen succeed.
            self._show(posted)
        elif len(self._queue) < _MAX_QUEUED:
            self._queue.append(posted)
        self._refresh_pending_count()

    def _already_says(self, posted: _Pending) -> bool:
        """Whether this message is showing or already waiting."""
        if self._current is not None and self._current.same_as(posted):
            return True
        return any(queued.same_as(posted) for queued in self._queue)

    def _show(self, pending: _Pending) -> None:
        """Put *pending* on the strip, replacing whatever occupies it."""
        self._timer.stop()
        self._current = pending
        self._label.setText(pending.message)
        self._details_button.setVisible(bool(pending.details))
        self.action_button.setText(pending.action_label)
        self.action_button.setAccessibleName(pending.action_label)
        self.action_button.setVisible(bool(pending.action_label))

        def _style(palette: QPalette) -> str:
            return f"color: {status_color(palette, pending.severity).name()};"

        follow_palette(self._label, _style)
        self.setVisible(True)
        self._refresh_pending_count()
        if pending.is_transient:
            self._timer.start(_SUCCESS_DISMISS_MS)

    def _refresh_pending_count(self) -> None:
        waiting = len(self._queue)
        self._pending_label.setVisible(waiting > 0)
        if waiting:
            text = tr("+{count} more").format(count=waiting)
            self._pending_label.setText(text)
            self._pending_label.setAccessibleName(
                tr("{count} more messages are waiting").format(count=waiting)
            )

    # ── clearing ─────────────────────────────────────────────────────

    def clear(self) -> None:
        """Dismiss the current message and show the next one waiting.

        Declining an offer is not the same as acting on it: this drops the
        callback and says nothing to whoever posted it, so the thing being
        offered stays where it is.
        """
        self._timer.stop()
        self._current = None
        if self._queue:
            self._show(self._queue.popleft())
            return
        self._hide()

    def clear_all(self) -> None:
        """Drop the current message and everything queued behind it."""
        self._queue.clear()
        self._timer.stop()
        self._current = None
        self._hide()

    def _hide(self) -> None:
        self.setVisible(False)
        self._label.setText("")
        self._details_button.setVisible(False)
        self.action_button.setText("")
        self.action_button.setVisible(False)
        self._pending_label.setVisible(False)

    def _emit_details(self) -> None:
        if self._current is not None and self._current.details:
            self.details_requested.emit(self._current.details)

    def _run_action(self) -> None:
        """Invoke the offer's callback, then take the message down.

        Read before clearing: ``clear`` drops the callback, so calling it first
        would make the button do nothing.
        """
        callback = self._current.on_action if self._current is not None else None
        self.clear()
        if callback is not None:
            callback()

    # ── for tests ────────────────────────────────────────────────────

    @property
    def message(self) -> str:
        return self._label.text()

    @property
    def details(self) -> str:
        return self._current.details if self._current is not None else ""

    @property
    def action_label(self) -> str:
        """The offered action's label, empty when the message offers none."""
        return self.action_button.text()

    @property
    def is_sticky(self) -> bool:
        """Whether this message will stay until dismissed."""
        return self.isVisible() and not self._timer.isActive()

    @property
    def pending_count(self) -> int:
        """How many messages are waiting behind the one on show."""
        return len(self._queue)
