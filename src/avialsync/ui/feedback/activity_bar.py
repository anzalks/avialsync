"""The status-bar activity area: what is running, how far, and how to stop it.

This replaces the modal ``QProgressDialog`` the import path used to raise
(D-091).  The work is unchanged — it was always on a worker — but the window
stays usable while it runs, which matters most for exactly the operation that
justified the modal: a 1 GB CSV import is allowed sixty seconds by the
performance budget, and sixty seconds of frozen application reads as a hang.

Update rate is capped at :data:`_MAX_UPDATE_HZ`, matching the presentation
limit the timeline observers already use (D-047).  Nothing here is ever driven
from the 60 Hz clock tick.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QWidget,
)

#: Nobody can read a changing percentage faster than this, and every extra
#: repaint is UI-thread time the worker's own progress signals compete for.
_MAX_UPDATE_HZ = 20.0
_MIN_INTERVAL_S = 1.0 / _MAX_UPDATE_HZ

#: Progress must be at least this far along before an estimate is shown. Early
#: on, the rate is dominated by start-up cost and the figure jumps around; a
#: number that swings between "2 minutes" and "8 seconds" is worse than none.
_ETA_MIN_FRACTION = 0.08

#: And it must have been running at least this long, for the same reason.
_ETA_MIN_ELAPSED_S = 1.5


def _format_duration(seconds: float) -> str:
    """Render a short, honest duration."""
    if seconds < 1:
        return "under a second"
    if seconds < 60:
        return f"{int(round(seconds))} s"
    minutes, secs = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes} min {secs:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


class ActivityBar(QWidget):
    """Current background work, with progress, an estimate, and cancel."""

    #: Emitted when the user asks to stop the running activity.
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._started_at = 0.0
        self._last_paint = 0.0
        self._fraction = 0.0
        self._cancellable = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(8)

        self._label = QLabel("")
        self._label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(False)
        self._bar.setFixedWidth(140)
        self._bar.setAccessibleName("Background task progress")

        self._eta = QLabel("")
        self._eta.setAccessibleName("Estimated time remaining")

        self._cancel = QPushButton("Cancel")
        self._cancel.setAccessibleName("Cancel the running background task")
        self._cancel.clicked.connect(self.cancel_requested)

        layout.addWidget(self._label)
        layout.addWidget(self._bar)
        layout.addWidget(self._eta)
        layout.addWidget(self._cancel)

        # Keeps the estimate honest while a quiet worker reports no progress:
        # a 1 GB import can legitimately go seconds between updates, and a
        # frozen elapsed time reads as a hang even when the bar is right.
        self._tick = QTimer(self)
        self._tick.setInterval(int(_MIN_INTERVAL_S * 1000))
        self._tick.timeout.connect(self._refresh_eta)

        self.setVisible(False)

    # ── lifecycle ────────────────────────────────────────────────────

    def begin(self, description: str, *, cancellable: bool = True) -> None:
        """Show the bar for a newly started activity."""
        self._started_at = time.monotonic()
        self._last_paint = 0.0
        self._fraction = 0.0
        self._cancellable = cancellable

        self._label.setText(description)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._eta.setText("")
        self._cancel.setVisible(cancellable)
        self.setVisible(True)
        self._tick.start()

    def set_progress(self, percent: float) -> None:
        """Report progress as a percentage, rate-limited to 20 Hz."""
        self._fraction = max(0.0, min(1.0, percent / 100.0))
        now = time.monotonic()
        if now - self._last_paint < _MIN_INTERVAL_S and percent < 100:
            return
        self._last_paint = now
        self._bar.setValue(int(round(self._fraction * 100)))
        self._refresh_eta()

    def set_indeterminate(self, description: str) -> None:
        """Show activity whose extent is unknown."""
        self.begin(description, cancellable=self._cancellable)
        self._bar.setRange(0, 0)

    def end(self) -> None:
        """Hide the bar; the outcome is reported by the notification strip."""
        self._tick.stop()
        self.setVisible(False)
        self._label.setText("")
        self._eta.setText("")

    # ── the estimate ─────────────────────────────────────────────────

    def _refresh_eta(self) -> None:
        elapsed = time.monotonic() - self._started_at
        if self._fraction <= _ETA_MIN_FRACTION or elapsed < _ETA_MIN_ELAPSED_S:
            # Deliberately blank rather than a guess: an estimate that swings
            # wildly in the first seconds teaches the user to ignore it.
            self._eta.setText(_format_duration(elapsed))
            return
        remaining = elapsed * (1.0 - self._fraction) / self._fraction
        self._eta.setText(f"{_format_duration(remaining)} left")

    # ── for tests and diagnostics ────────────────────────────────────

    @property
    def description(self) -> str:
        return self._label.text()

    @property
    def eta_text(self) -> str:
        return self._eta.text()

    @property
    def percent(self) -> int:
        return self._bar.value()
