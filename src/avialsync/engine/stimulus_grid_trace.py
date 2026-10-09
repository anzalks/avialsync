"""Bounded signal reads and the relative-time axis shared by a grid movie's sensor bands."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from avialsync.engine.export_worker import ReaderReference


@dataclass(frozen=True)
class GridSignal:
    """Selected stimulus channel and threshold for the shared export trace."""

    reference: ReaderReference
    label: str
    threshold: float


@dataclass(frozen=True)
class GridTrace:
    """One bounded, event-relative signal envelope read on the export worker."""

    times: np.ndarray
    low: np.ndarray
    high: np.ndarray
    gaps: np.ndarray


def read_signal_traces(
    signal: GridSignal,
    events: tuple[float, ...],
    before: float,
    after: float,
    width: int,
) -> tuple[GridTrace, ...]:
    """Query each selected window once, with no full-resolution arrays in the render loop."""
    reader = signal.reference.open()
    budget = min(1200, max(128, width))
    result: list[GridTrace] = []
    for event in events:
        times, low, high, gaps = reader.query(event - before, event + after, budget)
        result.append(
            GridTrace(
                np.asarray(times - event, dtype=np.float64).copy(),
                np.asarray(low, dtype=np.float64).copy(),
                np.asarray(high, dtype=np.float64).copy(),
                np.asarray(gaps, dtype=bool).copy(),
            )
        )
    return tuple(result)


def draw_relative_ticks(
    painter: QPainter, left: int, top: int, width: int, before: float, after: float
) -> None:
    """Put numeric relative-time ticks under the shared signal, including zero."""
    duration = before + after
    steps = (0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0)
    step = next((candidate for candidate in steps if candidate >= duration / 6), 120.0)
    painter.setPen(QPen(QColor("#879894"), 1))
    painter.drawLine(left, top, left + width, top)
    start = int(np.ceil(-before / step))
    end = int(np.floor(after / step))
    painter.setPen(QColor("#c3d1cd"))
    for multiple in range(start, end + 1):
        tick = multiple * step
        x = left + round(width * (tick + before) / duration)
        painter.drawLine(x, top, x, top + 6)
        label = "0 s" if multiple == 0 else f"{tick:+g} s"
        painter.drawText(QRect(x - 35, top + 8, 70, 19), Qt.AlignmentFlag.AlignCenter, label)
