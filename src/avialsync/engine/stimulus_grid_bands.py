"""Sensor bands under a stimulus grid: one per sensor group, every event overlaid (D-210).

A band spans the whole width under the picture rows, on the shared
``-before .. +after`` axis: each stream of the group in its own colour, every
selected event drawn thin and translucent, the mean across events drawn bold on
top, a vertical line at the trigger and the moving cursor. Up to
:data:`OVERLAY_LIMIT` streams share one y-axis; more are stacked in lanes on
one shared amplitude scale, as a multichannel recording viewer shows them, so
32 electrodes do not collapse into one coloured blob. Streams of different
units (wheel rpm and a 0/1 stimulus TTL) are always stacked, each lane on its
own scale (D-211).

Colours come from the UI (the validated categorical palette), so this module
imports nothing from ``ui``; every stream is also named in the band, so colour
never carries meaning on its own (AGENTS rule 17).
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.stimulus_grid_trace import GridTrace, draw_relative_ticks

#: Above this many streams a band stacks them in lanes instead of overlaying.
OVERLAY_LIMIT = 4
#: Height of the label row above each band's plot area.
LABEL_HEIGHT = 29
#: Space under the last band for the relative-time ticks.
TICKS_HEIGHT = 56
#: Space between one band's plot and the next band's label.
BETWEEN = 10
#: A lone overlaid band keeps the height the single-signal band always had.
SINGLE_AREA = 145
OVERLAY_AREA = 110
LANE_HEIGHT = 16
MAX_STACKED_AREA = 400
#: Samples per stream and event; bounded so a long window never reads full resolution.
MAX_SAMPLES = 1200

_EVENT_ALPHA = 70
_BACKGROUND = QColor("#1b282b")
_TEXT = QColor("#f1f4f2")
_MUTED = QColor("#c3d1cd")
_TRIGGER = QColor("#ef665d")


@dataclass(frozen=True)
class GridStream:
    """One stream of a sensor group, and the colour it is drawn in."""

    reference: ReaderReference
    label: str
    color: tuple[int, int, int] = (86, 180, 233)
    unit: str = ""


@dataclass(frozen=True)
class GridBand:
    """A sensor group drawn as one band: its chosen streams, all events overlaid.

    *threshold*, when set, is drawn as a dashed line for the stream at
    *threshold_stream* -- the trigger channel's detection level. *layout* is
    ``"auto"``, ``"overlay"`` or ``"stacked"``.
    """

    label: str
    streams: tuple[GridStream, ...]
    threshold: float | None = None
    threshold_stream: int = 0
    layout: str = "auto"

    @property
    def mixed_units(self) -> bool:
        """Whether the streams measure different things, which no one axis can show."""
        return len({stream.unit for stream in self.streams}) > 1

    @property
    def stacked(self) -> bool:
        if self.layout == "stacked":
            return True
        return self.layout == "auto" and (len(self.streams) > OVERLAY_LIMIT or self.mixed_units)


def area_height(band: GridBand, single: bool = False) -> int:
    """Height of *band*'s plot area: lanes for stacked streams, fixed when overlaid."""
    if band.stacked:
        return min(max(OVERLAY_AREA, LANE_HEIGHT * len(band.streams)), MAX_STACKED_AREA)
    return SINGLE_AREA if single else OVERLAY_AREA


def stack_height(bands: Sequence[GridBand]) -> int:
    """Height of every band together, with the shared tick axis under the last."""
    single = len(bands) == 1
    plots = sum(LABEL_HEIGHT + area_height(band, single) for band in bands)
    return plots + BETWEEN * max(0, len(bands) - 1) + TICKS_HEIGHT


def band_areas(top: int, left: int, width: int, bands: Sequence[GridBand]) -> list[QRect]:
    """Each band's plot rectangle, from *top* down."""
    single = len(bands) == 1
    areas: list[QRect] = []
    y = top
    for band in bands:
        y += LABEL_HEIGHT
        height = area_height(band, single)
        areas.append(QRect(left, y, width, height))
        y += height + BETWEEN
    return areas


def read_band_traces(
    band: GridBand, events: Sequence[float], before: float, after: float, width: int
) -> tuple[tuple[GridTrace, ...], ...]:
    """Each stream's bounded envelope for each event, read once on the export worker."""
    budget = min(MAX_SAMPLES, max(128, width))
    streams: list[tuple[GridTrace, ...]] = []
    for stream in band.streams:
        reader = stream.reference.open()
        windows = []
        for event in events:
            times, low, high, gaps = reader.query(event - before, event + after, budget)
            windows.append(
                GridTrace(
                    np.asarray(times - event, dtype=np.float64).copy(),
                    np.asarray(low, dtype=np.float64).copy(),
                    np.asarray(high, dtype=np.float64).copy(),
                    np.asarray(gaps, dtype=bool).copy(),
                )
            )
        streams.append(tuple(windows))
    return tuple(streams)


