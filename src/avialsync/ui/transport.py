"""Playback transport controls."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRegularExpression,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAccessible,
    QColor,
    QFontDatabase,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygon,
    QRegularExpressionValidator,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
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
from avialsync.ui.accessible_views import register_painted
from avialsync.ui.app_settings import app_settings
from avialsync.ui.design_tokens import DENSITY_ROW_HEIGHT, ControlRole, Density, apply_role
from avialsync.ui.feedback.status_line import StatusLine
from avialsync.ui.i18n import tr
from avialsync.ui.icons import set_svg_icon
from avialsync.ui.playback_rates import PLAYBACK_RATE_STEPS, rate_label
from avialsync.ui.preferences_dialog import read_setting
from avialsync.ui.scrub_bar import ScrubBar
from avialsync.ui.theme import (
    evidence_color,
    follow_palette,
    loop_pin_color,
    neutral_on_canvas,
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


@dataclass(frozen=True)
class _EventLane:
    """Point events (accepted TTL matches, or imported data gaps)."""

    events: tuple[tuple[float, str], ...]


@dataclass(frozen=True)
class _AnnotationLane:
    """Point and range annotation markers."""

    markers: tuple[tuple[float, float | None, str], ...]


#: A lane is its display label, its kind tag, and a payload whose shape depends
#: on that tag. Typed records let the paint and hover branches unpack safely;
#: the payload used to be `object`, which nothing could destructure.
_LanePayload = "_CoverageLane | _EventLane | _AnnotationLane | None"


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
    evidence_changed = Signal()
    _LABEL_WIDTH = 220
    _MIN_LANE_HEIGHT = 18

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._density = Density.COMPACT
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setToolTip(tr("Data Streams. Click to seek."))
        self.setAccessibleName(tr("Data Streams lanes"))
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
        self._viewport_start = 0.0
        self._viewport_duration = 0.0
        self._viewport_phase = 0.0
        self._dragging_viewport = False
        self._viewport_drag_offset = 0.0
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

    def set_viewport(self, start: float, duration: float, phase: float) -> None:
        """Render the one shared plot page without creating another time authority."""
        self._viewport_start = start
        self._viewport_duration = max(0.0, duration)
        self._viewport_phase = max(0.0, min(1.0, phase / duration)) if duration > 0 else 0.0
        self.update()

    def set_coverage(
        self, source_id: str, t0: float, t1: float, kind: str, group: str = ""
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
        else:
            self._coverage[source_id] = (t0, t1, kind, group)
        self._on_evidence_changed()

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
        """Display imported data gaps as red ticks."""
        self._gap_events = _normalise_events(events)
        self._event_times["gap"] = _time_index(self._gap_events)
        self._on_evidence_changed()

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
        the same place for the other (D-141).
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
        columns = np.fromiter(
            (self._content_x(float(time)) for time in times[first:last]),
            dtype=np.int64,
            count=last - first,
        )
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

    def set_markers(self, markers: list[tuple[float, float | None, str]]) -> None:
        """Display point/range annotations in their stored colors."""
        self._markers = tuple(markers)
        self._on_evidence_changed()

    def accessible_value(self) -> str:
        """The playhead, read when assistive technology asks (D-179)."""
        return tr("Playhead at {time} s").format(time=f"{self._cursor:.3f}")

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
        return "; ".join(parts) or tr("No sources are loaded.")

    def lane_labels(self) -> list[str]:
        """Return the currently populated lanes, in their rendered order.

        Read from the lanes themselves so the height and painted rows agree.
        """
        return [label for label, _, _ in self._lanes()]

    def _on_evidence_changed(self) -> None:
        """Refresh labels and ensure populated lanes have usable vertical space."""
        lane_count = max(1, len(self.lane_labels()))
        self.setFixedHeight(max(28, lane_count * self.lane_height()))
        self.evidence_changed.emit()
        self.update()

    @staticmethod
    def _coverage_label(source_id: str, kind: str) -> str:
        kind_label = "Video" if kind == "video" else "Data"
        return f"{kind_label} · {Path(source_id).name}"

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
            if not group:
                lanes.append(
                    (
                        self._coverage_label(source_id, kind),
                        "coverage",
                        _CoverageLane(source_id, start, end, kind),
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
                        _CoverageLane(group, start, end, kind),
                    )
                )
                continue
            label, tag, merged = lanes[position]
            assert isinstance(merged, _CoverageLane)
            lanes[position] = (
                label,
                tag,
                _CoverageLane(
                    merged.source_id,
                    min(merged.start, start),
                    max(merged.end, end),
                    kind,
                    merged.members + 1,
                ),
            )
        return lanes

    def _lanes(self) -> list[tuple[str, str, _CoverageLane | _EventLane | _AnnotationLane | None]]:
        lanes = self._coverage_lanes()
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
        return lanes

    def _content_x(self, time: float) -> int:
        t0, t1 = self._bounds
        width = max(1, self.width() - self._LABEL_WIDTH - 1)
        if t1 <= t0:
            return self._LABEL_WIDTH
        return self._LABEL_WIDTH + round((time - t0) / (t1 - t0) * width)

    def _time_at_x(self, x: float) -> float:
        t0, t1 = self._bounds
        width = max(1, self.width() - self._LABEL_WIDTH - 1)
        fraction = min(1.0, max(0.0, (x - self._LABEL_WIDTH) / width))
        return t0 + fraction * (t1 - t0)

    def _visible_span_x(self, start: float, end: float) -> tuple[int, int] | None:
        """Return the clipped timeline span, excluding the source-label gutter."""
        t0, t1 = self._bounds
        first, last = sorted((start, end))
        if t1 <= t0 or last < t0 or first > t1:
            return None
        left = max(self._LABEL_WIDTH, self._content_x(max(t0, first)))
        right = min(self.width() - 1, self._content_x(min(t1, last)))
        return left, max(left, right)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            t0, t1 = self._bounds
            if event.position().x() >= self._LABEL_WIDTH and t1 > t0:
                viewport = self._visible_span_x(
                    self._viewport_start, self._viewport_start + self._viewport_duration
                )
                if viewport is not None and viewport[0] <= event.position().x() <= viewport[1]:
                    self._dragging_viewport = True
                    self._viewport_drag_offset = event.position().x() - viewport[0]
                    event.accept()
                    return
                self.seek_requested.emit(self._time_at_x(event.position().x()))
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging_viewport:
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
        if self._dragging_viewport and event.button() == Qt.MouseButton.LeftButton:
            self._move_viewport(event.position().x(), exact=True)
            self._dragging_viewport = False
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
                span = self._visible_span_x(payload.start, payload.end)
                if span is None:
                    continue
                left, right = span
                color = accent if payload.kind == "video" else data_color
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
                # colour (rule 17).
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setPen(QPen(evidence_color(palette, "identity"), _GLYPH_WIDTH))
                for x in self._visible_event_x("identity", t0, t1):
                    painter.drawLine(x - 3, band_top, x + 3, band_top + band_height)
                    painter.drawLine(x + 3, band_top, x - 3, band_top + band_height)
                # The same hue at the same strength. Fading a proposal was the
                # obvious way to say "not yet" and it said "not there" instead;
                # hollow against the accepted crossing's stroke carries it
                # without spending contrast (rule 17).
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
            elif isinstance(payload, _AnnotationLane):
                for start, end, marker_color in payload.markers:
                    span = self._visible_span_x(start, start if end is None else end)
                    if span is None:
                        continue
                    left, right = span
                    if end is None:
                        painter.fillRect(left, band_top, 2, band_height, QColor(marker_color))
                    else:
                        _paint_span(
                            painter,
                            left,
                            band_top,
                            right - left,
                            band_height,
                            QColor(marker_color),
                        )

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

        painter.setPen(palette.color(palette.ColorRole.BrightText))
        cursor_x = min(self.width() - 1, max(self._LABEL_WIDTH, self._content_x(self._cursor)))
        painter.drawLine(cursor_x, 0, cursor_x, self.height() - 1)

    def _event_detail(self, x: float, y: float) -> str:
        """Return concise inspectable evidence nearest the pointer, if any."""
        t0, t1 = self._bounds
        if t1 <= t0:
            return ""
        lanes = self._lanes()
        if not lanes:
            return f"Navigator\nMaster time: {self._time_at_x(x):.6f} s"
        lane_height = self.lane_height()
        lane_index = min(len(lanes) - 1, int(y // lane_height))
        label, kind, payload = lanes[lane_index]
        time = self._time_at_x(x)
        tolerance = (t1 - t0) * 8 / max(1, self.width() - self._LABEL_WIDTH)
        if isinstance(payload, _CoverageLane):
            if payload.start <= time <= payload.end:
                source = Path(payload.source_id).name
                if payload.members > 1:
                    source = f"{source} ({payload.members} sources)"
                return f"Coverage\nSource: {source}\nMaster time: {time:.6f} s"
        if kind in {"ttl", "gap", "message", "identity"}:
            if kind == "identity":
                candidate = self._nearest_event("identity_candidate", time, tolerance)
                accepted = self._nearest_event("identity", time, tolerance)
                if candidate is not None and (
                    accepted is None or abs(candidate[0] - time) < abs(accepted[0] - time)
                ):
                    return tr("Possible identity swap\nMaster time: {time:.6f} s\n{detail}").format(
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
                return f"{event_name}\nMaster time: {nearest[0]:.6f} s{extra}"
        if isinstance(payload, _AnnotationLane):
            for start, end, _ in payload.markers:
                if start - tolerance <= time <= (end if end is not None else start) + tolerance:
                    return f"Annotation\nMaster time: {start:.6f} s"
        return f"{label}\nMaster time: {time:.6f} s"


class TimelineEvidence(QWidget):
    """Titled, collapsible Data Streams shell for named TimelineOverview lanes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = app_settings()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(6)
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

    New signals (D-022):
      jump_requested(float)— jump ±Ns (negative = back)

    Snapshot and Fullscreen moved to the ViewToolbar under the videos, and the
    Data Streams "Reset Zoom" -- a twin of the plots' own Reset -- was removed
    (D-126).
    """

    play_toggled = Signal(bool)
    seek_requested = Signal(float, bool)  # t, exact
    rate_changed = Signal(float)
    frame_step_requested = Signal(int)  # -1 or +1
    ab_loop_changed = Signal(object, object)  # t_in|None, t_out|None
    jump_requested = Signal(float)  # delta in seconds

    # Ordered playback-rate steps (J/K/L model, D-022.4)
    _RATE_STEPS = PLAYBACK_RATE_STEPS

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(5, 3, 5, 5)
        self._root_layout.setSpacing(2)
        self._timeline_layout = QHBoxLayout()
        self._timeline_layout.setSpacing(5)
        self.evidence = TimelineEvidence(self)
        self.status_line = StatusLine(self)
        self.overview = self.evidence.overview
        self.overview.seek_requested.connect(lambda t: self.seek_requested.emit(t, True))
        self.overview.viewport_seek_requested.connect(
            lambda t, exact: self.seek_requested.emit(t, exact)
        )
        self._root_layout.addWidget(self.evidence)
        self._root_layout.addLayout(self._timeline_layout)

        # ── Timeline row: playhead controls, scrub bar, A/B, end time, rate ──
        mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        self._time_edit = QLineEdit("00:00:00.000")
        # Declare which characters a timecode can hold. The grammar is still
        # checked by `_parse_time_input` on Enter; this only says what may be
        # typed at all, which is what lets the window take back a letter
        # shortcut the field would have discarded anyway (D-059). "UTC" is in
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

        # ── A/B loop buttons (checkable — D-022.5) ────────────────────
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
        for r in self._RATE_STEPS:
            self.rate_combo.addItem(rate_label(r), r)
        self.rate_combo.setCurrentText("1.0x")
        self.rate_combo.setToolTip(tr("Playback rate (L = step up, K = pause)"))
        self.rate_combo.currentIndexChanged.connect(self._on_rate_changed)
        playhead_buttons = (
            self._jump_back_btn,
            self._step_back_btn,
            self.play_btn,
            self._step_fwd_btn,
            self._jump_fwd_btn,
        )
        for index, button in enumerate(playhead_buttons):
            self._timeline_layout.insertWidget(index, button)
        for button in (self._ab_in_btn, self._ab_out_btn, self._ab_clear_btn):
            self._timeline_layout.addWidget(button)
        self._timeline_layout.addWidget(self.rate_combo)

        self._bounds = (0.0, 0.0)
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
        """Set the A/B loop in-point at the current slider position (public, D-022.1)."""
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
        """Set the A/B loop out-point at the current slider position (public, D-022.1)."""
        self._on_ab_out()

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
        coverage = tuple((start, end) for start, end, _, _ in self.overview._coverage.values())
        self.slider.set_track_data(
            self._bounds,
            coverage,
            self.overview._markers,
            (self._ab_in_t, self._ab_out_t),
        )

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
        keeping a second copy of either (D-020, AGENTS rule 15).  It formats a
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
        self, source_id: str, t0: float, t1: float, kind: str, group: str = ""
    ) -> None:
        """Show one video or data coverage span in the overview strip.

        A *group* draws this span in one shared lane with every other source
        naming the same group, for files that are one recording seen from one
        angle and would otherwise repeat one span down the whole strip.
        """
        self.overview.set_coverage(source_id, t0, t1, kind, group)

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

    def set_plot_viewport(self, start: float, duration: float, phase: float) -> None:
        """Mirror the single PlotPane page in the global Data Streams navigator."""
        self.overview.set_viewport(start, duration, phase)

    def set_time(self, t: float) -> None:
        """Update the displayed time (unless the user is typing)."""
        if not self._time_editing:
            self._time_edit.setText(format_time(t, self._time_mode, self._t_epoch))

        if not self._is_scrubbing:
            duration = self._bounds[1] - self._bounds[0]
            if duration > 0:
                val = int((t - self._bounds[0]) / duration * 10000)
                val = max(0, min(10000, val))
                self.slider.blockSignals(True)
                self.slider.setValue(val)
                self.slider.blockSignals(False)
        self.overview.set_cursor(t)

    def set_playing(self, playing: bool) -> None:
        self.play_btn.blockSignals(True)
        self.play_btn.setChecked(playing)
        self.play_btn.setText(tr("Pause") if playing else tr("Play"))
        set_svg_icon(self.play_btn, "pause" if playing else "play")
        self.play_btn.setAccessibleName(tr("Pause playback") if playing else tr("Start playback"))
        self.play_btn.blockSignals(False)

    def step_rate_up(self) -> None:
        """Advance the rate combo to the next higher step (L key, D-022.4)."""
        idx = min(self.rate_combo.currentIndex() + 1, self.rate_combo.count() - 1)
        self.rate_combo.setCurrentIndex(idx)

    # ── Internal helpers ──────────────────────────────────────────────

    def _t_from_slider(self, val: int) -> float:
        duration = self._bounds[1] - self._bounds[0]
        return self._bounds[0] + (val / 10000.0) * duration

    def _time_to_frac(self, t: float) -> float:
        """Convert absolute time to a [0, 1] fraction within current bounds."""
        t0, t1 = self._bounds
        duration = t1 - t0
        if duration <= 0:
            return 0.0
        return max(0.0, min(1.0, (t - t0) / duration))

    def _repin(self) -> None:
        """Reposition all visible A/B pins from stored times + current geometry."""
        if self._ab_in_t is not None:
            self._pin_in.pin_to_slider(self.slider, self._time_to_frac(self._ab_in_t))
        if self._ab_out_t is not None:
            self._pin_out.pin_to_slider(self.slider, self._time_to_frac(self._ab_out_t))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
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
        self.seek_requested.emit(self._t_from_slider(self.slider.value()), False)

    def _on_slider_moved(self, val: int) -> None:
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
        """Set A/B in-point at current slider position."""
        self._ab_in_t = self._t_from_slider(self.slider.value())
        self._ab_in_btn.setChecked(True)
        self._pin_in.pin_to_slider(self.slider, self._time_to_frac(self._ab_in_t))
        self._sync_scrub_track()
        self.ab_loop_changed.emit(self._ab_in_t, self._ab_out_t)

    def _on_ab_in_clicked(self, _checked: bool = False) -> None:
        """Button click — set A/B in-point (button state managed here)."""
        self._on_ab_in()

    def _on_ab_out(self) -> None:
        """Set A/B out-point at current slider position."""
        self._ab_out_t = self._t_from_slider(self.slider.value())
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
