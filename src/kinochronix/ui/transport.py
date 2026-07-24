"""Playback transport controls."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QFontDatabase
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
    QWidget,
)


class JumpSlider(QSlider):
    """A QSlider that instantly jumps to the clicked position."""

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            val = self.minimum() + int(
                (self.maximum() - self.minimum())
                * event.position().x()
                / self.width()
            )
            self.setValue(val)
        super().mousePressEvent(event)


class _ABPin(QFrame):
    """Thin vertical marker overlaid on the slider for A/B loop points."""

    def __init__(self, color: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedWidth(2)
        self.setStyleSheet(
            f"background-color: {color}; border: none;"
        )
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
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
    A/B loop, rate control, and inline time display / jump."""

    play_toggled = Signal(bool)
    seek_requested = Signal(float, bool)  # t, exact
    rate_changed = Signal(float)
    frame_step_requested = Signal(int)  # -1 or +1
    ab_loop_changed = Signal(object, object)  # t_in|None, t_out|None

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setLayout(QHBoxLayout())
        self.layout().setContentsMargins(5, 5, 5, 5)

        # Frame step back
        self._step_back_btn = QPushButton("◀")
        self._step_back_btn.setFixedWidth(28)
        self._step_back_btn.setToolTip("Step back 1 frame (← arrow)")
        self._step_back_btn.clicked.connect(
            lambda: self.frame_step_requested.emit(-1)
        )
        self.layout().addWidget(self._step_back_btn)

        # Play / Pause
        self.play_btn = QPushButton("Play")
        self.play_btn.setCheckable(True)
        self.play_btn.clicked.connect(self._on_play_clicked)
        self.layout().addWidget(self.play_btn)

        # Frame step forward
        self._step_fwd_btn = QPushButton("▶")
        self._step_fwd_btn.setFixedWidth(28)
        self._step_fwd_btn.setToolTip("Step forward 1 frame (→ arrow)")
        self._step_fwd_btn.clicked.connect(
            lambda: self.frame_step_requested.emit(1)
        )
        self.layout().addWidget(self._step_fwd_btn)

        # Unified time display / jump input
        # Editable: type a time and press Enter to jump.
        # Otherwise shows the current playhead position.
        mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        self._time_edit = QLineEdit("00:00:00.000")
        self._time_edit.setFixedWidth(110)
        self._time_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time_edit.setStyleSheet(
            f"font-family: '{mono_font}'; font-size: 12px;"
        )
        self._time_edit.setToolTip(
            "Current time — click to edit.\n"
            "Formats: HH:MM:SS.fff, MM:SS, or seconds."
        )
        self._time_edit.returnPressed.connect(self._on_jump)
        self._time_edit.editingFinished.connect(self._on_editing_done)
        self._time_editing = False
        self._time_edit.textEdited.connect(self._on_text_edited)
        self.layout().addWidget(self._time_edit)

        # Scrub slider
        self.slider = JumpSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 10000)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.layout().addWidget(self.slider)

        # A/B loop buttons
        self._ab_in_btn = QPushButton("[")
        self._ab_in_btn.setFixedWidth(24)
        self._ab_in_btn.setToolTip("Set loop in-point here")
        self._ab_in_btn.clicked.connect(self._on_ab_in)
        self.layout().addWidget(self._ab_in_btn)

        self._ab_out_btn = QPushButton("]")
        self._ab_out_btn.setFixedWidth(24)
        self._ab_out_btn.setToolTip("Set loop out-point here")
        self._ab_out_btn.clicked.connect(self._on_ab_out)
        self.layout().addWidget(self._ab_out_btn)

        self._ab_clear_btn = QPushButton("✕")
        self._ab_clear_btn.setFixedWidth(24)
        self._ab_clear_btn.setToolTip("Clear A/B loop")
        self._ab_clear_btn.clicked.connect(self._on_ab_clear)
        self.layout().addWidget(self._ab_clear_btn)

        # Rate combo — 0.01x to 10x
        self.rate_combo = QComboBox()
        for r in [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 10.0]:
            label = f"{r}x" if r >= 0.1 else f"{r:.2f}x"
            self.rate_combo.addItem(label, r)
        self.rate_combo.setCurrentText("1.0x")
        self.rate_combo.currentIndexChanged.connect(
            self._on_rate_changed
        )
        self.layout().addWidget(self.rate_combo)

        self._bounds = (0.0, 0.0)
        self._is_scrubbing = False
        self._ab_in_t: float | None = None
        self._ab_out_t: float | None = None

        # Overlay pins for A/B markers
        self._pin_in = _ABPin("#2a9d8f", self)
        self._pin_out = _ABPin("#e76f51", self)

    # ── Public API ────────────────────────────────────────────────────

    def set_bounds(self, t0: float, t1: float) -> None:
        self._bounds = (t0, t1)

    def set_time(self, t: float) -> None:
        """Update the displayed time (unless the user is typing)."""
        if not self._time_editing:
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = t % 60
            self._time_edit.setText(f"{h:02d}:{m:02d}:{s:06.3f}")

        if not self._is_scrubbing:
            duration = self._bounds[1] - self._bounds[0]
            if duration > 0:
                val = int(
                    (t - self._bounds[0]) / duration * 10000
                )
                val = max(0, min(10000, val))
                self.slider.blockSignals(True)
                self.slider.setValue(val)
                self.slider.blockSignals(False)

    def set_playing(self, playing: bool) -> None:
        self.play_btn.blockSignals(True)
        self.play_btn.setChecked(playing)
        self.play_btn.setText("Pause" if playing else "Play")
        self.play_btn.blockSignals(False)

    # ── Internal helpers ──────────────────────────────────────────────

    def _t_from_slider(self, val: int) -> float:
        duration = self._bounds[1] - self._bounds[0]
        return self._bounds[0] + (val / 10000.0) * duration

    def _slider_frac(self) -> float:
        span = max(1, self.slider.maximum() - self.slider.minimum())
        return (
            (self.slider.value() - self.slider.minimum()) / span
        )

    # ── Slots ─────────────────────────────────────────────────────────

    def _on_play_clicked(self, checked: bool) -> None:
        self.play_toggled.emit(checked)
        self.set_playing(checked)

    def _on_slider_pressed(self) -> None:
        self._is_scrubbing = True
        self.seek_requested.emit(
            self._t_from_slider(self.slider.value()), False
        )

    def _on_slider_moved(self, val: int) -> None:
        self.seek_requested.emit(self._t_from_slider(val), False)

    def _on_slider_released(self) -> None:
        self._is_scrubbing = False
        self.seek_requested.emit(
            self._t_from_slider(self.slider.value()), True
        )

    def _on_rate_changed(self, idx: int) -> None:
        rate = self.rate_combo.currentData()
        self.rate_changed.emit(rate)

    def _on_text_edited(self, _text: str) -> None:
        self._time_editing = True

    def _on_editing_done(self) -> None:
        self._time_editing = False

    def _on_ab_in(self) -> None:
        self._ab_in_t = self._t_from_slider(self.slider.value())
        self._pin_in.pin_to_slider(
            self.slider, self._slider_frac()
        )
        self.ab_loop_changed.emit(self._ab_in_t, self._ab_out_t)

    def _on_ab_out(self) -> None:
        self._ab_out_t = self._t_from_slider(self.slider.value())
        self._pin_out.pin_to_slider(
            self.slider, self._slider_frac()
        )
        self.ab_loop_changed.emit(self._ab_in_t, self._ab_out_t)

    def _on_ab_clear(self) -> None:
        self._ab_in_t = None
        self._ab_out_t = None
        self._pin_in.hide()
        self._pin_out.hide()
        self.ab_loop_changed.emit(None, None)

    def _on_jump(self) -> None:
        text = self._time_edit.text().strip()
        if not text:
            return
        t = self._parse_time_input(text)
        if t is not None:
            clamped = max(
                self._bounds[0], min(self._bounds[1], t)
            )
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