def event_mean(
    traces: Sequence[GridTrace], before: float, after: float, points: int
) -> tuple[np.ndarray, np.ndarray]:
    """``(times, mean)`` across events on a common grid; NaN where no event has data.

    Each event is sampled at the grid by its nearest envelope midpoint, and
    only where a sample lies within one envelope step -- a gap, or a window
    the stream does not cover, contributes nothing rather than a held value.
    """
    grid = np.linspace(-before, after, max(2, points))
    rows = []
    for trace in traces:
        middle = (trace.low + trace.high) / 2.0
        valid = ~trace.gaps & np.isfinite(trace.times) & np.isfinite(middle)
        times, values = trace.times[valid], middle[valid]
        if len(times) == 0:
            continue
        step = float(np.median(np.diff(times))) if len(times) > 1 else (before + after)
        # Interpolated between neighbouring samples, but only where one lies
        # within a step: across a gap, or beyond coverage, there is no value.
        index = np.clip(np.searchsorted(times, grid), 0, len(times) - 1)
        earlier = np.clip(index - 1, 0, len(times) - 1)
        distance = np.minimum(np.abs(times[index] - grid), np.abs(times[earlier] - grid))
        sampled = np.interp(grid, times, values)
        rows.append(np.where(distance <= step, sampled, np.nan))
    if not rows:
        return grid, np.full(len(grid), np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)  # all-NaN columns stay NaN
        return grid, np.nanmean(np.vstack(rows), axis=0)


def _finite_range(traces: Sequence[GridTrace]) -> tuple[float, float] | None:
    values = [
        np.concatenate((trace.low[ok], trace.high[ok]))
        for trace in traces
        if np.any(ok := (~trace.gaps & np.isfinite(trace.low) & np.isfinite(trace.high)))
    ]
    if not values:
        return None
    joined = np.concatenate(values)
    return float(joined.min()), float(joined.max())


def _padded(low: float, high: float) -> tuple[float, float]:
    if high == low:
        return low - 0.5, high + 0.5
    pad = (high - low) * 0.08
    return low - pad, high + pad


def _linear(top: int, height: int, low: float, high: float) -> Callable[[float], int]:
    """Map *low*..*high* onto a plot area, high at the top."""

    def y_at(value: float) -> int:
        return top + round((height - 1) * (high - value) / (high - low))

    return y_at


def _lane(middle: float, centre: float, scale: float) -> Callable[[float], int]:
    """Map a stream onto its lane: its centre value on the lane's middle."""

    def y_at(value: float) -> int:
        return round(middle - (value - centre) * scale)

    return y_at


def _scales(
    band: GridBand, traces: Sequence[Sequence[GridTrace]], area: QRect
) -> list[Callable[[float], int]] | None:
    """One value-to-pixel map per stream: one shared axis, or lanes on one amplitude."""
    ranges = [_finite_range(stream) for stream in traces]
    known = [value for value in ranges if value is not None]
    if not known:
        return None
    top, height = area.y(), area.height()
    if not band.stacked:
        low = min(value[0] for value in known)
        high = max(value[1] for value in known)
        if band.threshold is not None:
            low, high = min(low, band.threshold), max(high, band.threshold)
        return [_linear(top, height, *_padded(low, high))] * len(traces)
    lane = height / len(traces)
    # One amplitude for every lane, so channels stay comparable, as in an ephys
    # viewer -- unless they measure different things (rpm beside a 0/1 TTL),
    # where a shared amplitude would flatten one; then each lane fits its own.
    span = max((value[1] - value[0] for value in known), default=1.0) or 1.0
    scales = []
    for index, value in enumerate(ranges):
        own = (value[1] - value[0]) if value is not None else 0.0
        lane_span = (own or 1.0) if band.mixed_units else span
        centre = 0.0 if value is None else sum(value) / 2.0
        scales.append(_lane(top + lane * (index + 0.5), centre, lane * 0.9 / lane_span))
    return scales


def _draw_events(
    painter: QPainter,
    traces: Sequence[GridTrace],
    color: QColor,
    x_at: Callable[[float], int],
    y_at: Callable[[float], int],
) -> None:
    """Every event thin and translucent, its envelope kept, broken at gaps."""
    faint = QColor(color)
    faint.setAlpha(_EVENT_ALPHA)
    painter.setPen(QPen(faint, 1))
    for trace in traces:
        previous: tuple[int, int] | None = None
        for time, low, high, gap in zip(
            trace.times, trace.low, trace.high, trace.gaps, strict=True
        ):
            if gap or not (np.isfinite(time) and np.isfinite(low) and np.isfinite(high)):
                previous = None
                continue
            x = x_at(float(time))
            middle = y_at(float((low + high) / 2))
            painter.drawLine(x, y_at(float(low)), x, y_at(float(high)))
            if previous is not None:
                painter.drawLine(previous[0], previous[1], x, middle)
            previous = (x, middle)


