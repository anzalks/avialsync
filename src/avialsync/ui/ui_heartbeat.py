"""Detect and report stalls of the UI thread itself.

Background work being off-thread is only half the guarantee. The other half is
noticing when something *on* the UI thread blocks anyway — a large paint, a
synchronous read someone added, a pathological layout pass. Without a monitor
those show up as "the app felt laggy", which is unactionable.

This posts a timer to the UI thread and measures how late it actually fires.
Lateness is UI-thread blocking, by definition: the event loop could not get back
to the timer. AGENTS sets the budget at ≤8 ms typical, 30 ms hard ceiling for any
UI-thread callback.
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger(__name__)

#: Tick interval. Short enough to catch a stall, long enough to cost nothing.
_INTERVAL_MS = 100

#: AGENTS' hard ceiling for a UI-thread callback. Lateness beyond this means the
#: event loop was blocked, not merely busy.
STALL_THRESHOLD_MS = 30.0

#: Only surface a stall to the user above this, so ordinary scheduling jitter
#: does not produce a flood of warnings during normal interaction.
REPORT_THRESHOLD_MS = 250.0


class UiHeartbeat(QObject):
    """Measure UI-thread responsiveness and report stalls."""

    #: Emitted with the observed stall in milliseconds when the loop was blocked
    #: for longer than :data:`REPORT_THRESHOLD_MS`.
    stalled = Signal(float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._last_tick = time.monotonic()
        self._worst_ms = 0.0
        self._stall_count = 0

    def start(self) -> None:
        self._last_tick = time.monotonic()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    @property
    def worst_stall_ms(self) -> float:
        """The largest stall seen so far, for diagnostics."""
        return self._worst_ms

    @property
    def stall_count(self) -> int:
        return self._stall_count

    def reset(self) -> None:
        self._worst_ms = 0.0
        self._stall_count = 0
        self._last_tick = time.monotonic()

    def _tick(self) -> None:
        now = time.monotonic()
        lateness_ms = (now - self._last_tick) * 1000.0 - _INTERVAL_MS
        self._last_tick = now
        if lateness_ms <= STALL_THRESHOLD_MS:
            return

        self._stall_count += 1
        self._worst_ms = max(self._worst_ms, lateness_ms)
        if lateness_ms >= REPORT_THRESHOLD_MS:
            logger.warning("UI thread blocked for %.0f ms", lateness_ms)
            self.stalled.emit(lateness_ms)
