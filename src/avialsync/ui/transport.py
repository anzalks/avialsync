"""Playback transport controls."""

import bisect
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRegularExpression,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAccessible,
    QAccessibleValueChangeEvent,
    QColor,
    QFocusEvent,
    QFontDatabase,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygon,
    QRegularExpressionValidator,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.settings_schema import setting_for
from avialsync.core.trials import MIN_COLLAPSED_GAP_S, TimeWarp, common_gaps, stream_spans
from avialsync.ui.accessible_views import register_painted
from avialsync.ui.app_settings import app_settings
from avialsync.ui.design_tokens import DENSITY_ROW_HEIGHT, ControlRole, Density, apply_role, spacing
from avialsync.ui.feedback.status_line import StatusLine
from avialsync.ui.i18n import tr
from avialsync.ui.icons import set_svg_icon
from avialsync.ui.playback_rates import PLAYBACK_RATE_STEPS, rate_label
from avialsync.ui.preferences_dialog import read_setting
from avialsync.ui.scrub_bar import ScrubBar
from avialsync.ui.theme import (
    accent_hue,
    evidence_color,
    follow_palette,
    loop_pin_color,
    neutral_on_canvas,
    on_surface,
    separator_color,
    set_font_family,
    surface_color,
    system_accent,
)
from avialsync.ui.time_format import TimeDisplayMode, format_time

#: Surface left above and below every mark in a lane, so rows read as a rhythm
#: and a span never touches the one above it.
_LANE_INSET = 4

#: Coverage and range fills are spans, not slabs: a tint of the colour, rounded,
#: with the colour at full weight only at the two ends. What a coverage row says
#: is where it *ends*; a full-weight block across the width of the window said
#: that worst, and with the platform's real accent two of them were the loudest
#: thing on screen.
_SPAN_FILL_ALPHA = 110
_SPAN_CAP_WIDTH = 2
_SPAN_RADIUS = 3

#: A lane whose marks are glyphs rather than spans draws them at two pixels and
#: a little larger: a one-pixel outline at this size is legible on a screenshot
#: and not on a screen, which is the difference between a mark being present and
#: being findable.
_GLYPH_WIDTH = 2
_GLYPH_RADIUS = 5

#: How far the identity lane's ground is lifted off the strip behind it. Small:
#: enough that a diamond has something to be seen against, not so much that the
#: row reads as selected.
_GROUND_LIFT = 26


def _lane_ground(palette: QColor | object) -> QColor:
    """A slightly lighter bed for a lane whose marks are small glyphs.

    Derived from the surface rather than stated, so it lifts on a dark theme
    and settles on a light one instead of being a grey that only works in one.
    """
    base = surface_color(palette)  # type: ignore[arg-type]
    dark = base.lightnessF() < 0.5
    lift = _GROUND_LIFT if dark else -_GROUND_LIFT
    return QColor(
        max(0, min(255, base.red() + lift)),
        max(0, min(255, base.green() + lift)),
        max(0, min(255, base.blue() + lift)),
    )


#: A periodic train collapses to one tick per pixel column. Drawn full height at
#: full weight that is a striped slab which says only "there are many of these";
#: a shorter, lighter mark says the same thing without drowning the lane.
_RUG_ALPHA = 200


def _union(spans: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    """Overlapping stretches merged, in time order."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _duration_words(seconds: float) -> str:
    """A gap's length as a person says it: 33.4 s, 4 min 12 s, 2 h 5 min."""
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(round(seconds), 60)
    if minutes < 60:
        return f"{minutes} min {rest} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min"


def _paint_span(
    painter: QPainter, left: int, top: int, width: int, height: int, color: QColor
) -> None:
    """Fill one span as a tint of *color*, with *color* itself at both ends."""
    width = max(2, width)
    fill = QColor(color)
    fill.setAlpha(_SPAN_FILL_ALPHA)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill)
    painter.drawRoundedRect(left, top, width, height, _SPAN_RADIUS, _SPAN_RADIUS)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    cap = min(_SPAN_CAP_WIDTH, width)
    painter.fillRect(left, top, cap, height, color)
    painter.fillRect(left + width - cap, top, cap, height, color)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _rug_pen(color: QColor) -> QPen:
    """A light pen for dense event ticks."""
    faded = QColor(color)
    faded.setAlpha(_RUG_ALPHA)
    return QPen(faded, 1)


_EMPTY_TIMES = np.empty(0, dtype=np.float64)


@dataclass(frozen=True)
class _CoverageLane:
    """One coverage span: a single source's, or a whole group's merged.

    ``members`` is 1 for an ordinary source lane and the number of sources
    behind a grouped one, which is the only thing a reader cannot recover from
    the span itself once several files have been merged into it.
    """

    source_id: str
    start: float
    end: float
    kind: str
    members: int = 1
    #: The stretches with data, ``start`` to ``end`` less the time between a
    #: session's parts where the source recorded nothing (D-218).
    spans: tuple[tuple[float, float], ...] = ()

    def covers(self, time: float) -> bool:
        return any(a <= time <= b for a, b in self.spans or ((self.start, self.end),))


@dataclass(frozen=True)
class _EventLane:
    """Point events (accepted TTL matches, or imported data gaps)."""

    events: tuple[tuple[float, str], ...]


@dataclass(frozen=True)
class _AnnotationLane:
    """Point and range annotation markers."""

    markers: tuple[tuple[float, float | None, str], ...]


@dataclass(frozen=True)
class _SpanIndex:
    """Sorted start/end tables for logarithmic interval and handle queries."""

    order: np.ndarray
    starts: np.ndarray
    max_ends: np.ndarray
    range_end_order: np.ndarray

    def overlapping(self, q0: float, q1: float) -> np.ndarray:
        if len(self.starts) == 0 or q1 < q0:
            return np.empty(0, dtype=np.int64)
        hi = int(np.searchsorted(self.starts, q1, side="right"))
        if hi == 0:
            return np.empty(0, dtype=np.int64)
        lo = int(np.searchsorted(self.max_ends[:hi], q0, side="left"))
        return self.order[lo:hi]


def _build_segment_index(segments: tuple[tuple[float, float, str], ...]) -> _SpanIndex:
    n = len(segments)
    if n == 0:
        empty_i = np.empty(0, dtype=np.int64)
        return _SpanIndex(empty_i, _EMPTY_TIMES, _EMPTY_TIMES, empty_i)
    firsts = np.fromiter((min(a, b) for a, b, _ in segments), dtype=np.float64, count=n)
    lasts = np.fromiter((max(a, b) for a, b, _ in segments), dtype=np.float64, count=n)
    if n > 1 and bool(np.any(firsts[1:] < firsts[:-1])):
        order = np.argsort(firsts, kind="mergesort")
    else:
        order = np.arange(n, dtype=np.int64)
    s_starts = firsts[order]
    max_ends = np.maximum.accumulate(lasts[order])
    return _SpanIndex(order, s_starts, max_ends, np.empty(0, dtype=np.int64))


def _build_marker_index(markers: tuple[tuple[float, float | None, str], ...]) -> _SpanIndex:
    n = len(markers)
    if n == 0:
        empty_i = np.empty(0, dtype=np.int64)
        return _SpanIndex(empty_i, _EMPTY_TIMES, _EMPTY_TIMES, empty_i)
    starts = np.fromiter((s for s, _e, _c in markers), dtype=np.float64, count=n)
    ends = np.fromiter(
        (s if e is None else max(s, e) for s, e, _c in markers), dtype=np.float64, count=n
    )
    firsts = np.minimum(starts, ends)
    order = np.argsort(firsts, kind="mergesort")
    s_starts = firsts[order]
    max_ends = np.maximum.accumulate(ends[order])
    range_indices = np.asarray(
        [i for i, (_s, e, _c) in enumerate(markers) if e is not None], dtype=np.int64
    )
    if len(range_indices):
        range_ends = np.fromiter(
            (float(markers[int(i)][1]) for i in range_indices),  # type: ignore[arg-type]
            dtype=np.float64,
            count=len(range_indices),
        )
        range_end_order = range_indices[np.argsort(range_ends, kind="mergesort")]
    else:
        range_end_order = np.empty(0, dtype=np.int64)
    return _SpanIndex(order, s_starts, max_ends, range_end_order)


@dataclass(frozen=True)
class _SegmentLane:
    """Named stretches of the recording -- a joined experiment's trials."""

    segments: tuple[tuple[float, float, str], ...]


#: A lane is its display label, its kind tag, and a payload whose shape depends
#: on that tag. Typed records let the paint and hover branches unpack safely;
#: the payload used to be `object`, which nothing could destructure.
_LanePayload = "_CoverageLane | _EventLane | _AnnotationLane | _SegmentLane | None"


def _normalise_events(
    events: "list[float | tuple[float, str]] | tuple[float, ...]",
) -> tuple[tuple[float, str], ...]:
    """Return ``(time, detail)`` pairs sorted by time."""
    pairs = [
        (float(event[0]), event[1]) if isinstance(event, tuple) else (float(event), "")
        for event in events
    ]
    pairs.sort(key=lambda pair: pair[0])
    return tuple(pairs)


def _time_index(events: tuple[tuple[float, str], ...]) -> np.ndarray:
    """Return the sorted time column of *events* for binary search."""
    if not events:
        return _EMPTY_TIMES
    return np.fromiter((time for time, _ in events), dtype=np.float64, count=len(events))


