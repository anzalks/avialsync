"""What is running and what just finished (D-091).

``JobManager`` has always known this — state, elapsed time, whether a worker
offers a cancel, whether it has gone quiet — and none of it was visible.  When
something takes longer than expected the only honest answer to "is it stuck?"
was the log.

History is bounded at :data:`_MAX_HISTORY`: this is a glance, not an audit
trail, and an unbounded list of finished jobs is a memory leak with a scrollbar.
"""

from __future__ import annotations

import dataclasses
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.i18n import tr

#: Finished jobs kept for reference.
_MAX_HISTORY = 20


@dataclasses.dataclass(frozen=True)
class FinishedJob:
    """One completed job, for the history rows."""

    label: str
    outcome: str
    duration_s: float
    finished_at: float


class JobsPanel(QGroupBox):
    """Running jobs above, recently finished below."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Background Tasks", parent)
        self._history: list[FinishedJob] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Task", "State", "Time"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setAccessibleName(tr("Background tasks, running and recently finished"))
        layout.addWidget(self._table)

    # ── updating ─────────────────────────────────────────────────────

    def record_finished(self, label: str, outcome: str, duration_s: float) -> None:
        """Note a job that ended, keeping the history bounded."""
        self._history.insert(0, FinishedJob(label, outcome, duration_s, time.monotonic()))
        del self._history[_MAX_HISTORY:]

    def refresh(self, running: list[tuple[str, str, float]]) -> None:
        """Redraw from *running* -- ``(label, state, elapsed_seconds)`` -- plus history.

        Callers rate-limit this; it is never driven from the clock tick.
        """
        rows = [(label, state, elapsed, False) for label, state, elapsed in running]
        rows += [(job.label, job.outcome, job.duration_s, True) for job in self._history]

        self._table.setRowCount(len(rows))
        for index, (label, state, seconds, done) in enumerate(rows):
            name = QTableWidgetItem(label)
            if done:
                # Finished rows read as history rather than competing with what
                # is happening now.
                name.setForeground(self.palette().placeholderText())
            self._table.setItem(index, 0, name)

            state_item = QTableWidgetItem(state)
            state_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(index, 1, state_item)

            time_item = QTableWidgetItem(f"{seconds:.1f} s")
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(index, 2, time_item)

    # ── for tests ────────────────────────────────────────────────────

    @property
    def row_count(self) -> int:
        return self._table.rowCount()

    @property
    def history(self) -> list[FinishedJob]:
        return list(self._history)