def _draw_mean(
    painter: QPainter,
    times: np.ndarray,
    mean: np.ndarray,
    color: QColor,
    x_at: Callable[[float], int],
    y_at: Callable[[float], int],
) -> None:
    painter.setPen(QPen(color, 2.5))
    previous: tuple[int, int] | None = None
    for time, value in zip(times, mean, strict=True):
        if not np.isfinite(value):
            previous = None
            continue
        point = (x_at(float(time)), y_at(float(value)))
        if previous is not None:
            painter.drawLine(previous[0], previous[1], point[0], point[1])
        previous = point


def draw_band_background(
    painter: QPainter,
    area: QRect,
    band: GridBand,
    traces: Sequence[Sequence[GridTrace]],
    before: float,
    after: float,
    title: str,
    no_signal: str,
    *,
    ticks: bool,
) -> None:
    """Draw one band's events, means, names and trigger line once for every frame."""
    left, top, width, height = area.x(), area.y(), area.width(), area.height()
    painter.fillRect(area, _BACKGROUND)
    painter.setFont(QFont("Arial", 9))
    _draw_names(painter, area, band, title)
    scales = _scales(band, traces, area)

    def x_at(time: float) -> int:
        return left + round(width * (time + before) / (before + after))

    painter.save()
    painter.setClipRect(area)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if scales is not None:
        if band.threshold is not None and 0 <= band.threshold_stream < len(scales):
            y = scales[band.threshold_stream](band.threshold)
            painter.setPen(QPen(QColor("#9aaba7"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(left, y, left + width, y)
        for stream, stream_traces, y_at in zip(band.streams, traces, scales, strict=True):
            color = QColor(*stream.color)
            _draw_events(painter, stream_traces, color, x_at, y_at)
            times, mean = event_mean(stream_traces, before, after, min(width, MAX_SAMPLES))
            _draw_mean(painter, times, mean, color, x_at, y_at)
    painter.setPen(QPen(_TRIGGER, 2))
    painter.drawLine(x_at(0.0), top, x_at(0.0), top + height)
    painter.restore()
    if scales is None and no_signal:
        painter.setPen(_MUTED)
        painter.drawText(area, Qt.AlignmentFlag.AlignCenter, no_signal)
    if ticks:
        draw_relative_ticks(painter, left, top + height + 4, width, before, after)


def _draw_names(painter: QPainter, area: QRect, band: GridBand, title: str) -> None:
    """The group's name and each stream's, in its colour, so colour is never alone."""
    left, top, width = area.x(), area.y(), area.width()
    painter.setPen(_TEXT)
    painter.drawText(QRect(left, top - 24, width // 2, 22), Qt.AlignmentFlag.AlignVCenter, title)
    metrics = painter.fontMetrics()
    if band.stacked:
        # In the margin to the band's left, beside each lane, never over a trace.
        lane = area.height() / max(1, len(band.streams))
        if lane >= metrics.height() * 0.8:
            for index, stream in enumerate(band.streams):
                painter.setPen(QColor(*stream.color))
                painter.drawText(
                    QRect(max(0, left - 100), round(top + lane * index), 94, round(lane)),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    stream.label,
                )
        return
    x = left + width // 2
    for stream in band.streams:
        painter.setPen(QColor(*stream.color))
        text = f"■ {stream.label}"
        painter.drawText(
            QRect(x, top - 24, metrics.horizontalAdvance(text) + 4, 22),
            Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        x += metrics.horizontalAdvance(text) + 14


def draw_band_cursor(
    painter: QPainter,
    area: QRect,
    before: float,
    after: float,
    relative_time: float,
    current_label: str | None = None,
) -> None:
    """Draw the moving cursor, and on the first band the relative-time readout."""
    left, top, width, height = area.x(), area.y(), area.width(), area.height()
    if current_label is not None:
        painter.setPen(_TEXT)
        painter.setFont(QFont("Arial", 9))
        painter.drawText(
            QRect(left, top - 24, width, 22),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            current_label.format(time=relative_time),
        )
    x = left + round(width * (relative_time + before) / (before + after))
    painter.save()
    painter.setClipRect(area)
    painter.setPen(QPen(_TEXT, 2))
    painter.drawLine(x, top, x, top + height)
    painter.restore()
