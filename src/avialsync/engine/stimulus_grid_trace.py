"""Bounded signal reads and the shared relative-time chart for grid movies."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

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


def _value_range(traces: Sequence[GridTrace], threshold: float) -> tuple[float, float, bool]:
    """Use one Y scale for every overlaid event, ignoring gaps and non-finite samples."""
    bounds = [
        np.concatenate((trace.low[valid], trace.high[valid]))
        for trace in traces
        if np.any(valid := (~trace.gaps & np.isfinite(trace.low) & np.isfinite(trace.high)))
    ]
    if not bounds:
        return threshold - 0.5, threshold + 0.5, False
    values = np.concatenate(bounds)
    minimum = min(float(values.min()), threshold)
    maximum = max(float(values.max()), threshold)
    if maximum == minimum:
        return minimum - 0.5, maximum + 0.5, True
    pad = (maximum - minimum) * 0.08
    return minimum - pad, maximum + pad, True


def _draw_envelopes(
    painter: QPainter,
    traces: Sequence[GridTrace],
    x_at: Callable[[float], int],
    y_at: Callable[[float], int],
) -> None:
    """Draw bounded min/max envelopes, breaking lines at gaps and bad samples."""
    for trace in traces:
        painter.setPen(QPen(QColor(94, 215, 229, 150), 2))
        previous: tuple[int, int] | None = None
        for time, low, high, gap in zip(
            trace.times, trace.low, trace.high, trace.gaps, strict=True
        ):
            if gap or not (np.isfinite(time) and np.isfinite(low) and np.isfinite(high)):
                previous = None
                continue
            x = x_at(float(time))
            mid = y_at(float((low + high) / 2))
            painter.drawLine(x, y_at(float(low)), x, y_at(float(high)))
            if previous is not None:
                painter.drawLine(previous[0], previous[1], x, mid)
            previous = (x, mid)


def draw_signal_trace(
    painter: QPainter,
    area: QRect,
    traces: Sequence[GridTrace],
    signal: GridSignal,
    before: float,
    after: float,
    relative_time: float,
    no_signal: str,
    current_label: str,
) -> None:
    """Overlay all event windows beneath the cameras on one relative-time axis."""
    left, top, width, height = area.x(), area.y(), area.width(), area.height()
    painter.fillRect(area, QColor("#1b282b"))
    painter.setFont(QFont("Arial", 9))
    painter.setPen(QColor("#f1f4f2"))
    painter.drawText(QRect(left, top - 24, width, 22), signal.label)
    painter.drawText(
        QRect(left, top - 24, width, 22),
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        current_label.format(time=relative_time),
    )
    minimum, maximum, has_samples = _value_range(traces, signal.threshold)

    def x_at(time: float) -> int:
        return left + round(width * (time + before) / (before + after))

    def y_at(value: float) -> int:
        return top + round((height - 1) * (maximum - value) / (maximum - minimum))

    painter.save()
    painter.setClipRect(area)
    painter.setPen(QPen(QColor("#9aaba7"), 1, Qt.PenStyle.DashLine))
    painter.drawLine(left, y_at(signal.threshold), left + width, y_at(signal.threshold))
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw_envelopes(painter, traces, x_at, y_at)
    painter.setPen(QPen(QColor("#ef665d"), 2))
    painter.drawLine(x_at(0.0), top, x_at(0.0), top + height)
    painter.setPen(QPen(QColor("#f1f4f2"), 2))
    painter.drawLine(x_at(relative_time), top, x_at(relative_time), top + height)
    painter.restore()
    if not has_samples and no_signal:
        painter.setPen(QColor("#c3d1cd"))
        painter.drawText(area, Qt.AlignmentFlag.AlignCenter, no_signal)
    _draw_relative_ticks(painter, left, top + height + 4, width, before, after)


def _draw_relative_ticks(
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
