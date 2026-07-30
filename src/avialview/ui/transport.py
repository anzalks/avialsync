"""Playback transport controls."""

from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from avialview.ui.theme import set_font_family, system_accent
from avialview.ui.time_format import TimeDisplayMode, format_time


class JumpSlider(QSlider):
    """A QSlider that instantly jumps to the clicked position."""

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            val = self.minimum() + int(
                (self.maximum() - self.minimum()) * event.position().x() / self.width()
            )
            self.setValue(val)
        super().mousePressEvent(event)


_EMPTY_TIMES = np.empty(0, dtype=np.float64)


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
        self.setMinimumHeight(28)
        self.setMaximumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setToolTip("Data Streams. Click to seek.")
        self.setAccessibleName("Data Streams lanes")
        self.setAccessibleDescription(
            "Named data, synchronization, gap, and annotation evidence on the master timeline."
        )
        self._bounds = (0.0, 0.0)
        self._cursor = 0.0
        self._coverage: dict[str, tuple[float, float, str]] = {}
        self._ttl_events: tuple[tuple[float, str], ...] = ()
        self._gap_events: tuple[tuple[float, str], ...] = ()
        # Sorted time index per event lane.  Paint and hover binary-search this
        # instead of scanning every event, so a 100k-event session costs the
        # same per frame as a 100-event one (P3.5 P1 hot path).
        self._event_times: dict[str, np.ndarray] = {"ttl": _EMPTY_TIMES, "gap": _EMPTY_TIMES}
        self._markers: tuple[tuple[float, float | None, str], ...] = ()
        self._viewport_start = 0.0
        self._viewport_duration = 0.0
        self._viewport_phase = 0.0
        self._dragging_viewport = False
        self._viewport_drag_offset = 0.0

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

    def set_coverage(self, source_id: str, t0: float, t1: float, kind: str) -> None:
        """Register one source coverage span, keyed for later replacement."""
        self._coverage[source_id] = (t0, t1, kind)
        self._on_evidence_changed()

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

    def _nearest_event(self, kind: str, time: float, tolerance: float):
        """Binary-search the nearest event of *kind*, or None outside tolerance."""
        times = self._event_times.get(kind, _EMPTY_TIMES)
        if len(times) == 0:
            return None
        events = self._ttl_events if kind == "ttl" else self._gap_events
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

    def lane_labels(self) -> list[str]:
        """Return the currently populated lanes, in their rendered order."""
        labels = [
            self._coverage_label(source_id, kind)
            for source_id, (_, _, kind) in self._coverage.items()
        ]
        if self._ttl_events:
            labels.append("Sync / TTL")
        if self._gap_events:
            labels.append("Data gaps")
        if self._markers:
            labels.append("Annotations")
        return labels

    def _on_evidence_changed(self) -> None:
        """Refresh labels and ensure populated lanes have usable vertical space."""
        lane_count = max(1, len(self.lane_labels()))
        requested_height = max(28, lane_count * self._MIN_LANE_HEIGHT + 4)
        self.setMinimumHeight(min(180, requested_height))
        self.evidence_changed.emit()
        self.update()

    @staticmethod
    def _coverage_label(source_id: str, kind: str) -> str:
        kind_label = "Video" if kind == "video" else "Data"
        return f"{kind_label} · {Path(source_id).name}"

    def _lanes(self) -> list[tuple[str, str, object]]:
        lanes: list[tuple[str, str, object]] = [
            (self._coverage_label(source_id, kind), "coverage", (source_id, start, end, kind))
            for source_id, (start, end, kind) in self._coverage.items()
        ]
        if self._ttl_events:
            lanes.append(("Sync / TTL", "ttl", self._ttl_events))
        if self._gap_events:
            lanes.append(("Data gaps", "gap", self._gap_events))
        if self._markers:
            lanes.append(("Annotations", "annotation", self._markers))
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
        detail = self._event_detail(event.position().x(), event.position().y())
        self.setToolTip(detail or "Data Streams. Click to seek.")
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
        painter.fillRect(self.rect(), palette.color(palette.ColorRole.AlternateBase))
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

        lane_height = max(self._MIN_LANE_HEIGHT, self.height() // len(lanes))
        accent = system_accent(palette)
        data_color = palette.color(palette.ColorRole.Link)
        label_pen = palette.color(palette.ColorRole.WindowText)
        label_width = min(self._LABEL_WIDTH, max(1, self.width() - 1))
        for lane_index, (label, lane_kind, payload) in enumerate(lanes):
            top = lane_index * lane_height
            bottom = min(self.height() - 1, top + lane_height - 1)
            painter.setPen(label_pen)
            painter.fillRect(
                0, top, label_width, lane_height, palette.color(palette.ColorRole.Base)
            )
            painter.drawText(
                4,
                top,
                label_width - 8,
                lane_height,
                Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            painter.setPen(palette.color(palette.ColorRole.Mid))
            painter.drawLine(self._LABEL_WIDTH, bottom, self.width() - 1, bottom)
            if lane_kind == "coverage":
                _, start, end, kind = payload
                span = self._visible_span_x(start, end)
                if span is None:
                    continue
                left, right = span
                color = accent if kind == "video" else data_color
                painter.fillRect(
                    left, top + 2, max(1, right - left), max(2, lane_height - 4), color
                )
            elif lane_kind == "ttl":
                painter.setPen(accent)
                for x in self._visible_event_x("ttl", t0, t1):
                    painter.drawLine(x, top + 2, x, bottom - 2)
            elif lane_kind == "gap":
                painter.setPen(QColor("#d64545"))
                for x in self._visible_event_x("gap", t0, t1):
                    painter.drawLine(x, top + 2, x, bottom - 2)
            elif lane_kind == "annotation":
                for start, end, color in payload:
                    span = self._visible_span_x(start, start if end is None else end)
                    if span is None:
                        continue
                    left, right = span
                    if end is None:
                        painter.fillRect(left, top + 2, 2, max(2, lane_height - 4), QColor(color))
                    else:
                        painter.fillRect(
                            left,
                            top + 2,
                            max(2, right - left),
                            max(2, lane_height - 4),
                            QColor(color).darker(130),
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
        lane_height = max(self._MIN_LANE_HEIGHT, self.height() // len(lanes))
        lane_index = min(len(lanes) - 1, int(y // lane_height))
        label, kind, payload = lanes[lane_index]
        time = self._time_at_x(x)
        tolerance = (t1 - t0) * 8 / max(1, self.width() - self._LABEL_WIDTH)
        if kind == "coverage":
            source, start, end, _ = payload
            if start <= time <= end:
                return f"Coverage\nSource: {Path(source).name}\nMaster time: {time:.6f} s"
        if kind in {"ttl", "gap"}:
            nearest = self._nearest_event(kind, time, tolerance)
            if nearest is not None:
                event_name = "Accepted sync / TTL event" if kind == "ttl" else "Imported data gap"
                extra = f"\n{nearest[1]}" if nearest[1] else ""
                return f"{event_name}\nMaster time: {nearest[0]:.6f} s{extra}"
        if kind == "annotation":
            for start, end, _ in payload:
                if start - tolerance <= time <= (end if end is not None else start) + tolerance:
                    return f"Annotation\nMaster time: {start:.6f} s"
        return f"{label}\nMaster time: {time:.6f} s"


class TimelineEvidence(QWidget):
    """Titled, collapsible Data Streams shell for named TimelineOverview lanes."""

    snapshot_requested = Signal()
    reset_zoom_requested = Signal()
    flag_requested = Signal()
    fullscreen_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = QSettings("AvialView", "AvialView")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(6)
        self.title = QLabel("Data Streams", self)
        self.title.setAccessibleName("Data Streams title")
        header.addWidget(self.title)
        self.collapse_button = QPushButton("Hide", self)
        self.collapse_button.setAccessibleName("Hide Data Streams")
        self.collapse_button.setToolTip("Hide or show the Data Streams lanes")
        self.collapse_button.clicked.connect(self.toggle_collapsed)
        header.addWidget(self.collapse_button)
        self.flag_button = QPushButton("Flag Frame", self)
        self.flag_button.setToolTip("Flag the current frame (M)")
        self.flag_button.clicked.connect(self.flag_requested.emit)
        header.addWidget(self.flag_button)
        header.addStretch(1)
        self.snapshot_button = QPushButton("Snapshot", self)
        self.snapshot_button.setToolTip("Export snapshot (Ctrl+E)")
        self.snapshot_button.clicked.connect(self.snapshot_requested.emit)
        header.addWidget(self.snapshot_button)
        self.fullscreen_button = QPushButton("Fullscreen Toggle", self)
        self.fullscreen_button.setToolTip("Toggle the active video pane fullscreen (F11)")
        self.fullscreen_button.clicked.connect(self.fullscreen_requested.emit)
        header.addWidget(self.fullscreen_button)
        self.reset_zoom_button = QPushButton("Reset Zoom", self)
        self.reset_zoom_button.setToolTip("Reset plot zoom to all loaded data (Ctrl+0)")
        self.reset_zoom_button.clicked.connect(self.reset_zoom_requested.emit)
        header.addWidget(self.reset_zoom_button)
        self._status_label = QLabel(self)
        self._status_label.setAccessibleName("Application status")
        self._status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._status_label.setToolTip("Non-blocking application status")
        self._status_label.hide()
        self._status_clear_timer = QTimer(self)
        self._status_clear_timer.setSingleShot(True)
        self._status_clear_timer.timeout.connect(self._clear_status)
        header.addWidget(self._status_label)
        layout.addLayout(header)
        self.overview = TimelineOverview(self)
        layout.addWidget(self.overview)
        collapsed = self._settings.value("timeline_evidence/collapsed", False, type=bool)
        self.set_collapsed(collapsed, persist=False)

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self.overview.isHidden())

    def set_status(self, message: str, severity: str = "info") -> None:
        """Show active work beside Reset Zoom and clear non-active messages shortly after."""
        colors = {"info": "#b8c7d9", "busy": "#f0c674", "warning": "#ff9f43", "error": "#ff6b6b"}
        self._status_label.setText(f"Status: {message}")
        self._status_label.setStyleSheet(f"color: {colors.get(severity, colors['info'])};")
        self._status_label.show()
        if severity == "busy":
            self._status_clear_timer.stop()
        else:
            self._status_clear_timer.start(5000)

    def _clear_status(self) -> None:
        self._status_label.clear()
        self._status_label.hide()

    def set_collapsed(self, collapsed: bool, *, persist: bool = True) -> None:
        self.overview.setVisible(not collapsed)
        self.collapse_button.setText("Show" if collapsed else "Hide")
        self.collapse_button.setAccessibleName(
            "Show Data Streams" if collapsed else "Hide Data Streams"
        )
        if persist:
            self._settings.setValue("timeline_evidence/collapsed", collapsed)


class _ABPin(QFrame):
    """Thin vertical marker overlaid on the slider for A/B loop points."""

    def __init__(self, color: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedWidth(2)
        self.setStyleSheet(f"background-color: {color}; border: none;")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
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
      snapshot_requested   — snapshot button or Ctrl+E
      fullscreen_requested — fullscreen button or F11
      jump_requested(float)— jump ±Ns (negative = back)
    """

    play_toggled = Signal(bool)
    seek_requested = Signal(float, bool)  # t, exact
    rate_changed = Signal(float)
    frame_step_requested = Signal(int)  # -1 or +1
    annotate_requested = Signal()
    ab_loop_changed = Signal(object, object)  # t_in|None, t_out|None
    snapshot_requested = Signal()
    fullscreen_requested = Signal()
    jump_requested = Signal(float)  # delta in seconds
    reset_zoom_requested = Signal()

    # Ordered playback-rate steps (J/K/L model, D-022.4)
    _RATE_STEPS = [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 10.0]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(5, 3, 5, 5)
        self._root_layout.setSpacing(2)
        self._timeline_layout = QHBoxLayout()
        self._timeline_layout.setSpacing(5)
        self._controls_layout = QHBoxLayout()
        self._controls_layout.setSpacing(4)
        self.evidence = TimelineEvidence(self)
        self.overview = self.evidence.overview
        self.overview.seek_requested.connect(lambda t: self.seek_requested.emit(t, True))
        self.overview.viewport_seek_requested.connect(
            lambda t, exact: self.seek_requested.emit(t, exact)
        )
        self.evidence.snapshot_requested.connect(self.snapshot_requested.emit)
        self.evidence.reset_zoom_requested.connect(self.reset_zoom_requested.emit)
        self.evidence.flag_requested.connect(self.annotate_requested.emit)
        self.evidence.fullscreen_requested.connect(self.fullscreen_requested.emit)
        self._root_layout.addWidget(self.evidence)
        self._root_layout.addLayout(self._timeline_layout)
        self._root_layout.addLayout(self._controls_layout)

        # ── Timeline row: playhead controls, scrub bar, A/B, end time, rate ──
        mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        self._time_edit = QLineEdit("00:00:00.000")
        self._time_edit.setMinimumWidth(110)
        self._time_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_font_family(self._time_edit, mono_font)
        self._time_edit.setToolTip(
            "Current time — click to edit.\nFormats: HH:MM:SS.fff, MM:SS, or seconds."
        )
        self._time_edit.returnPressed.connect(self._on_jump)
        self._time_edit.editingFinished.connect(self._on_editing_done)
        self._time_editing = False
        self._time_edit.textEdited.connect(self._on_text_edited)
        self._timeline_layout.addWidget(self._time_edit)

        self.slider = JumpSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 10000)
        self.slider.setToolTip("Master timeline — drag to scrub; release for an exact seek")
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self._timeline_layout.addWidget(self.slider, 1)

        self._end_time_label = QLabel("00:00:00.000", self)
        self._end_time_label.setMinimumWidth(110)
        self._end_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_font_family(self._end_time_label, mono_font)
        self._end_time_label.setToolTip("End of the loaded master timeline")
        self._timeline_layout.addWidget(self._end_time_label)

        # ── Jump back 1 s ─────────────────────────────────────────────
        self._jump_back_btn = QPushButton("–1s")
        self._jump_back_btn.setFixedWidth(36)
        self._jump_back_btn.setToolTip("Jump back 1 second (J or Shift+←)")
        self._jump_back_btn.clicked.connect(lambda: self.jump_requested.emit(-1.0))

        # ── Frame step back ───────────────────────────────────────────
        self._step_back_btn = QPushButton("◀")
        self._step_back_btn.setFixedWidth(28)
        self._step_back_btn.setToolTip("Step back 1 frame (← or ,)")
        self._step_back_btn.clicked.connect(lambda: self.frame_step_requested.emit(-1))

        # ── Play / Pause ──────────────────────────────────────────────
        self.play_btn = QPushButton("Play")
        self.play_btn.setFixedWidth(58)
        self.play_btn.setCheckable(True)
        self.play_btn.setToolTip("Play / Pause (Space)")
        self.play_btn.clicked.connect(self._on_play_clicked)

        # ── Frame step forward ────────────────────────────────────────
        self._step_fwd_btn = QPushButton("▶")
        self._step_fwd_btn.setFixedWidth(28)
        self._step_fwd_btn.setToolTip("Step forward 1 frame (→ or .)")
        self._step_fwd_btn.clicked.connect(lambda: self.frame_step_requested.emit(1))

        # ── Jump forward 1 s ──────────────────────────────────────────
        self._jump_fwd_btn = QPushButton("+1s")
        self._jump_fwd_btn.setFixedWidth(36)
        self._jump_fwd_btn.setToolTip("Jump forward 1 second (Shift+→)")
        self._jump_fwd_btn.clicked.connect(lambda: self.jump_requested.emit(1.0))

        # ── A/B loop buttons (checkable — D-022.5) ────────────────────
        self._ab_in_btn = QPushButton("[")
        self._ab_in_btn.setFixedWidth(28)
        self._ab_in_btn.setCheckable(True)
        self._ab_in_btn.setToolTip("Set loop in-point here ([ or I)")
        self._ab_in_btn.clicked.connect(self._on_ab_in_clicked)

        self._ab_out_btn = QPushButton("]")
        self._ab_out_btn.setFixedWidth(28)
        self._ab_out_btn.setCheckable(True)
        self._ab_out_btn.setToolTip("Set loop out-point here (] or O)")
        self._ab_out_btn.clicked.connect(self._on_ab_out_clicked)

        self._ab_clear_btn = QPushButton("✕")
        self._ab_clear_btn.setFixedWidth(24)
        self._ab_clear_btn.setToolTip("Clear A/B loop")
        self._ab_clear_btn.clicked.connect(self._on_ab_clear)

        # ── Rate combo (0.01× – 10×) ──────────────────────────────────
        self.rate_combo = QComboBox()
        for r in self._RATE_STEPS:
            label = f"{r}x" if r >= 0.1 else f"{r:.2f}x"
            self.rate_combo.addItem(label, r)
        self.rate_combo.setCurrentText("1.0x")
        self.rate_combo.setToolTip("Playback rate (L = step up, K = pause)")
        self.rate_combo.currentIndexChanged.connect(self._on_rate_changed)
        self._speed_label = QLabel("Speed", self)
        self._speed_label.setToolTip("Playback speed selector")

        playhead_buttons = (
            self._jump_back_btn,
            self._step_back_btn,
            self.play_btn,
            self._step_fwd_btn,
            self._jump_fwd_btn,
        )
        for index, button in enumerate(playhead_buttons):
            self._timeline_layout.insertWidget(index, button)
        end_time_index = self._timeline_layout.indexOf(self._end_time_label)
        for index, button in enumerate(
            (self._ab_in_btn, self._ab_out_btn, self._ab_clear_btn), start=end_time_index + 1
        ):
            self._timeline_layout.insertWidget(index, button)

        self._timeline_layout.addWidget(self._speed_label)
        self._timeline_layout.addWidget(self.rate_combo)

        self._bounds = (0.0, 0.0)
        self._is_scrubbing = False
        self._ab_in_t: float | None = None
        self._ab_out_t: float | None = None
        self._time_mode = TimeDisplayMode.RELATIVE
        self._t_epoch = 0.0

        # Overlay pins for A/B markers
        self._pin_in = _ABPin("#2a9d8f", self)
        self._pin_out = _ABPin("#e76f51", self)

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

    def set_bounds(self, t0: float, t1: float) -> None:
        self._bounds = (t0, t1)
        self._end_time_label.setText(format_time(t1, self._time_mode, self._t_epoch))
        self.overview.set_bounds(t0, t1)

    def set_time_mode(self, mode: TimeDisplayMode) -> None:
        self._time_mode = mode
        self._end_time_label.setText(format_time(self._bounds[1], self._time_mode, self._t_epoch))

    def set_t_epoch(self, epoch: float) -> None:
        self._t_epoch = epoch
        self._end_time_label.setText(format_time(self._bounds[1], self._time_mode, self._t_epoch))

    def set_status(self, message: str, severity: str = "info") -> None:
        """Show compact, non-blocking status text beside Reset Zoom."""
        self.evidence.set_status(message, severity)

    def set_source_coverage(self, source_id: str, t0: float, t1: float, kind: str) -> None:
        """Show one video or data coverage span in the overview strip."""
        self.overview.set_coverage(source_id, t0, t1, kind)

    def set_ttl_events(self, events: list[float | tuple[float, str]] | tuple[float, ...]) -> None:
        """Show accepted synchronization events in the overview strip."""
        self.overview.set_ttl_events(events)

    def set_gap_events(self, events: list[float | tuple[float, str]] | tuple[float, ...]) -> None:
        """Show imported data gaps in the overview strip."""
        self.overview.set_gap_events(events)

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
        self.play_btn.setText("Pause" if playing else "Play")
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
        self.ab_loop_changed.emit(self._ab_in_t, self._ab_out_t)

    def _on_ab_in_clicked(self, _checked: bool = False) -> None:
        """Button click — set A/B in-point (button state managed here)."""
        self._on_ab_in()

    def _on_ab_out(self) -> None:
        """Set A/B out-point at current slider position."""
        self._ab_out_t = self._t_from_slider(self.slider.value())
        self._ab_out_btn.setChecked(True)
        self._pin_out.pin_to_slider(self.slider, self._time_to_frac(self._ab_out_t))
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
