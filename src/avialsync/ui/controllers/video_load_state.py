"""State for ordered, bounded video opening.

The job manager owns workers and threads. This state only tracks which probe
slots are occupied and which probe results are waiting for pane construction.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread


@dataclass
class VideoLoadState:
    """Queues and counters for one window's video-open pipeline."""

    pending: deque[tuple[Path, float, float, dict[str, Any] | None]] = field(default_factory=deque)
    active_probes: set[QThread] = field(default_factory=set)
    offsets: dict[str, float] = field(default_factory=dict)
    drifts: dict[str, float] = field(default_factory=dict)
    request_order: list[str] = field(default_factory=list)
    probed: dict[str, tuple[object, str]] = field(default_factory=dict)
    pane_initializing: object | None = None

    def clear_pending(self) -> None:
        """Forget results from the old session while active probes drain."""
        self.pending.clear()
        self.offsets.clear()
        self.drifts.clear()
        self.request_order.clear()
        self.probed.clear()
        self.pane_initializing = None