class TimelineOverview(QWidget):
    """Paint named, conditional timeline-evidence lanes without owning time state."""

    seek_requested = Signal(float)
    viewport_seek_requested = Signal(float, bool)
    marker_move_requested = Signal(int, float, object)
    evidence_changed = Signal()
    _LABEL_WIDTH = 220
    _MIN_LANE_HEIGHT = 18

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._density = Density.COMPACT
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        # Tab only: a click seeks and must not take the arrow keys away from
        # frame stepping; reaching the lanes is a keyboard user's choice.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setToolTip(
            tr(
                "Data Streams. Click to seek. With focus: Up/Down choose a lane, "
                "Left/Right go to its previous/next event."
            )
        )
        self.setAccessibleName(tr("Data Streams lanes"))
        #: The lane the keyboard reads and steps along.
        self._focus_lane = 0
        register_painted(
            self, QAccessible.Role.Chart, self.accessible_value, self.accessible_detail
        )
        self.setAccessibleDescription(
            tr(
                "Named data, synchronization, gap, identity-swap, and annotation "
                "evidence on the master timeline."
            )
        )
        self._bounds = (0.0, 0.0)
        self._cursor = 0.0
        #: source id -> (start, end, kind, coverage group). Keyed per source
        #: even when grouped, so one member can still be replaced or removed
        #: without the rest of its group being rebuilt.
        self._coverage: dict[str, tuple[float, float, str, str]] = {}
        #: source id -> where between the session's parts it has no data.
        self._holes: dict[str, tuple[tuple[float, float], ...]] = {}
        #: Collapse the time no source has data in, for viewing (D-218).
        self._collapse_gaps = False
        self._warp = TimeWarp()
        self._raw_gap_events: tuple[tuple[float, str], ...] = ()
        self._raw_gap_times: np.ndarray = _EMPTY_TIMES
        #: Source id -> the session's name for it, for lane labels.
        self._labels: dict[str, str] = {}
        self._ttl_events: tuple[tuple[float, str], ...] = ()
        self._gap_events: tuple[tuple[float, str], ...] = ()
        self._message_events: tuple[tuple[float, str], ...] = ()
        self._identity_events: tuple[tuple[float, str], ...] = ()
        self._identity_candidates: tuple[tuple[float, str], ...] = ()
        # Sorted time index per event lane.  Paint and hover binary-search this
        # instead of scanning every event, so a 100k-event session costs the
        # same per frame as a 100-event one (P3.5 P1 hot path).
        self._event_times: dict[str, np.ndarray] = {
            "ttl": _EMPTY_TIMES,
            "gap": _EMPTY_TIMES,
            "message": _EMPTY_TIMES,
            "identity": _EMPTY_TIMES,
            "identity_candidate": _EMPTY_TIMES,
        }
        self._markers: tuple[tuple[float, float | None, str], ...] = ()
        self._markers_index_cache: tuple[int, _SpanIndex] = (0, _build_marker_index(()))
        self._segments: tuple[tuple[float, float, str], ...] = ()
        self._segments_index_cache: tuple[int, _SpanIndex] = (0, _build_segment_index(()))
        self._press_x = 0.0
        self._viewport_moved = False
        self._viewport_start = 0.0
        self._viewport_duration = 0.0
        self._viewport_phase = 0.0
        self._hover_time: float | None = None
        self._dragging_viewport = False
        self._viewport_drag_offset = 0.0
        self._dragging_marker: tuple[int, str, float, float | None] | None = None
        self._on_evidence_changed()

    def changeEvent(self, event: QEvent) -> None:
        """Repaint the lanes when the platform appearance changes.

        Lane colours are derived from the palette at paint time, so following a
        light/dark switch costs one repaint and no stored state. Qt already
        repaints widgets it styles itself; a widget that paints its own content
        has to ask, which is why a custom lane would otherwise keep the previous
        theme's colours until something else happened to invalidate it.
        """
        if event.type() == QEvent.Type.PaletteChange:
            self.update()
        elif event.type() == QEvent.Type.FontChange and hasattr(self, "_coverage"):
            self._on_evidence_changed()
        super().changeEvent(event)

    def set_density(self, density: Density) -> None:
        """Resize evidence rows using the shared density token."""
        self._density = density
        self._on_evidence_changed()

    def lane_height(self) -> int:
        """Return a single readable row at the current font and density."""
        return max(
            self._MIN_LANE_HEIGHT,
            self.fontMetrics().height() + DENSITY_ROW_HEIGHT[self._density],
        )

    def set_bounds(self, t0: float, t1: float) -> None:
        """Set the shared master-time range rendered by this overview."""
        self._bounds = (t0, t1)
        self.update()

    def set_cursor(self, t: float) -> None:
        """Move the overview playhead without recalculating any evidence."""
        self._cursor = t
        self.update()

    def set_hover_time(self, t: float | None) -> None:
        """Mirror the plot canvas hover hairline without moving the playhead."""
        if t == self._hover_time:
            return
        self._hover_time = t
        self.update()

    def set_viewport(self, start: float, duration: float, phase: float) -> None:
        """Render the one shared plot page without creating another time authority."""
        self._viewport_start = start
        self._viewport_duration = max(0.0, duration)
        self._viewport_phase = max(0.0, min(1.0, phase / duration)) if duration > 0 else 0.0
        self.update()

    def set_coverage(
        self,
        source_id: str,
        t0: float,
        t1: float,
        kind: str,
        group: str = "",
        holes: tuple[tuple[float, float], ...] | list[tuple[float, float]] = (),
    ) -> None:
        """Register one source coverage span, keyed for later replacement.

        A non-empty *group* merges this span into one lane with every other
        source naming the same group, instead of giving it a lane of its own.

        An empty span at the origin is how the window says a source is gone, so
        it drops the entry rather than storing a lane that draws nothing -- and,
        once groups exist, one that would otherwise drag its group's start back
        to zero and make the whole lane claim coverage nobody has.
        """
        if t0 == 0.0 and t1 == 0.0:
            self._coverage.pop(source_id, None)
            self._holes.pop(source_id, None)
        else:
            self._coverage[source_id] = (t0, t1, kind, group)
            self._holes[source_id] = tuple(holes)
        self._on_evidence_changed()

    def set_holes(self, holes: dict[str, list[tuple[float, float]]]) -> None:
        """Replace where each source has no data between parts, once the parts change."""
        self._holes = {source_id: tuple(holes.get(source_id, ())) for source_id in self._coverage}
        self._on_evidence_changed()

    def source_spans(self, source_id: str) -> list[tuple[float, float]]:
        """One source's stretches of data, in master seconds."""
        start, end, _kind, _group = self._coverage[source_id]
        return stream_spans((start, end), self._holes.get(source_id, ()))

    def set_collapse_gaps(self, collapse: bool) -> None:
        """Draw the time no source has data in as a break, or at its length (D-218)."""
        self._collapse_gaps = bool(collapse)
        self._on_evidence_changed()

    @property
    def warp(self) -> TimeWarp:
        """How the timeline is drawn: the collapsed gaps, none when not collapsing."""
        return self._warp

    def coverage_span(self) -> tuple[float, float] | None:
        """Return the master-time extent of every registered source, or None.

        This is the registry the master bounds are derived from, so it has to
        answer from what is loaded *now*: a span that grew while a source was
        misplaced has to come back when the source is put right, and one whose
        source has been removed must stop counting.
        """
        if not self._coverage:
            return None
        return (
            min(span[0] for span in self._coverage.values()),
            max(span[1] for span in self._coverage.values()),
        )

    def set_ttl_events(self, events: list[float | tuple[float, str]] | tuple[float, ...]) -> None:
        """Display accepted sync matches with inspectable provenance text."""
        self._ttl_events = _normalise_events(events)
        self._event_times["ttl"] = _time_index(self._ttl_events)
        self._on_evidence_changed()

    def set_gap_events(self, events: list[float | tuple[float, str]] | tuple[float, ...]) -> None:
        """Display imported data gaps as red ticks.

        A gap a source shows between a session's parts is that time, not a
        dropout: the source's lane shows it stopping, and it is left out here.
        """
        self._raw_gap_events = _normalise_events(events)
        self._raw_gap_times = _time_index(self._raw_gap_events)
        self._on_evidence_changed()

    def _filter_gap_events(self) -> None:
        if not self._raw_gap_events:
            if self._gap_events:
                self._gap_events = ()
                self._event_times["gap"] = _EMPTY_TIMES
            return
        shifted = sorted(
            (a - MIN_COLLAPSED_GAP_S, b)
            for holes in self._holes.values()
            for a, b in holes
            if b > a - MIN_COLLAPSED_GAP_S
        )
        if not shifted:
            events = self._raw_gap_events
            times = (
                self._raw_gap_times
                if len(self._raw_gap_times) == len(events)
                else _time_index(events)
            )
        else:
            merged: list[tuple[float, float]] = []
            for s, e in shifted:
                if merged and s <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], e))
                else:
                    merged.append((s, e))
            starts = np.fromiter((s for s, _ in merged), dtype=np.float64, count=len(merged))
            ends = np.fromiter((e for _, e in merged), dtype=np.float64, count=len(merged))
            raw_times = (
                self._raw_gap_times
                if len(self._raw_gap_times) == len(self._raw_gap_events)
                else _time_index(self._raw_gap_events)
            )
            self._raw_gap_times = raw_times
            # A gap is stamped at the last sample before it, just short of the hole.
            idx = np.searchsorted(starts, raw_times, side="right") - 1
            in_hole = (idx >= 0) & (raw_times < ends[np.maximum(idx, 0)])
            if not bool(np.any(in_hole)):
                events = self._raw_gap_events
                times = raw_times
            else:
                keep = np.flatnonzero(~in_hole)
                events = tuple(self._raw_gap_events[int(i)] for i in keep)
                times = raw_times[keep]
        if events != self._gap_events:
            self._gap_events = events
            self._event_times["gap"] = times

    def set_message_events(
        self, events: list[float | tuple[float, str]] | tuple[float, ...]
    ) -> None:
        """Display messages the sources recorded, with their text inspectable."""
        self._message_events = _normalise_events(events)
        self._event_times["message"] = _time_index(self._message_events)
        self._on_evidence_changed()

    def set_identity_events(
        self, events: list[float | tuple[float, str]] | tuple[float, ...]
    ) -> None:
        """Display accepted identity swaps, where a tracker lost track of who is who.

        Beside the gap lane deliberately: both answer "where is this recording
        not what it appears to be", and a reviewer looking for one is looking in
        the same place for the other.
        """
        self._identity_events = _normalise_events(events)
        self._event_times["identity"] = _time_index(self._identity_events)
        self._on_evidence_changed()

    def set_identity_candidates(
        self, events: list[float | tuple[float, str]] | tuple[float, ...]
    ) -> None:
        """Show proposals from the selected braid slice as hollow diamonds."""
        self._identity_candidates = _normalise_events(events)
        self._event_times["identity_candidate"] = _time_index(self._identity_candidates)
        self._on_evidence_changed()

    def _visible_event_x(self, kind: str, t0: float, t1: float) -> list[int]:
        """Return the distinct pixel columns of the events inside ``[t0, t1]``.

        Bounded by the widget width, not by the number of events: the slice is
        found by binary search and collapsed to unique columns before drawing.
        """
        times = self._event_times.get(kind, _EMPTY_TIMES)
        if len(times) == 0:
            return []
        first = int(np.searchsorted(times, t0, side="left"))
        last = int(np.searchsorted(times, t1, side="right"))
        if last <= first:
            return []
        columns = self._content_x_array(times[first:last])
        return [int(column) for column in np.unique(columns)]

    def _events_of(self, kind: str) -> tuple[tuple[float, str], ...]:
        """Return the event tuples behind one lane kind.

        A lookup rather than a conditional: the two-lane ternary this replaced
        answered "gap" for every kind that was not "ttl", so a third lane would
        have silently reported gap text under its own name.
        """
        return {
            "ttl": self._ttl_events,
            "gap": self._gap_events,
            "message": self._message_events,
            "identity": self._identity_events,
            "identity_candidate": self._identity_candidates,
        }.get(kind, ())

    def _nearest_event(self, kind: str, time: float, tolerance: float):
        """Binary-search the nearest event of *kind*, or None outside tolerance."""
        times = self._event_times.get(kind, _EMPTY_TIMES)
        if len(times) == 0:
            return None
        events = self._events_of(kind)
        index = int(np.searchsorted(times, time))
        candidates = [i for i in (index - 1, index) if 0 <= i < len(times)]
        if not candidates:
            return None
        best = min(candidates, key=lambda i: abs(float(times[i]) - time))
        if abs(float(times[best]) - time) > tolerance:
            return None
        return events[best]

    def _segment_index_for(self, segments: tuple[tuple[float, float, str], ...]) -> _SpanIndex:
        if self._segments_index_cache[0] != id(segments):
            self._segments_index_cache = (id(segments), _build_segment_index(segments))
        return self._segments_index_cache[1]

    def _marker_index_for(self, markers: tuple[tuple[float, float | None, str], ...]) -> _SpanIndex:
        if self._markers_index_cache[0] != id(markers):
            self._markers_index_cache = (id(markers), _build_marker_index(markers))
        return self._markers_index_cache[1]

    def set_segments(self, segments: list[tuple[float, float, str]]) -> None:
        """Show the recording's trials, ``(start, end, name)`` in master seconds."""
        self._segments = tuple(segments)
        self._segments_index_cache = (id(self._segments), _build_segment_index(self._segments))
        self._on_evidence_changed()

    def set_markers(self, markers: list[tuple[float, float | None, str]]) -> None:
        """Display point/range annotations in their stored colors."""
        self._markers = tuple(markers)
        self._markers_index_cache = (id(self._markers), _build_marker_index(self._markers))
        self._on_evidence_changed()

    def accessible_value(self) -> str:
        """The playhead, and what the focused lane holds there."""
        value = tr("Playhead at {time} s").format(time=f"{self._cursor:.3f}")
        lanes = self._lanes()
        if not lanes or not self.hasFocus():
            return value
        lane = min(self._focus_lane, len(lanes) - 1)
        detail = self._event_detail(
            float(self._content_x(self._cursor)), (lane + 0.5) * self.lane_height()
        )
        return f"{value}; {detail.replace(chr(10), ', ')}" if detail else value

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Choose a lane and step along it without a mouse."""
        from avialsync.ui.timeline_keys import lane_times, step_target

        lanes = self._lanes()
        key = event.key()
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and lanes:
            step = -1 if key == Qt.Key.Key_Up else 1
            self._focus_lane = min(max(0, self._focus_lane + step), len(lanes) - 1)
            self._announce()
            event.accept()
            return
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and lanes:
            lane = min(self._focus_lane, len(lanes) - 1)
            target = step_target(
                lane_times(lanes[lane][2]), self._cursor, 1 if key == Qt.Key.Key_Right else -1
            )
            if target is not None:
                self.seek_requested.emit(target)
                self._cursor = target
                self._announce()
            event.accept()
            return
        if key in (Qt.Key.Key_Home, Qt.Key.Key_End) and self._bounds[1] > self._bounds[0]:
            self.seek_requested.emit(self._bounds[0 if key == Qt.Key.Key_Home else 1])
            event.accept()
            return
        super().keyPressEvent(event)

    def event(self, event: QEvent) -> bool:
        """Keep the arrow keys for the lanes while they have focus.

        Frame step and seek own Left/Right as window shortcuts; without this
        a focused Data Streams strip could never receive them.
        """
        if event.type() == QEvent.Type.ShortcutOverride and isinstance(event, QKeyEvent):
            if event.modifiers() == Qt.KeyboardModifier.NoModifier and event.key() in (
                Qt.Key.Key_Up,
                Qt.Key.Key_Down,
                Qt.Key.Key_Left,
                Qt.Key.Key_Right,
                Qt.Key.Key_Home,
                Qt.Key.Key_End,
            ):
                event.accept()
                return True
        return super().event(event)

    def _announce(self) -> None:
        """Repaint the focus and tell assistive technology the value changed."""
        self.update()
        QAccessible.updateAccessibility(QAccessibleValueChangeEvent(self, self.accessible_value()))

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.update()

    def accessible_detail(self) -> str:
        """Each lane: a source's span, or how many events or markers it carries."""
        parts: list[str] = []
        for label, _kind, payload in self._lanes():
            if isinstance(payload, _CoverageLane):
                parts.append(f"{label}: {payload.start:.3f}–{payload.end:.3f} s")
            elif isinstance(payload, _EventLane):
                parts.append(tr("{lane}: {n} events").format(lane=label, n=len(payload.events)))
            elif isinstance(payload, _AnnotationLane):
                parts.append(tr("{lane}: {n} markers").format(lane=label, n=len(payload.markers)))
            elif isinstance(payload, _SegmentLane):
                parts.append(tr("{lane}: {n} trials").format(lane=label, n=len(payload.segments)))
        return "; ".join(parts) or tr("No sources are loaded.")

    def lane_labels(self) -> list[str]:
        """Return the currently populated lanes, in their rendered order.

        Read from the lanes themselves so the height and painted rows agree.
        """
        return [label for label, _, _ in self._lanes()]

    def _on_evidence_changed(self) -> None:
        """Refresh labels and ensure populated lanes have usable vertical space."""
        self._filter_gap_events()
        self._warp = TimeWarp(
            common_gaps([lane.spans for lane in self._coverage_payloads()])
            if self._collapse_gaps
            else ()
        )
        lane_count = max(1, len(self.lane_labels()))
        self.setFixedHeight(max(28, lane_count * self.lane_height()))
        self.evidence_changed.emit()
        self.update()

    @staticmethod
    def _coverage_label(source_id: str, kind: str, name: str = "") -> str:
        """The lane's kind and name: the session's *name* for it, else the file's."""
        kind_label = {"video": tr("Video"), "imaging": tr("Imaging")}.get(kind, tr("Data"))
        return f"{kind_label} · {name or Path(source_id).name}"

    def set_source_labels(self, labels: dict[str, str]) -> None:
        """Name lanes as the session named its items ("camera 2125010 — 17 trials")."""
        self._labels = dict(labels)
        self._on_evidence_changed()

    def _coverage_lanes(
        self,
    ) -> list[tuple[str, str, _CoverageLane | _EventLane | _AnnotationLane | None]]:
        """Return one lane per ungrouped source, plus one merged lane per group.

        A group takes the position of its first member, so grouping collapses
        lanes without reordering the ones around them, and its span is the union
        of its members'. That keeps the merged lane answering the only question
        a coverage lane exists to answer: when this data starts and stops.
        """
        lanes: list[tuple[str, str, _CoverageLane | _EventLane | _AnnotationLane | None]] = []
        positions: dict[tuple[str, str], int] = {}
        for source_id, (start, end, kind, group) in self._coverage.items():
            spans = tuple(self.source_spans(source_id))
            if not group:
                lanes.append(
                    (
                        self._coverage_label(source_id, kind, self._labels.get(source_id, "")),
                        "coverage",
                        _CoverageLane(source_id, start, end, kind, spans=spans),
                    )
                )
                continue
            position = positions.get((group, kind))
            if position is None:
                positions[(group, kind)] = len(lanes)
                lanes.append(
                    (
                        self._coverage_label(group, kind),
                        "coverage",
                        _CoverageLane(group, start, end, kind, spans=spans),
                    )
                )
                continue
            label, tag, merged = lanes[position]
            assert isinstance(merged, _CoverageLane)
            # The members' stretches, not their outer span: the time between
            # two trials' files is not covered by either (D-218).
            lanes[position] = (
                label,
                tag,
                _CoverageLane(
                    merged.source_id,
                    min(merged.start, start),
                    max(merged.end, end),
                    kind,
                    merged.members + 1,
                    spans=_union(merged.spans + spans),
                ),
            )
        return lanes

    def _lanes(
        self,
    ) -> list[tuple[str, str, _CoverageLane | _EventLane | _AnnotationLane | _SegmentLane | None]]:
        lanes: list[
            tuple[str, str, _CoverageLane | _EventLane | _AnnotationLane | _SegmentLane | None]
        ] = list(self._coverage_lanes())
        if self._ttl_events:
            lanes.append(("Sync / TTL", "ttl", _EventLane(self._ttl_events)))
        if self._gap_events:
            lanes.append(("Data gaps", "gap", _EventLane(self._gap_events)))
        if self._identity_events or self._identity_candidates:
            lanes.append(("Identity", "identity", _EventLane(self._identity_events)))
        if self._message_events:
            lanes.append(("Messages", "message", _EventLane(self._message_events)))
        if self._markers:
            lanes.append(("Annotations", "annotation", _AnnotationLane(self._markers)))
        if self._segments:
            lanes.append(("Trials", "segment", _SegmentLane(self._segments)))
        return lanes

    def _paint_segments(self, painter: QPainter, lane: _SegmentLane, top: int, height: int) -> None:
        """Alternate two shades so neighbouring trials read apart, each named if it fits."""
        t0, t1 = self._bounds
        if t1 <= t0 or not lane.segments:
            return
        vis = self._segment_index_for(lane.segments).overlapping(t0, t1)
        if len(vis) == 0:
            return
        starts = np.fromiter(
            (max(t0, min(lane.segments[int(i)][0], lane.segments[int(i)][1])) for i in vis),
            dtype=np.float64,
            count=len(vis),
        )
        ends = np.fromiter(
            (min(t1, max(lane.segments[int(i)][0], lane.segments[int(i)][1])) for i in vis),
            dtype=np.float64,
            count=len(vis),
        )
        lefts = self._content_x_array(starts, clip_gutter=True)
        rights = np.maximum(lefts, self._content_x_array(ends, clip_gutter=True))
        palette = self.palette()
        shades = (palette.color(palette.ColorRole.Mid), palette.color(palette.ColorRole.Midlight))
        sep_pen = separator_color(palette)
        text_pen = palette.color(palette.ColorRole.Text)
        fm = painter.fontMetrics()
        last_collapsed = (-1, -1)
        last_sep_x = -1
        for pos, orig_i in enumerate(vis):
            index = int(orig_i)
            left, right = int(lefts[pos]), int(rights[pos])
            span_w = max(1, right - left)
            shade_idx = index % 2
            if span_w <= 1:
                if (left, shade_idx) == last_collapsed:
                    continue
                last_collapsed = (left, shade_idx)
            painter.fillRect(left, top, span_w, height, shades[shade_idx])
            if left != last_sep_x:
                painter.setPen(sep_pen)
                painter.drawLine(left, top, left, top + height)
                last_sep_x = left
            width = right - left - 4
            name = lane.segments[index][2]
            if width >= 24 and name and width > fm.horizontalAdvance(name):
                painter.setPen(text_pen)
                painter.drawText(left + 2, top, width, height, Qt.AlignmentFlag.AlignVCenter, name)

    def _paint_annotations(
        self, painter: QPainter, payload: _AnnotationLane, band_top: int, band_height: int
    ) -> None:
        """Paint visible point and range annotations without overdrawing collapsed columns."""
        t0, t1 = self._bounds
        if t1 <= t0 or not payload.markers:
            return
        vis = self._marker_index_for(payload.markers).overlapping(t0, t1)
        if len(vis) == 0:
            return
        starts = np.fromiter(
            (
                max(
                    t0,
                    payload.markers[int(i)][0]
                    if payload.markers[int(i)][1] is None
                    else min(payload.markers[int(i)][0], float(payload.markers[int(i)][1])),  # type: ignore[arg-type]
                )
                for i in vis
            ),
            dtype=np.float64,
            count=len(vis),
        )
        ends = np.fromiter(
            (
                min(
                    t1,
                    payload.markers[int(i)][0]
                    if payload.markers[int(i)][1] is None
                    else max(payload.markers[int(i)][0], float(payload.markers[int(i)][1])),  # type: ignore[arg-type]
                )
                for i in vis
            ),
            dtype=np.float64,
            count=len(vis),
        )
        lefts = self._content_x_array(starts, clip_gutter=True)
        rights = np.maximum(lefts, self._content_x_array(ends, clip_gutter=True))
        colors: dict[str, QColor] = {}
        seen_points: set[tuple[int, str]] = set()
        seen_ranges: set[tuple[int, int, str]] = set()
        for pos, orig_i in enumerate(vis):
            _start, end, marker_color = payload.markers[int(orig_i)]
            left, right = int(lefts[pos]), int(rights[pos])
            qcol = colors.get(marker_color)
            if qcol is None:
                qcol = QColor(marker_color)
                colors[marker_color] = qcol
            if end is None:
                pt_key = (left, marker_color)
                if pt_key in seen_points:
                    continue
                seen_points.add(pt_key)
                painter.fillRect(left, band_top, 2, band_height, qcol)
            else:
                if right - left <= 2:
                    rng_key = (left, right, marker_color)
                    if rng_key in seen_ranges:
                        continue
                    seen_ranges.add(rng_key)
                _paint_span(painter, left, band_top, right - left, band_height, qcol)

    def _coverage_payloads(self) -> list[_CoverageLane]:
        return [
            payload
            for _l, _k, payload in self._coverage_lanes()
            if isinstance(payload, _CoverageLane)
        ]

    def _content_x(self, time: float) -> int:
        warp = self._warp
        t0, t1 = (warp.to_view(t) for t in self._bounds)
        width = max(1, self.width() - self._LABEL_WIDTH - 1)
        if t1 <= t0:
            return self._LABEL_WIDTH
        return self._LABEL_WIDTH + round((warp.to_view(time) - t0) / (t1 - t0) * width)

    def _content_x_array(self, times: np.ndarray, *, clip_gutter: bool = False) -> np.ndarray:
        if len(times) == 0:
            return np.empty(0, dtype=np.int64)
        warp = self._warp
        t0, t1 = warp.to_view(self._bounds[0]), warp.to_view(self._bounds[1])
        width = max(1, self.width() - self._LABEL_WIDTH - 1)
        if t1 <= t0:
            return np.full(len(times), self._LABEL_WIDTH, dtype=np.int64)
        cols = self._LABEL_WIDTH + np.rint((warp.to_view_array(times) - t0) / (t1 - t0) * width)
        out = cols.astype(np.int64)
        if clip_gutter:
            return np.clip(out, self._LABEL_WIDTH, max(self._LABEL_WIDTH, self.width() - 1))
        return out

    def _time_at_x(self, x: float) -> float:
        warp = self._warp
        t0, t1 = (warp.to_view(t) for t in self._bounds)
        width = max(1, self.width() - self._LABEL_WIDTH - 1)
        fraction = min(1.0, max(0.0, (x - self._LABEL_WIDTH) / width))
        return warp.to_master(t0 + fraction * (t1 - t0), snap=0.5 * (t1 - t0) / width)

    def _visible_span_x(self, start: float, end: float) -> tuple[int, int] | None:
        """Return the clipped timeline span, excluding the source-label gutter."""
        t0, t1 = self._bounds
        first, last = sorted((start, end))
        if t1 <= t0 or last < t0 or first > t1:
            return None
        left = max(self._LABEL_WIDTH, self._content_x(max(t0, first)))
        right = min(self.width() - 1, self._content_x(min(t1, last)))
        return left, max(left, right)

    def _annotation_hit_at(self, x: float, y: float) -> tuple[int, str, float, float | None] | None:
        """Return ``(marker_index, edge, t_start, t_end)`` when clicking an annotation handle."""
        lanes = self._lanes()
        if not lanes or not self._markers:
            return None
        lane_index = min(len(lanes) - 1, int(y // self.lane_height()))
        if lanes[lane_index][1] != "annotation":
            return None
        m_idx = self._marker_index_for(self._markers)
        candidates: set[int] = set()
        if len(m_idx.order):
            s_lo = bisect.bisect_left(
                m_idx.order,
                x - 5.0,
                key=lambda idx: self._content_x(self._markers[int(idx)][0]),
            )
            s_hi = bisect.bisect_right(
                m_idx.order,
                x + 5.0,
                lo=s_lo,
                key=lambda idx: self._content_x(self._markers[int(idx)][0]),
            )
            if s_hi > s_lo:
                candidates.add(int(np.min(m_idx.order[s_lo:s_hi])))
        if len(m_idx.range_end_order):
            e_lo = bisect.bisect_left(
                m_idx.range_end_order,
                x - 5.0,
                key=lambda idx: self._content_x(float(self._markers[int(idx)][1])),  # type: ignore[arg-type]
            )
            e_hi = bisect.bisect_right(
                m_idx.range_end_order,
                x + 5.0,
                lo=e_lo,
                key=lambda idx: self._content_x(float(self._markers[int(idx)][1])),  # type: ignore[arg-type]
            )
            if e_hi > e_lo:
                candidates.add(int(np.min(m_idx.range_end_order[e_lo:e_hi])))
        for idx in sorted(candidates):
            start, end, _color = self._markers[idx]
            sx = self._content_x(start)
            if end is None:
                if abs(x - sx) <= 5:
                    return idx, "point", start, None
            else:
                ex = self._content_x(end)
                if abs(x - sx) <= 5:
                    return idx, "start", start, end
                if abs(x - ex) <= 5:
                    return idx, "end", start, end
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            t0, t1 = self._bounds
            if event.position().x() >= self._LABEL_WIDTH and t1 > t0:
                hit = self._annotation_hit_at(event.position().x(), event.position().y())
                if hit is not None:
                    self._dragging_marker = hit
                    self._press_x = event.position().x()
                    event.accept()
                    return
                viewport = self._visible_span_x(
                    self._viewport_start, self._viewport_start + self._viewport_duration
                )
                if viewport is not None and viewport[0] <= event.position().x() <= viewport[1]:
                    self._dragging_viewport = True
                    self._viewport_drag_offset = event.position().x() - viewport[0]
                    self._press_x = event.position().x()
                    self._viewport_moved = False
                    event.accept()
                    return
                self.seek_requested.emit(self._time_at_x(event.position().x()))
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging_marker is not None:
            event.accept()
            return
        if self._dragging_viewport:
            # A press inside the page window is a click until it travels the
            # platform's drag distance; only then does it move the page.
            if abs(event.position().x() - self._press_x) >= QApplication.startDragDistance():
                self._viewport_moved = True
            if self._viewport_moved:
                self._move_viewport(event.position().x(), exact=False)
            event.accept()
            return
        x, y = event.position().x(), event.position().y()
        if x < self._LABEL_WIDTH:
            labels = self.lane_labels()
            index = int(y // self.lane_height())
            self.setToolTip(
                labels[index] if 0 <= index < len(labels) else tr("Data Streams. Click to seek.")
            )
        else:
            self.setToolTip(self._event_detail(x, y) or tr("Data Streams. Click to seek."))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._dragging_marker is not None and event.button() == Qt.MouseButton.LeftButton:
            idx, edge, orig_start, orig_end = self._dragging_marker
            self._dragging_marker = None
            new_t = self._time_at_x(event.position().x())
            if abs(event.position().x() - self._press_x) < 3:
                self.seek_requested.emit(orig_start)
            elif edge == "point":
                self.marker_move_requested.emit(idx, new_t, None)
            elif edge == "start" and orig_end is not None:
                self.marker_move_requested.emit(idx, min(new_t, orig_end), max(new_t, orig_end))
            elif edge == "end" and orig_end is not None:
                self.marker_move_requested.emit(idx, min(orig_start, new_t), max(orig_start, new_t))
            event.accept()
            return
        if self._dragging_viewport and event.button() == Qt.MouseButton.LeftButton:
            self._dragging_viewport = False
            if self._viewport_moved:
                self._move_viewport(event.position().x(), exact=True)
            else:
                # A click, not a drag: go where it landed, as anywhere else on
                # the strip. Treated as a drag, it moved the page by nothing.
                self.seek_requested.emit(self._time_at_x(event.position().x()))
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _move_viewport(self, x: float, *, exact: bool) -> None:
        """Move the page while preserving the playhead's fractional page position."""
        t0, t1 = self._bounds
        if t1 <= t0 or self._viewport_duration <= 0:
            return
        start = self._time_at_x(x - self._viewport_drag_offset)
        start = min(max(start, t0), max(t0, t1 - self._viewport_duration))
        self._viewport_start = start
        self._cursor = start + self._viewport_phase * self._viewport_duration
        self.update()
        self.viewport_seek_requested.emit(self._cursor, exact)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        palette = self.palette()
        painter.fillRect(self.rect(), surface_color(palette))
        t0, t1 = self._bounds
        lanes = self._lanes()
        if t1 <= t0:
            painter.setPen(palette.color(palette.ColorRole.PlaceholderText))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "No timeline evidence loaded"
            )
            return
        if not lanes:
            lanes = [("Navigator", "navigator", None)]

        lane_height = self.lane_height()
        accent = system_accent(palette)
        data_color = evidence_color(palette, "data")
        video_color = on_surface(palette, accent_hue(palette))
        label_width = min(self._LABEL_WIDTH, max(1, self.width() - 1))
        for lane_index, (label, lane_kind, payload) in enumerate(lanes):
            top = lane_index * lane_height
            bottom = min(self.height() - 1, top + lane_height - 1)
            painter.fillRect(
                0, top, label_width, lane_height, palette.color(palette.ColorRole.Base)
            )
            # Muted: the label says which row this is, the row says the data.
            # A label at full ink weight competes with the evidence beside it.
            painter.setPen(neutral_on_canvas(palette, 0.88))
            painter.drawText(
                8,
                top,
                label_width - 14,
                lane_height,
                Qt.AlignmentFlag.AlignVCenter,
                painter.fontMetrics().elidedText(
                    label, Qt.TextElideMode.ElideMiddle, max(1, label_width - 14)
                ),
            )
            painter.setPen(separator_color(palette))
            painter.drawLine(self._LABEL_WIDTH, bottom, self.width() - 1, bottom)
            # Every row's marks sit inside the same inset, so the rows read as
            # one rhythm and a span never touches the row above it.
            band_top = top + _LANE_INSET
            band_height = max(3, lane_height - 2 * _LANE_INSET)
            if isinstance(payload, _CoverageLane):
                # The accent's hue at a lightness solved against this surface,
                # like data coverage: the raw accent tinted to a span fill read
                # at about 1.4:1 on the lane in Dark.
                color = video_color if payload.kind == "video" else data_color
                for first, last in payload.spans or ((payload.start, payload.end),):
                    span = self._visible_span_x(first, last)
                    if span is not None:
                        left, right = span
                        _paint_span(painter, left, band_top, right - left, band_height, color)
            elif lane_kind == "ttl":
                # A rug, not a picket fence. A periodic train collapses to one
                # tick per pixel column, and at full height that is a striped
                # slab saying only "there are many" -- which is exactly what a
                # shorter, lighter mark says without shouting it.
                painter.setPen(_rug_pen(accent))
                foot = band_top + band_height
                for x in self._visible_event_x("ttl", t0, t1):
                    painter.drawLine(x, foot - max(3, band_height // 2), x, foot)
            elif lane_kind == "gap":
                painter.setPen(evidence_color(palette, "gap"))
                for x in self._visible_event_x("gap", t0, t1):
                    painter.drawLine(x, band_top, x, band_top + band_height)
            elif lane_kind == "identity":
                # This lane's marks are small glyphs rather than spans, and a
                # small glyph on the strip's own mid-grey is the one thing a
                # person is hunting for and the hardest thing to find. The lane
                # gets a lighter ground to sit on, taken from the palette so it
                # lifts on dark and settles on light.
                painter.fillRect(
                    label_width,
                    band_top,
                    max(0, self.width() - 1 - label_width),
                    band_height,
                    _lane_ground(palette),
                )
                # Two crossing strokes, not a tick: this lane says two labels
                # exchanged, and the glyph says it without relying on its
                # colour.
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setPen(QPen(evidence_color(palette, "identity"), _GLYPH_WIDTH))
                for x in self._visible_event_x("identity", t0, t1):
                    painter.drawLine(x - 3, band_top, x + 3, band_top + band_height)
                    painter.drawLine(x + 3, band_top, x - 3, band_top + band_height)
                # The same hue at the same strength. Fading a proposal was the
                # obvious way to say "not yet" and it said "not there" instead;
                # hollow against the accepted crossing's stroke carries it
                # without spending contrast.
                painter.setPen(QPen(evidence_color(palette, "identity"), _GLYPH_WIDTH))
                middle = (top + bottom) // 2
                for x in self._visible_event_x("identity_candidate", t0, t1):
                    painter.drawPolygon(
                        QPolygon(
                            [
                                QPoint(x, middle - _GLYPH_RADIUS),
                                QPoint(x + _GLYPH_RADIUS, middle),
                                QPoint(x, middle + _GLYPH_RADIUS),
                                QPoint(x - _GLYPH_RADIUS, middle),
                            ]
                        )
                    )
            elif lane_kind == "message":
                # Neither the accent nor the defect red: a note the experimenter
                # typed is neither a sync match nor an error, and colouring it
                # like either would misreport what it is. Derived from the live
                # accent, so that separation holds under any theme.
                painter.setPen(evidence_color(palette, "message"))
                for x in self._visible_event_x("message", t0, t1):
                    painter.drawLine(x, band_top, x, band_top + band_height)
            elif isinstance(payload, _SegmentLane):
                self._paint_segments(painter, payload, band_top, band_height)
            elif isinstance(payload, _AnnotationLane):
                self._paint_annotations(painter, payload, band_top, band_height)

        viewport = self._visible_span_x(
            self._viewport_start, self._viewport_start + self._viewport_duration
        )
        if viewport is not None and self._viewport_duration > 0:
            left, right = viewport
            view_color = QColor(palette.color(palette.ColorRole.Highlight))
            view_color.setAlpha(180)
            painter.setPen(view_color)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(left, 1, max(1, right - left), max(1, self.height() - 3))

        self._paint_breaks(painter)
        if self._hover_time is not None and t0 <= self._hover_time <= t1:
            hover_color = QColor(palette.color(palette.ColorRole.BrightText))
            hover_color.setAlpha(110)
            painter.setPen(QPen(hover_color, 1, Qt.PenStyle.DotLine))
            hx = min(self.width() - 1, max(self._LABEL_WIDTH, self._content_x(self._hover_time)))
            painter.drawLine(hx, 0, hx, self.height() - 1)
        painter.setPen(palette.color(palette.ColorRole.BrightText))
        cursor_x = min(self.width() - 1, max(self._LABEL_WIDTH, self._content_x(self._cursor)))
        painter.drawLine(cursor_x, 0, cursor_x, self.height() - 1)
        if self.hasFocus() and lanes:
            # Which lane the arrow keys read; without it, focus was invisible.
            lane = min(self._focus_lane, len(lanes) - 1)
            painter.setPen(QPen(system_accent(palette), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(1, lane * lane_height + 1, self.width() - 3, lane_height - 2)

    def _paint_breaks(self, painter: QPainter) -> None:
        """A collapsed gap is a double dashed line, so a break never reads as a seam (D-218)."""
        if not self._warp.gaps:
            return
        t0, t1 = self._bounds
        starts = self._warp._starts
        lo = int(np.searchsorted(starts, t0, side="left"))
        hi = int(np.searchsorted(starts, t1, side="right"))
        if hi <= lo:
            return
        pen = QPen(evidence_color(self.palette(), "gap"))
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        h = self.height() - 1
        for x in np.unique(self._content_x_array(starts[lo:hi])):
            px = int(x)
            painter.drawLine(px - 1, 0, px - 1, h)
            painter.drawLine(px + 1, 0, px + 1, h)

    def _break_detail(self, x: float) -> str:
        """The collapsed gap under *x*, in the words of its tooltip."""
        gaps = self._warp.gaps
        if not gaps:
            return ""
        lo = bisect.bisect_left(gaps, x - 3.0, key=lambda gap: self._content_x(gap[0]))
        hi = bisect.bisect_right(gaps, x + 3.0, lo=lo, key=lambda gap: self._content_x(gap[0]))
        if hi > lo:
            a, b = gaps[lo]
            if abs(self._content_x(a) - x) <= 3:
                return tr(
                    "Collapsed: {length} with no data, {start:.3f}–{end:.3f} s\n"
                    "Uncheck View → Collapse Gaps Without Data to show it at its length."
                ).format(length=_duration_words(b - a), start=a, end=b)
        return ""

    def _event_detail(self, x: float, y: float) -> str:
        """Return concise inspectable evidence nearest the pointer, if any."""
        t0, t1 = self._bounds
        if t1 <= t0:
            return ""
        collapsed = self._break_detail(x)
        if collapsed:
            return collapsed
        lanes = self._lanes()
        if not lanes:
            return f"Navigator\nMaster time: {self._time_at_x(x):.3f} s"
        lane_height = self.lane_height()
        lane_index = min(len(lanes) - 1, int(y // lane_height))
        label, kind, payload = lanes[lane_index]
        time = self._time_at_x(x)
        tolerance = (t1 - t0) * 8 / max(1, self.width() - self._LABEL_WIDTH)
        if isinstance(payload, _CoverageLane):
            if payload.covers(time):
                source = Path(payload.source_id).name
                if payload.members > 1:
                    source = f"{source} ({payload.members} sources)"
                return f"Coverage\nSource: {source}\nMaster time: {time:.3f} s"
        if kind in {"ttl", "gap", "message", "identity"}:
            if kind == "identity":
                candidate = self._nearest_event("identity_candidate", time, tolerance)
                accepted = self._nearest_event("identity", time, tolerance)
                if candidate is not None and (
                    accepted is None or abs(candidate[0] - time) < abs(accepted[0] - time)
                ):
                    return tr("Possible identity swap\nMaster time: {time:.3f} s\n{detail}").format(
                        time=candidate[0], detail=candidate[1]
                    )
            nearest = self._nearest_event(kind, time, tolerance)
            if nearest is not None:
                event_name = {
                    "ttl": "Accepted sync / TTL event",
                    "gap": "Imported data gap",
                    "message": "Recorded message",
                    "identity": "Accepted identity swap",
                }[kind]
                extra = f"\n{nearest[1]}" if nearest[1] else ""
                return f"{event_name}\nMaster time: {nearest[0]:.3f} s{extra}"
        if isinstance(payload, _SegmentLane):
            vis = self._segment_index_for(payload.segments).overlapping(time, time)
            for idx in np.sort(vis):
                first, last, name = payload.segments[int(idx)]
                if first <= time <= last:
                    return tr("Trial {name}\n{start:.3f}–{end:.3f} s").format(
                        name=name, start=first, end=last
                    )
        if isinstance(payload, _AnnotationLane):
            vis = self._marker_index_for(payload.markers).overlapping(
                time - tolerance, time + tolerance
            )
            for idx in np.sort(vis):
                start, end, _ = payload.markers[int(idx)]
                if start - tolerance <= time <= (end if end is not None else start) + tolerance:
                    return f"Annotation\nMaster time: {start:.3f} s"
        return f"{label}\nMaster time: {time:.3f} s"


class TimelineEvidence(QWidget):
    """Titled, collapsible Data Streams shell for named TimelineOverview lanes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = app_settings()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(spacing("xs"), 0, spacing("xs"), 0)
        header.setSpacing(spacing("s"))
        self.title = QLabel(tr("Data Streams"), self)
        self.title.setAccessibleName(tr("Data Streams title"))
        header.addWidget(self.title)
        self.collapse_button = QPushButton(tr("Hide"), self)
        self.collapse_button.setAccessibleName(tr("Hide Data Streams"))
        self.collapse_button.setToolTip(tr("Hide or show the Data Streams lanes"))
        self.collapse_button.clicked.connect(self.toggle_collapsed)
        header.addWidget(self.collapse_button)
        header.addStretch(1)
        self.overview = TimelineOverview(self)
        self.lane_scroll = QScrollArea(self)
        self.lane_scroll.setAccessibleName(tr("Data Streams scroll area"))
        self.lane_scroll.setAccessibleDescription(
            tr("Scroll vertically to inspect additional Data Streams lanes.")
        )
        self.lane_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.lane_scroll.setWidgetResizable(True)
        self.lane_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lane_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.lane_scroll.setWidget(self.overview)
        self._layout.addLayout(header)
        self._layout.addWidget(self.lane_scroll)
        self.overview.evidence_changed.connect(self._resize_lanes)
        self.reload_preferences()
        collapsed = bool(self._settings.value("timeline_evidence/collapsed", False, type=bool))
        self.set_collapsed(collapsed, persist=False)

    def reload_preferences(self) -> None:
        """Apply density and its row cap after a preference or font change."""
        density_setting = setting_for("interface/density")
        assert density_setting is not None
        raw_density = read_setting(density_setting)
        try:
            density = Density(raw_density)
        except ValueError:
            density = Density(density_setting.default)
        self._density = density
        cap_setting = setting_for(f"timeline/{density.value}_visible_lanes")
        assert cap_setting is not None
        self._visible_cap = max(1, min(32, read_setting(cap_setting)))
        self.overview.set_density(density)
        self._resize_lanes()

    def _resize_lanes(self) -> None:
        visible = min(self._visible_cap, max(1, len(self.overview.lane_labels())))
        self.lane_scroll.setFixedHeight(max(28, visible * self.overview.lane_height()))
        self._limit_shell_height()

    def _limit_shell_height(self) -> None:
        """Return unused splitter space to the video and plots."""
        self._layout.activate()
        self.setMaximumHeight(self._layout.sizeHint().height())

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self.overview.isHidden())

    def set_collapsed(self, collapsed: bool, *, persist: bool = True) -> None:
        self.overview.setVisible(not collapsed)
        self.lane_scroll.setVisible(not collapsed)
        self.collapse_button.setText(tr("Show") if collapsed else tr("Hide"))
        self.collapse_button.setAccessibleName(
            tr("Show Data Streams") if collapsed else tr("Hide Data Streams")
        )
        self._limit_shell_height()
        if persist:
            self._settings.setValue("timeline_evidence/collapsed", collapsed)


class _ABPin(QFrame):
    """Thin vertical marker overlaid on the slider for A/B loop points."""

    def __init__(self, which: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedWidth(2)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        follow_palette(
            self,
            lambda palette: (
                f"background-color: {loop_pin_color(palette, which).name()}; border: none;"
            ),
        )
        self.hide()

    def pin_to_slider(self, slider: QSlider, frac: float) -> None:
        if isinstance(slider, ScrubBar):
            groove = slider.track_rect()
            pin_height = max(12, groove.height() + 8)
            g_global = slider.mapToParent(groove.topLeft())
            x = g_global.x() + int(frac * groove.width()) - 1
            y = g_global.y() + (groove.height() - pin_height) // 2
            self.setGeometry(x, y, 2, pin_height)
        else:
            opt = QStyleOptionSlider()
            slider.initStyleOption(opt)
            groove = slider.style().subControlRect(
                QStyle.ComplexControl.CC_Slider,
                opt,
                QStyle.SubControl.SC_SliderGroove,
                slider,
            )
            g_global = slider.mapToParent(groove.topLeft())
            x = g_global.x() + int(frac * groove.width()) - 1
            y = g_global.y()
            self.setGeometry(x, y, 2, groove.height())
        self.raise_()
        self.show()


class Transport(QWidget):
    """Transport bar: play/pause, frame step, scrub slider,
    A/B loop, rate control, and inline time display / jump.

    New signals:
      jump_requested(float)— jump ±Ns (negative = back)

    Snapshot and Fullscreen moved to the ViewToolbar under the videos, and the
    Data Streams "Reset Zoom" -- a twin of the plots' own Reset -- was removed.
    """

    play_toggled = Signal(bool)
    seek_requested = Signal(float, bool)  # t, exact
    rate_changed = Signal(float)
    direction_changed = Signal(int)  # +1 forward, -1 reverse
    frame_step_requested = Signal(int)  # -1 or +1
    ab_loop_changed = Signal(object, object)  # t_in|None, t_out|None
    jump_requested = Signal(float)  # delta in seconds
    marker_move_requested = Signal(int, float, object)  # index, t_start, t_end|None

    # Ordered playback-rate steps (J/K/L model)
    _RATE_STEPS = PLAYBACK_RATE_STEPS
    _MIN_SINGLE_ROW_SLIDER_WIDTH = 120
    _MIN_COMPACT_WIDTH = 392

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        # Tab only: a click seeks and must not take the arrow keys away from
        # frame stepping; reaching the lanes is a keyboard user's choice.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._root_layout.setContentsMargins(
            spacing("s"), spacing("xs"), spacing("s"), spacing("s")
        )
        self._root_layout.setSpacing(spacing("xs"))
        self._timeline_layout = QHBoxLayout()
        self._timeline_layout.setSpacing(spacing("s"))
        self._controls_layout = QHBoxLayout()
        self._controls_layout.setSpacing(spacing("s"))
        self._compact_timeline = False
        self.evidence = TimelineEvidence(self)
        self.status_line = StatusLine(self)
        self.overview = self.evidence.overview
        self.overview.seek_requested.connect(lambda t: self.seek_requested.emit(t, True))
        self.overview.viewport_seek_requested.connect(
            lambda t, exact: self.seek_requested.emit(t, exact)
        )
        self.overview.marker_move_requested.connect(self.marker_move_requested)
        self._root_layout.addWidget(self.evidence)
        self._root_layout.addLayout(self._timeline_layout)

        # ── Timeline row: playhead controls, scrub bar, A/B, end time, rate ──
        mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        self._time_edit = QLineEdit("00:00:00.000")
        # Declare which characters a timecode can hold. The grammar is still
        # checked by `_parse_time_input` on Enter; this only says what may be
        # typed at all, which is what lets the window take back a letter
        # shortcut the field would have discarded anyway. "UTC" is in
        # the class because `format_time` writes that suffix into this field.
        self._time_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"[0-9:.+\- UTC]*"), self._time_edit)
        )
        self._time_edit.setMinimumWidth(110)
        self._time_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_font_family(self._time_edit, mono_font)
        self._time_edit.setToolTip(
            tr("Current time — click to edit.\nFormats: HH:MM:SS.fff, MM:SS, or seconds.")
        )
        self._time_edit.returnPressed.connect(self._on_jump)
        self._time_edit.editingFinished.connect(self._on_editing_done)
        self._time_editing = False
        self._time_edit.textEdited.connect(self._on_text_edited)
        self._timeline_layout.addWidget(self._time_edit)

        self.slider = ScrubBar(self)
        self.slider.setRange(0, 10000)
        self.slider.setMinimumWidth(80)
        self._last_t: float | None = None
        self.slider.setAccessibleName(tr("Master timeline scrubber"))
        self.slider.setToolTip(tr("Master timeline — drag to scrub; release for an exact seek"))
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self._timeline_layout.addWidget(self.slider, 1)

        self._end_time_label = QLabel("00:00:00.000", self)
        self._end_time_label.setMinimumWidth(110)
        self._end_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_font_family(self._end_time_label, mono_font)
        self._end_time_label.setToolTip(
            tr("End of the loaded master timeline; plot Time span is the width of the current page")
        )
        self._timeline_layout.addWidget(self._end_time_label)

        # ── Jump back 1 s ─────────────────────────────────────────────
        self._jump_back_btn = QPushButton(tr("Back 1 s"))
        self._jump_back_btn.setAccessibleName(tr("Jump back one second"))
        self._jump_back_btn.setToolTip(tr("Jump back 1 second (J or Shift+←)"))
        apply_role(self._jump_back_btn, ControlRole.TOOL, "jump-back")
        self._jump_back_btn.clicked.connect(lambda: self.jump_requested.emit(-1.0))

        # ── Frame step back ───────────────────────────────────────────
        self._step_back_btn = QPushButton(tr("Prev frame"))
        self._step_back_btn.setAccessibleName(tr("Step back one frame"))
        self._step_back_btn.setToolTip(tr("Step back 1 frame (← or ,)"))
        apply_role(self._step_back_btn, ControlRole.TOOL, "frame-back")
        self._step_back_btn.clicked.connect(lambda: self.frame_step_requested.emit(-1))

        # ── Play / Pause ──────────────────────────────────────────────
        self.play_btn = QPushButton(tr("Play"))
        self.play_btn.setCheckable(True)
        apply_role(self.play_btn, ControlRole.PRIMARY, "play")
        # Wide enough for either label, so toggling playback does not reflow
        # the row under the pointer.
        self.play_btn.setText(tr("Pause"))
        self.play_btn.setMinimumWidth(max(60, self.play_btn.sizeHint().width()))
        self.play_btn.setText(tr("Play"))
        self.play_btn.setAccessibleName(tr("Start playback"))
        self.play_btn.setToolTip(tr("Play / Pause (Space)"))
        self.play_btn.clicked.connect(self._on_play_clicked)

        # ── Frame step forward ────────────────────────────────────────
        self._step_fwd_btn = QPushButton(tr("Next frame"))
        self._step_fwd_btn.setAccessibleName(tr("Step forward one frame"))
        self._step_fwd_btn.setToolTip(tr("Step forward 1 frame (→ or .)"))
        apply_role(self._step_fwd_btn, ControlRole.TOOL, "frame-forward")
        self._step_fwd_btn.clicked.connect(lambda: self.frame_step_requested.emit(1))

        # ── Jump forward 1 s ──────────────────────────────────────────
        self._jump_fwd_btn = QPushButton(tr("Forward 1 s"))
        self._jump_fwd_btn.setAccessibleName(tr("Jump forward one second"))
        self._jump_fwd_btn.setToolTip(tr("Jump forward 1 second (Shift+→)"))
        apply_role(self._jump_fwd_btn, ControlRole.TOOL, "jump-forward")
        self._jump_fwd_btn.clicked.connect(lambda: self.jump_requested.emit(1.0))

        # ── A/B loop buttons (checkable) ────────────────────
        self._ab_in_btn = QPushButton(tr("Set In"))
        self._ab_in_btn.setCheckable(True)
        self._ab_in_btn.setAccessibleName(tr("Set loop in-point"))
        self._ab_in_btn.setToolTip(tr("Set the loop start here (I)"))
        apply_role(self._ab_in_btn, ControlRole.TOOL, "loop-in")
        self._ab_in_btn.clicked.connect(self._on_ab_in_clicked)

        self._ab_out_btn = QPushButton(tr("Set Out"))
        self._ab_out_btn.setCheckable(True)
        self._ab_out_btn.setAccessibleName(tr("Set loop out-point"))
        self._ab_out_btn.setToolTip(tr("Set the loop end here (O)"))
        apply_role(self._ab_out_btn, ControlRole.TOOL, "loop-out")
        self._ab_out_btn.clicked.connect(self._on_ab_out_clicked)

        self._ab_clear_btn = QPushButton(tr("Clear Loop"))
        self._ab_clear_btn.setAccessibleName(tr("Clear loop points"))
        self._ab_clear_btn.setToolTip(tr("Clear A/B loop"))
        apply_role(self._ab_clear_btn, ControlRole.TOOL, "loop-clear")
        self._ab_clear_btn.clicked.connect(self._on_ab_clear)

        # ── Rate combo (0.01× – 10×) ──────────────────────────────────
        self.rate_combo = QComboBox()
        self.rate_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for r in self._RATE_STEPS:
            self.rate_combo.addItem(rate_label(r), r)
        self.rate_combo.setCurrentText("1.0x")
        self.rate_combo.setToolTip(tr("Playback rate (L = step up, K = pause)"))
        self.rate_combo.currentIndexChanged.connect(self._on_rate_changed)
        self._playhead_buttons = (
            self._jump_back_btn,
            self._step_back_btn,
            self.play_btn,
            self._step_fwd_btn,
            self._jump_fwd_btn,
        )
        self._loop_rate_controls = (
            self._ab_in_btn,
            self._ab_out_btn,
            self._ab_clear_btn,
            self.rate_combo,
        )
        for index, button in enumerate(self._playhead_buttons):
            self._timeline_layout.insertWidget(index, button)
        for control in self._loop_rate_controls:
            self._timeline_layout.addWidget(control)

        self._bounds = (0.0, 0.0)
        self._direction = 1
        self._is_scrubbing = False
        self._ab_in_t: float | None = None
        self._ab_out_t: float | None = None
        self._time_mode = TimeDisplayMode.RELATIVE
        self._t_epoch = 0.0
        self.overview.evidence_changed.connect(self._sync_scrub_track)
        self._sync_scrub_track()

        # Overlay pins for A/B markers
        self._pin_in = _ABPin("in", self)
        self._pin_out = _ABPin("out", self)

        # Keep normal Tab traversal. Space itself is arbitrated below so controls
        # do not steal the window-scoped play/pause command.
        for widget in self.findChildren(QWidget):
            if isinstance(widget, (QPushButton, QComboBox, QSlider)):
                widget.setFocusPolicy(Qt.FocusPolicy.TabFocus)
                widget.installEventFilter(self)

    # ── Public API ────────────────────────────────────────────────────

    def ab_in(self) -> None:
        """Set the A/B loop in-point at the current slider position (public)."""
        self._on_ab_in()

    def detach_data_streams(self) -> TimelineEvidence:
        """Detach Data Streams so the main workspace splitter can own its height."""
        index = self._root_layout.indexOf(self.evidence)
        if index < 0:
            raise RuntimeError("Data Streams is already managed outside Transport")
        self._root_layout.takeAt(index)
        self.evidence.setParent(None)
        return self.evidence

    def ab_out(self) -> None:
        """Set the A/B loop out-point at the current slider position (public)."""
        self._on_ab_out()

    def ab_range(self) -> tuple[float, float] | None:
        """Return ``(start, end)`` when both A and B loop pins are set."""
        if self._ab_in_t is None or self._ab_out_t is None:
            return None
        return min(self._ab_in_t, self._ab_out_t), max(self._ab_in_t, self._ab_out_t)

    @property
    def direction(self) -> int:
        """Current shuttle direction (``+1`` forward, ``-1`` reverse)."""
        return self._direction

    def set_direction(self, direction: int) -> None:
        """Set playback direction without resetting speed."""
        next_dir = -1 if direction < 0 else 1
        if next_dir != self._direction:
            self._direction = next_dir
            self.direction_changed.emit(self._direction)
        self._update_shuttle_tooltip()

    def shuttle_forward(self) -> None:
        """Start forward playback at 1x, or step forward speed up (L key)."""
        if not self.play_btn.isChecked() or self._direction < 0:
            self.set_direction(1)
            idx_1x = self.rate_combo.findData(1.0)
            if idx_1x >= 0:
                self.rate_combo.setCurrentIndex(idx_1x)
            self.set_playing(True)
            self.play_toggled.emit(True)
            return
        self.step_rate_up()

    def shuttle_reverse(self) -> None:
        """Start reverse playback at -1x, or step reverse speed up (J key)."""
        if not self.play_btn.isChecked() or self._direction > 0:
            self.set_direction(-1)
            idx_1x = self.rate_combo.findData(1.0)
            if idx_1x >= 0:
                self.rate_combo.setCurrentIndex(idx_1x)
            self.set_playing(True)
            self.play_toggled.emit(True)
            return
        self.step_rate_up()

    def shuttle_pause(self) -> None:
        """Pause unconditionally and reset shuttle direction to forward (K key)."""
        self.set_direction(1)
        self.set_playing(False)
        self.play_toggled.emit(False)

    def reset_transport_state(self) -> None:
        """Clear A/B loop pins and reset shuttle direction and playback rate."""
        self._on_ab_clear()
        self.set_direction(1)
        idx = self.rate_combo.findData(1.0)
        if idx >= 0:
            self.rate_combo.setCurrentIndex(idx)

    def _update_shuttle_tooltip(self) -> None:
        if self._direction < 0 and self.play_btn.isChecked():
            self.play_btn.setToolTip(tr("Playing in reverse — press K or Space to pause"))
        else:
            self.play_btn.setToolTip(tr("Play / Pause (Space)"))

    def set_ab_region(self, start: float, end: float) -> None:
        """Show a review span using the same A/B pins as the transport buttons."""
        low, high = self._bounds
        self._ab_in_t = max(low, min(high, float(start)))
        self._ab_out_t = max(self._ab_in_t, min(high, float(end)))
        self._ab_in_btn.setChecked(True)
        self._ab_out_btn.setChecked(True)
        self._pin_in.pin_to_slider(self.slider, self._time_to_frac(self._ab_in_t))
        self._pin_out.pin_to_slider(self.slider, self._time_to_frac(self._ab_out_t))
        self._sync_scrub_track()
        self.ab_loop_changed.emit(self._ab_in_t, self._ab_out_t)

    @property
    def bounds(self) -> tuple[float, float]:
        """The master-timeline extent currently displayed.

        Public because ``engine/player.py`` needs it to decide where playback
        wraps; it used to reach into ``transport._bounds`` directly (V-13).
        """
        return self._bounds

    def set_bounds(self, t0: float, t1: float) -> None:
        self._bounds = (t0, t1)
        self._end_time_label.setText(format_time(t1, self._time_mode, self._t_epoch))
        self.overview.set_bounds(t0, t1)
        self._sync_scrub_track()

    def _sync_scrub_track(self) -> None:
        """Snapshot changed evidence for the slider, never called by a cursor tick."""
        # The slider is drawn in view time: with gaps collapsed, a collapsed
        # gap takes no track at all (D-218).
        warp = self.overview.warp
        view = warp.to_view
        coverage = tuple(
            (view(start), view(end))
            for source_id in self.overview._coverage
            for start, end in self.overview.source_spans(source_id)
        )
        raw_markers = self.overview._markers
        if len(raw_markers) > 64 and warp:
            m_starts = warp.to_view_array(
                np.fromiter(
                    (s for s, _e, _l in raw_markers), dtype=np.float64, count=len(raw_markers)
                )
            )
            m_ends = warp.to_view_array(
                np.fromiter(
                    (0.0 if e is None else e for _s, e, _l in raw_markers),
                    dtype=np.float64,
                    count=len(raw_markers),
                )
            )
            markers = tuple(
                (
                    float(m_starts[i]),
                    None if raw_markers[i][1] is None else float(m_ends[i]),
                    raw_markers[i][2],
                )
                for i in range(len(raw_markers))
            )
        else:
            markers = tuple(
                (view(start), None if end is None else view(end), label)
                for start, end, label in raw_markers
            )
        loop = tuple(None if t is None else view(t) for t in (self._ab_in_t, self._ab_out_t))
        self.slider.set_track_data(
            (view(self._bounds[0]), view(self._bounds[1])),
            coverage,
            markers,
            (loop[0], loop[1]),
        )
        self._repin()

    def set_time_mode(self, mode: TimeDisplayMode) -> None:
        self._time_mode = mode
        self._end_time_label.setText(format_time(self._bounds[1], self._time_mode, self._t_epoch))

    def set_t_epoch(self, epoch: float) -> None:
        self._t_epoch = epoch
        self._end_time_label.setText(format_time(self._bounds[1], self._time_mode, self._t_epoch))

    def format_master_time(self, t: float) -> str:
        """Format *t* exactly as the seek row displays it.

        The transport owns the displayed time mode and epoch, so anything that
        has to write a master time in the same words asks here rather than
        keeping a second copy of either.  It formats a
        given time rather than returning the field's text, which is the user's
        own keystrokes while they are typing a jump.
        """
        return format_time(t, self._time_mode, self._t_epoch)

    def status_text(self) -> str:
        """The currently displayed status message."""
        return self.status_line.status_text()

    def set_status(self, message: str, severity: str = "info") -> None:
        """Show compact, non-blocking status text in the status bar."""
        self.status_line.set_status(message, severity)

    def set_source_coverage(
        self,
        source_id: str,
        t0: float,
        t1: float,
        kind: str,
        group: str = "",
        holes: tuple[tuple[float, float], ...] | list[tuple[float, float]] = (),
    ) -> None:
        """Show one video or data coverage span in the overview strip.

        A *group* draws this span in one shared lane with every other source
        naming the same group, for files that are one recording seen from one
        angle and would otherwise repeat one span down the whole strip.
        *holes* are where between the session's parts the source has no data;
        its lane is empty there (D-218).
        """
        self.overview.set_coverage(source_id, t0, t1, kind, group, holes)

    def set_coverage_holes(self, holes: dict[str, list[tuple[float, float]]]) -> None:
        """Replace every source's holes, once the session's parts change."""
        self.overview.set_holes(holes)

    def set_collapse_gaps(self, collapse: bool) -> None:
        """Collapse the time no source has data in, for viewing only (D-218)."""
        self.overview.set_collapse_gaps(collapse)

    @property
    def warp(self):
        """How the timeline is drawn; master time is never changed by it."""
        return self.overview.warp

    def coverage_span(self) -> tuple[float, float] | None:
        """Return the master-time extent of every registered source, or None."""
        return self.overview.coverage_span()

    def set_ttl_events(self, events: list[float | tuple[float, str]] | tuple[float, ...]) -> None:
        """Show accepted synchronization events in the overview strip."""
        self.overview.set_ttl_events(events)

    def set_gap_events(self, events: list[float | tuple[float, str]] | tuple[float, ...]) -> None:
        """Show imported data gaps in the overview strip."""
        self.overview.set_gap_events(events)

    def set_message_events(
        self, events: list[float | tuple[float, str]] | tuple[float, ...]
    ) -> None:
        """Show messages the sources recorded in the overview strip."""
        self.overview.set_message_events(events)

    def set_identity_events(
        self, events: list[float | tuple[float, str]] | tuple[float, ...]
    ) -> None:
        """Show accepted identity swaps as crossings in the overview strip."""
        self.overview.set_identity_events(events)

    def set_identity_candidates(
        self, events: list[float | tuple[float, str]] | tuple[float, ...]
    ) -> None:
        """Show proposals for the currently selected identity group and part."""
        self.overview.set_identity_candidates(events)

    def set_annotation_markers(self, markers: list[tuple[float, float | None, str]]) -> None:
        """Show point and range annotations in the overview strip."""
        self.overview.set_markers(markers)

    def set_trial_segments(self, segments: list[tuple[float, float, str]]) -> None:
        """Show the recording's trials as a lane in Data Streams."""
        self.overview.set_segments(segments)

    def set_plot_viewport(self, start: float, duration: float, phase: float) -> None:
        """Mirror the single PlotPane page in the global Data Streams navigator."""
        self.overview.set_viewport(start, duration, phase)

    def set_time(self, t: float) -> None:
        """Update the displayed time (unless the user is typing)."""
        self._last_t = float(t)
        if not self._time_editing:
            self._time_edit.setText(format_time(t, self._time_mode, self._t_epoch))

        if not self._is_scrubbing:
            if self._bounds[1] > self._bounds[0]:
                val = max(0, min(10000, round(self._time_to_frac(t) * 10000)))
                self.slider.blockSignals(True)
                self.slider.setValue(val)
                self.slider.blockSignals(False)
        self.overview.set_cursor(t)

    def set_hover_time(self, t: object) -> None:
        """Forward plot hover time (float or None) to the timeline overview."""
        self.overview.set_hover_time(float(t) if isinstance(t, (int, float)) else None)

    def set_playing(self, playing: bool) -> None:
        self.play_btn.blockSignals(True)
        self.play_btn.setChecked(playing)
        self.play_btn.setText(tr("Pause") if playing else tr("Play"))
        set_svg_icon(self.play_btn, "pause" if playing else "play")
        self.play_btn.setAccessibleName(tr("Pause playback") if playing else tr("Start playback"))
        self.play_btn.blockSignals(False)
        self._update_shuttle_tooltip()

    def step_rate_up(self) -> None:
        """Advance the rate combo to the next higher step (L key)."""
        idx = min(self.rate_combo.currentIndex() + 1, self.rate_combo.count() - 1)
        self.rate_combo.setCurrentIndex(idx)

    # ── Internal helpers ──────────────────────────────────────────────

    def _t_from_slider(self, val: int) -> float:
        """The master time at a slider value; gaps collapsed take no track (D-218)."""
        warp = self.overview.warp
        t0, t1 = (warp.to_view(t) for t in self._bounds)
        return warp.to_master(t0 + (val / 10000.0) * (t1 - t0))

    def _time_to_frac(self, t: float) -> float:
        """Convert absolute time to a [0, 1] fraction within current bounds."""
        warp = self.overview.warp
        t0, t1 = (warp.to_view(time) for time in self._bounds)
        duration = t1 - t0
        if duration <= 0:
            return 0.0
        return max(0.0, min(1.0, (warp.to_view(t) - t0) / duration))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        """Allow horizontal splitters to narrow smoothly into two-row compact mode."""
        hint = self._root_layout.minimumSize()
        return QSize(min(hint.width(), self._MIN_COMPACT_WIDTH), hint.height())

    def _single_row_min_width(self) -> int:
        """Minimum width required to keep all transport controls and a usable slider on one row."""
        margins = self._root_layout.contentsMargins()
        gap = max(0, self._timeline_layout.spacing())
        items = (
            *self._playhead_buttons,
            self._time_edit,
            self._end_time_label,
            *self._loop_rate_controls,
        )
        controls_w = sum(max(w.minimumWidth(), w.minimumSizeHint().width()) for w in items)
        return (
            margins.left()
            + margins.right()
            + controls_w
            + self._MIN_SINGLE_ROW_SLIDER_WIDTH
            + gap * len(items)
        )

    def _sync_timeline_mode(self, width: int) -> None:
        """Split seek and transport controls into two rows when narrow."""
        want_compact = 0 < width < self._single_row_min_width()
        if want_compact == self._compact_timeline:
            return
        while self._timeline_layout.count():
            self._timeline_layout.takeAt(0)
        while self._controls_layout.count():
            self._controls_layout.takeAt(0)
        controls_index = self._root_layout.indexOf(self._controls_layout)
        if controls_index >= 0:
            self._root_layout.takeAt(controls_index)
        if want_compact:
            self._timeline_layout.addWidget(self._time_edit)
            self._timeline_layout.addWidget(self.slider, 1)
            self._timeline_layout.addWidget(self._end_time_label)
            for button in self._playhead_buttons:
                self._controls_layout.addWidget(button)
            self._controls_layout.addStretch(1)
            for control in self._loop_rate_controls:
                self._controls_layout.addWidget(control)
            self._root_layout.addLayout(self._controls_layout)
        else:
            for button in self._playhead_buttons:
                self._timeline_layout.addWidget(button)
            self._timeline_layout.addWidget(self._time_edit)
            self._timeline_layout.addWidget(self.slider, 1)
            self._timeline_layout.addWidget(self._end_time_label)
            for control in self._loop_rate_controls:
                self._timeline_layout.addWidget(control)
        self._compact_timeline = want_compact
        self.updateGeometry()
        self._root_layout.activate()

    def _repin(self) -> None:
        """Reposition all visible A/B pins from stored times + current geometry."""
        if self._ab_in_t is not None:
            self._pin_in.pin_to_slider(self.slider, self._time_to_frac(self._ab_in_t))
        if self._ab_out_t is not None:
            self._pin_out.pin_to_slider(self.slider, self._time_to_frac(self._ab_out_t))

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_timeline_mode(self.width())
        self._repin()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._sync_timeline_mode(self.width())
            self._repin()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_timeline_mode(event.size().width())
        self._repin()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Reserve Space for playback while retaining ordinary Tab accessibility."""
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            key = event.key()
            if key == Qt.Key.Key_Space:
                self.play_toggled.emit(not self.play_btn.isChecked())
                return True
        return super().eventFilter(watched, event)

    # ── Slots ─────────────────────────────────────────────────────────

    def _on_play_clicked(self, checked: bool) -> None:
        self.play_toggled.emit(checked)
        self.set_playing(checked)

    def _on_slider_pressed(self) -> None:
        self._is_scrubbing = True
        self._last_t = None
        self.seek_requested.emit(self._t_from_slider(self.slider.value()), False)

    def _on_slider_moved(self, val: int) -> None:
        self._last_t = None
        self.seek_requested.emit(self._t_from_slider(val), False)

    def _on_slider_released(self) -> None:
        self._is_scrubbing = False
        self.seek_requested.emit(self._t_from_slider(self.slider.value()), True)

    def _on_rate_changed(self, idx: int) -> None:
        rate = self.rate_combo.currentData()
        self.rate_changed.emit(rate)

    def _on_text_edited(self, _text: str) -> None:
        self._time_editing = True

    def _on_editing_done(self) -> None:
        self._time_editing = False

    def _on_ab_in(self) -> None:
        """Set A/B in-point at the exact playhead time (or slider position if unset)."""
        self._ab_in_t = (
            self._last_t if self._last_t is not None else self._t_from_slider(self.slider.value())
        )
        self._ab_in_btn.setChecked(True)
        self._pin_in.pin_to_slider(self.slider, self._time_to_frac(self._ab_in_t))
        self._sync_scrub_track()
        self.ab_loop_changed.emit(self._ab_in_t, self._ab_out_t)

    def _on_ab_in_clicked(self, _checked: bool = False) -> None:
        """Button click — set A/B in-point (button state managed here)."""
        self._on_ab_in()

    def _on_ab_out(self) -> None:
        """Set A/B out-point at the exact playhead time (or slider position if unset)."""
        self._ab_out_t = (
            self._last_t if self._last_t is not None else self._t_from_slider(self.slider.value())
        )
        self._ab_out_btn.setChecked(True)
        self._pin_out.pin_to_slider(self.slider, self._time_to_frac(self._ab_out_t))
        self._sync_scrub_track()
        self.ab_loop_changed.emit(self._ab_in_t, self._ab_out_t)

    def _on_ab_out_clicked(self, _checked: bool = False) -> None:
        """Button click — set A/B out-point (button state managed here)."""
        self._on_ab_out()

    def _on_ab_clear(self) -> None:
        self._ab_in_t = None
        self._ab_out_t = None
        self._ab_in_btn.setChecked(False)
        self._ab_out_btn.setChecked(False)
        self._pin_in.hide()
        self._pin_out.hide()
        self._sync_scrub_track()
        self.ab_loop_changed.emit(None, None)

    def _on_jump(self) -> None:
        text = self._time_edit.text().strip()
        if not text:
            return
        t = self._parse_time_input(text)
        if t is not None:
            clamped = max(self._bounds[0], min(self._bounds[1], t))
            self.seek_requested.emit(clamped, True)
            self._time_editing = False
            self.setFocus(Qt.FocusReason.OtherFocusReason)

    @staticmethod
    def _parse_time_input(text: str) -> float | None:
        """Parse HH:MM:SS.fff, MM:SS, or bare seconds."""
        try:
            return float(text)
        except ValueError:
            pass
        parts = text.split(":")
        try:
            if len(parts) == 3:
                h, m, s = parts
                return int(h) * 3600 + int(m) * 60 + float(s)
            if len(parts) == 2:
                m, s = parts
                return int(m) * 60 + float(s)
        except (ValueError, IndexError):
            pass
        return None
