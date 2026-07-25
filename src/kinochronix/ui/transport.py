"""Playback transport controls."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QWidget,
)

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

    # Ordered playback-rate steps (J/K/L model, D-022.4)
    _RATE_STEPS = [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 10.0]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setLayout(QHBoxLayout())
        self.layout().setContentsMargins(5, 5, 5, 5)

        # ── Jump back 1 s ─────────────────────────────────────────────
        self._jump_back_btn = QPushButton("–1s")
        self._jump_back_btn.setFixedWidth(36)
        self._jump_back_btn.setToolTip("Jump back 1 second (J or Shift+←)")
        self._jump_back_btn.clicked.connect(lambda: self.jump_requested.emit(-1.0))
        self.layout().addWidget(self._jump_back_btn)

        # ── Frame step back ───────────────────────────────────────────
        self._step_back_btn = QPushButton("◀")
        self._step_back_btn.setFixedWidth(28)
        self._step_back_btn.setToolTip("Step back 1 frame (← or ,)")
        self._step_back_btn.clicked.connect(lambda: self.frame_step_requested.emit(-1))
        self.layout().addWidget(self._step_back_btn)

        # ── Play / Pause ──────────────────────────────────────────────
        self.play_btn = QPushButton("Play")
        self.play_btn.setCheckable(True)
        self.play_btn.setToolTip("Play / Pause (Space)")
        self.play_btn.clicked.connect(self._on_play_clicked)
        self.layout().addWidget(self.play_btn)

        # ── Frame step forward ────────────────────────────────────────
        self._step_fwd_btn = QPushButton("▶")
        self._step_fwd_btn.setFixedWidth(28)
        self._step_fwd_btn.setToolTip("Step forward 1 frame (→ or .)")
        self._step_fwd_btn.clicked.connect(lambda: self.frame_step_requested.emit(1))
        self.layout().addWidget(self._step_fwd_btn)

        # ── Jump forward 1 s ──────────────────────────────────────────
        self._jump_fwd_btn = QPushButton("+1s")
        self._jump_fwd_btn.setFixedWidth(36)
        self._jump_fwd_btn.setToolTip("Jump forward 1 second (Shift+→)")
        self._jump_fwd_btn.clicked.connect(lambda: self.jump_requested.emit(1.0))
        self.layout().addWidget(self._jump_fwd_btn)

        self.layout().addWidget(_sep(self))

        # ── Time display / jump input ──────────────────────────────────
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
        self.layout().addWidget(self._time_edit)

        # ── Scrub slider ──────────────────────────────────────────────
        self.slider = JumpSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 10000)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.layout().addWidget(self.slider)

        self.layout().addWidget(_sep(self))

        # ── A/B loop buttons (checkable — D-022.5) ────────────────────
        self._ab_in_btn = QPushButton("[")
        self._ab_in_btn.setFixedWidth(28)
        self._ab_in_btn.setCheckable(True)
        self._ab_in_btn.setToolTip("Set loop in-point here ([ or I)")
        self._ab_in_btn.clicked.connect(self._on_ab_in_clicked)
        self.layout().addWidget(self._ab_in_btn)

        self._ab_out_btn = QPushButton("]")
        self._ab_out_btn.setFixedWidth(28)
        self._ab_out_btn.setCheckable(True)
        self._ab_out_btn.setToolTip("Set loop out-point here (] or O)")
        self._ab_out_btn.clicked.connect(self._on_ab_out_clicked)
        self.layout().addWidget(self._ab_out_btn)

        self._ab_clear_btn = QPushButton("✕")
        self._ab_clear_btn.setFixedWidth(24)
        self._ab_clear_btn.setToolTip("Clear A/B loop")
        self._ab_clear_btn.clicked.connect(self._on_ab_clear)
        self.layout().addWidget(self._ab_clear_btn)

        self.layout().addWidget(_sep(self))

        # ── Annotate ──────────────────────────────────────────────────
        self._annotate_btn = QPushButton("⚑")
        self._annotate_btn.setFixedWidth(28)
        self._annotate_btn.setToolTip("Add marker at playhead (M)")
        self._annotate_btn.clicked.connect(self.annotate_requested.emit)
        self.layout().addWidget(self._annotate_btn)

        # ── Snapshot ──────────────────────────────────────────────────
        self._snapshot_btn = QPushButton("⊙")
        self._snapshot_btn.setFixedWidth(28)
        self._snapshot_btn.setToolTip("Export snapshot (Ctrl+E)")
        self._snapshot_btn.clicked.connect(self.snapshot_requested.emit)
        self.layout().addWidget(self._snapshot_btn)

        # ── Fullscreen toggle ─────────────────────────────────────────
        self._fullscreen_btn = QPushButton("⤢")
        self._fullscreen_btn.setFixedWidth(28)
        self._fullscreen_btn.setToolTip("Toggle pane fullscreen (F11)")
        self._fullscreen_btn.clicked.connect(self.fullscreen_requested.emit)
        self.layout().addWidget(self._fullscreen_btn)

        self.layout().addWidget(_sep(self))

        # ── Rate combo (0.01× – 10×) ──────────────────────────────────
        self.rate_combo = QComboBox()
        for r in self._RATE_STEPS:
            label = f"{r}x" if r >= 0.1 else f"{r:.2f}x"
            self.rate_combo.addItem(label, r)
        self.rate_combo.setCurrentText("1.0x")
        self.rate_combo.setToolTip("Playback rate (L = step up, K = pause)")
        self.rate_combo.currentIndexChanged.connect(self._on_rate_changed)
        self.layout().addWidget(self.rate_combo)

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

    def set_bounds(self, t0: float, t1: float) -> None:
        self._bounds = (t0, t1)

    def set_time_mode(self, mode: TimeDisplayMode) -> None:
        self._time_mode = mode

    def set_t_epoch(self, epoch: float) -> None:
        self._t_epoch = epoch

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
