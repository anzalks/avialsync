"""Playback transport controls."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase, QMouseEvent, QPainter, QPaintEvent, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from kinochronix.ui.theme import system_accent
from kinochronix.ui.time_format import TimeDisplayMode, format_time


class JumpSlider(QSlider):
    """A QSlider that instantly jumps to the clicked position."""

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            val = self.minimum() + int(
                (self.maximum() - self.minimum()) * event.position().x() / self.width()
            )
            self.setValue(val)
        super().mousePressEvent(event)


class TimelineOverview(QWidget):
    """Compact, clickable overview of coverage and inspection evidence."""

    seek_requested = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setMouseTracking(True)
        self.setToolTip(
            "Overview: source coverage, annotations, gaps, and accepted TTL matches. "
            "Click to seek on the master timeline. Drag its lower edge to resize."
        )
        self._bounds = (0.0, 0.0)
        self._cursor = 0.0
        self._coverage: dict[str, tuple[float, float, str]] = {}
        self._ttl_events: tuple[float, ...] = ()
        self._gap_events: tuple[float, ...] = ()
        self._markers: tuple[tuple[float, float | None, str], ...] = ()
        self._resize_origin_y: float | None = None
        self._resize_origin_height = self.height()

    def set_bounds(self, t0: float, t1: float) -> None:
        """Set the shared master-time range rendered by this overview."""
        self._bounds = (t0, t1)
        self.update()

    def set_cursor(self, t: float) -> None:
        """Move the overview playhead without recalculating any evidence."""
        self._cursor = t
        self.update()

    def set_coverage(self, source_id: str, t0: float, t1: float, kind: str) -> None:
        """Register one source coverage span, keyed for later replacement."""
        self._coverage[source_id] = (t0, t1, kind)
        self.update()

    def set_ttl_events(self, events: list[float] | tuple[float, ...]) -> None:
        """Display accepted TTL/event matches as cyan ticks."""
        self._ttl_events = tuple(events)
        self.update()

    def set_gap_events(self, events: list[float] | tuple[float, ...]) -> None:
        """Display imported data gaps as red ticks."""
        self._gap_events = tuple(events)
        self.update()

    def set_markers(self, markers: list[tuple[float, float | None, str]]) -> None:
        """Display point/range annotations in their stored colors."""
        self._markers = tuple(markers)
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if event.position().y() >= self.height() - 5:
                self._resize_origin_y = event.globalPosition().y()
                self._resize_origin_height = self.height()
                event.accept()
                return
            t0, t1 = self._bounds
            if self.width() > 0 and t1 > t0:
                fraction = min(1.0, max(0.0, event.position().x() / self.width()))
                self.seek_requested.emit(t0 + fraction * (t1 - t0))
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._resize_origin_y is not None:
            height = round(
                self._resize_origin_height + event.globalPosition().y() - self._resize_origin_y
            )
            self.setFixedHeight(max(20, min(180, height)))
            event.accept()
            return
        edge = event.position().y() >= self.height() - 5
        self.setCursor(Qt.CursorShape.SizeVerCursor if edge else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._resize_origin_y is not None and event.button() == Qt.MouseButton.LeftButton:
            self._resize_origin_y = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.color(palette.ColorRole.AlternateBase))
        t0, t1 = self._bounds
        if t1 <= t0:
            return

        def x_at(time: float) -> int:
            return round((time - t0) / (t1 - t0) * max(0, self.width() - 1))

        lane_height = max(2, self.height() // max(1, len(self._coverage)))
        accent = system_accent(palette)
        data_color = palette.color(palette.ColorRole.Link)
        for lane, (_, (start, end, kind)) in enumerate(sorted(self._coverage.items())):
            left, right = sorted((x_at(start), x_at(end)))
            painter.fillRect(
                left,
                lane * lane_height,
                max(1, right - left),
                lane_height - 1,
                accent if kind == "video" else data_color,
            )

        for start, end, color in self._markers:
            left = x_at(start)
            if end is None:
                painter.fillRect(left, 0, 2, self.height(), QColor(color))
            else:
                painter.fillRect(
                    min(left, x_at(end)),
                    0,
                    max(2, abs(x_at(end) - left)),
                    self.height(),
                    QColor(color).darker(130),
                )

        painter.setPen(QColor("#d64545"))
        for gap in self._gap_events:
            x = x_at(gap)
            painter.drawLine(x, 0, x, self.height() - 1)

        painter.setPen(accent)
        for ttl in self._ttl_events:
            x = x_at(ttl)
            painter.drawLine(x, self.height() // 2, x, self.height() - 1)

        painter.setPen(palette.color(palette.ColorRole.BrightText))
        cursor_x = x_at(self._cursor)
        painter.drawLine(cursor_x, 0, cursor_x, self.height() - 1)


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


def _sep(parent: QWidget) -> QFrame:
    """Thin vertical separator for the transport bar."""
    sep = QFrame(parent)
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setFrameShadow(QFrame.Shadow.Sunken)
    sep.setFixedWidth(6)
    return sep


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
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(5, 3, 5, 5)
        root_layout.setSpacing(2)
        self._timeline_layout = QHBoxLayout()
        self._timeline_layout.setSpacing(5)
        self._controls_layout = QHBoxLayout()
        self._controls_layout.setSpacing(4)
        root_layout.addLayout(self._timeline_layout)
        root_layout.addLayout(self._controls_layout)

        # ── Timeline row: time, scrub bar, end time, view reset ──────
        mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        self._time_edit = QLineEdit("00:00:00.000")
        self._time_edit.setFixedWidth(110)
        self._time_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time_edit.setStyleSheet(f"font-family: '{mono_font}'; font-size: 12px;")
        self._time_edit.setToolTip(
            "Current time — click to edit.\nFormats: HH:MM:SS.fff, MM:SS, or seconds."
        )
        self._time_edit.returnPressed.connect(self._on_jump)
        self._time_edit.editingFinished.connect(self._on_editing_done)
        self._time_editing = False
        self._time_edit.textEdited.connect(self._on_text_edited)
        self._timeline_layout.addWidget(self._time_edit)

        timeline_stack = QVBoxLayout()
        timeline_stack.setContentsMargins(0, 0, 0, 0)
        timeline_stack.setSpacing(1)
        self.slider = JumpSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 10000)
        self.slider.setToolTip("Master timeline — drag to scrub; release for an exact seek")
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.sliderReleased.connect(self._on_slider_released)
        timeline_stack.addWidget(self.slider)
        self.overview = TimelineOverview(self)
        self.overview.seek_requested.connect(lambda t: self.seek_requested.emit(t, True))
        timeline_stack.addWidget(self.overview)
        self._timeline_layout.addLayout(timeline_stack, 1)

        self._end_time_label = QLabel("00:00:00.000", self)
        self._end_time_label.setFixedWidth(110)
        self._end_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._end_time_label.setStyleSheet(f"font-family: '{mono_font}'; font-size: 12px;")
        self._end_time_label.setToolTip("End of the loaded master timeline")
        self._timeline_layout.addWidget(self._end_time_label)

        self._reset_zoom_btn = QPushButton("Reset Zoom", self)
        self._reset_zoom_btn.setToolTip("Reset plot zoom to all loaded data (Ctrl+0)")
        self._reset_zoom_btn.clicked.connect(self.reset_zoom_requested.emit)
        self._timeline_layout.addWidget(self._reset_zoom_btn)

        # ── Jump back 1 s ─────────────────────────────────────────────
        self._jump_back_btn = QPushButton("–1s")
        self._jump_back_btn.setFixedWidth(36)
        self._jump_back_btn.setToolTip("Jump back 1 second (J or Shift+←)")
        self._jump_back_btn.clicked.connect(lambda: self.jump_requested.emit(-1.0))
        self._controls_layout.addWidget(self._jump_back_btn)

        # ── Frame step back ───────────────────────────────────────────
        self._step_back_btn = QPushButton("◀")
        self._step_back_btn.setFixedWidth(28)
        self._step_back_btn.setToolTip("Step back 1 frame (← or ,)")
        self._step_back_btn.clicked.connect(lambda: self.frame_step_requested.emit(-1))
        self._controls_layout.addWidget(self._step_back_btn)

        # ── Play / Pause ──────────────────────────────────────────────
        self.play_btn = QPushButton("Play")
        self.play_btn.setCheckable(True)
        self.play_btn.setToolTip("Play / Pause (Space)")
        self.play_btn.clicked.connect(self._on_play_clicked)
        self._controls_layout.addWidget(self.play_btn)

        # ── Frame step forward ────────────────────────────────────────
        self._step_fwd_btn = QPushButton("▶")
        self._step_fwd_btn.setFixedWidth(28)
        self._step_fwd_btn.setToolTip("Step forward 1 frame (→ or .)")
        self._step_fwd_btn.clicked.connect(lambda: self.frame_step_requested.emit(1))
        self._controls_layout.addWidget(self._step_fwd_btn)

        # ── Jump forward 1 s ──────────────────────────────────────────
        self._jump_fwd_btn = QPushButton("+1s")
        self._jump_fwd_btn.setFixedWidth(36)
        self._jump_fwd_btn.setToolTip("Jump forward 1 second (Shift+→)")
        self._jump_fwd_btn.clicked.connect(lambda: self.jump_requested.emit(1.0))
        self._controls_layout.addWidget(self._jump_fwd_btn)

        self._controls_layout.addWidget(_sep(self))

        # ── A/B loop buttons (checkable — D-022.5) ────────────────────
        self._ab_in_btn = QPushButton("[")
        self._ab_in_btn.setFixedWidth(28)
        self._ab_in_btn.setCheckable(True)
        self._ab_in_btn.setToolTip("Set loop in-point here ([ or I)")
        self._ab_in_btn.clicked.connect(self._on_ab_in_clicked)
        self._controls_layout.addWidget(self._ab_in_btn)

        self._ab_out_btn = QPushButton("]")
        self._ab_out_btn.setFixedWidth(28)
        self._ab_out_btn.setCheckable(True)
        self._ab_out_btn.setToolTip("Set loop out-point here (] or O)")
        self._ab_out_btn.clicked.connect(self._on_ab_out_clicked)
        self._controls_layout.addWidget(self._ab_out_btn)

        self._ab_clear_btn = QPushButton("✕")
        self._ab_clear_btn.setFixedWidth(24)
        self._ab_clear_btn.setToolTip("Clear A/B loop")
        self._ab_clear_btn.clicked.connect(self._on_ab_clear)
        self._controls_layout.addWidget(self._ab_clear_btn)

        self._controls_layout.addWidget(_sep(self))

        # ── Annotate ──────────────────────────────────────────────────
        self._annotate_btn = QPushButton("⚑")
        self._annotate_btn.setFixedWidth(28)
        self._annotate_btn.setToolTip("Add marker at playhead (M)")
        self._annotate_btn.clicked.connect(self.annotate_requested.emit)
        self._controls_layout.addWidget(self._annotate_btn)

        # ── Snapshot ──────────────────────────────────────────────────
        self._snapshot_btn = QPushButton("⊙")
        self._snapshot_btn.setFixedWidth(28)
        self._snapshot_btn.setToolTip("Export snapshot (Ctrl+E)")
        self._snapshot_btn.clicked.connect(self.snapshot_requested.emit)
        self._controls_layout.addWidget(self._snapshot_btn)

        # ── Fullscreen toggle ─────────────────────────────────────────
        self._fullscreen_btn = QPushButton("⤢")
        self._fullscreen_btn.setFixedWidth(28)
        self._fullscreen_btn.setToolTip("Toggle pane fullscreen (F11)")
        self._fullscreen_btn.clicked.connect(self.fullscreen_requested.emit)
        self._controls_layout.addWidget(self._fullscreen_btn)

        self._controls_layout.addWidget(_sep(self))

        # ── Rate combo (0.01× – 10×) ──────────────────────────────────
        self.rate_combo = QComboBox()
        for r in self._RATE_STEPS:
            label = f"{r}x" if r >= 0.1 else f"{r:.2f}x"
            self.rate_combo.addItem(label, r)
        self.rate_combo.setCurrentText("1.0x")
        self.rate_combo.setToolTip("Playback rate (L = step up, K = pause)")
        self.rate_combo.currentIndexChanged.connect(self._on_rate_changed)
        self._controls_layout.addWidget(self.rate_combo)

        self._controls_layout.addStretch(1)
        self._status_label = QLabel("Ready", self)
        self._status_label.setMinimumWidth(220)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._status_label.setToolTip("Non-blocking application status")
        self._controls_layout.addWidget(self._status_label)

        self._bounds = (0.0, 0.0)
        self._is_scrubbing = False
        self._ab_in_t: float | None = None
        self._ab_out_t: float | None = None
        self._time_mode = TimeDisplayMode.RELATIVE
        self._t_epoch = 0.0

        # Overlay pins for A/B markers
        self._pin_in = _ABPin("#2a9d8f", self)
        self._pin_out = _ABPin("#e76f51", self)

        # Prevent buttons/combos/sliders from stealing the Spacebar shortcut
        for widget in self.findChildren(QWidget):
            if isinstance(widget, (QPushButton, QComboBox, QSlider)):
                widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    # ── Public API ────────────────────────────────────────────────────

    def ab_in(self) -> None:
        """Set the A/B loop in-point at the current slider position (public, D-022.1)."""
        self._on_ab_in()

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
        """Show compact, non-blocking status text on the transport controls row."""
        colors = {"info": "#b8c7d9", "busy": "#f0c674", "warning": "#ff9f43", "error": "#ff6b6b"}
        color = colors.get(severity, colors["info"])
        self._status_label.setText(message)
        self._status_label.setStyleSheet(f"color: {color};")

    def set_source_coverage(self, source_id: str, t0: float, t1: float, kind: str) -> None:
        """Show one video or data coverage span in the overview strip."""
        self.overview.set_coverage(source_id, t0, t1, kind)

    def set_ttl_events(self, events: list[float] | tuple[float, ...]) -> None:
        """Show accepted synchronization events in the overview strip."""
        self.overview.set_ttl_events(events)

    def set_gap_events(self, events: list[float] | tuple[float, ...]) -> None:
        """Show imported data gaps in the overview strip."""
        self.overview.set_gap_events(events)

    def set_annotation_markers(self, markers: list[tuple[float, float | None, str]]) -> None:
        """Show point and range annotations in the overview strip."""
        self.overview.set_markers(markers)

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
