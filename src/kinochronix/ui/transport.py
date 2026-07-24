"""Playback transport controls."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)
from PySide6.QtGui import QMouseEvent


class JumpSlider(QSlider):
    """A QSlider that instantly jumps to the clicked position."""

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            val = self.minimum() + ((self.maximum() - self.minimum()) * event.position().x()) / self.width()
            self.setValue(int(val))
        super().mousePressEvent(event)


class Transport(QWidget):
    """Transport bar with play/pause, scrub slider, and rate control."""

    play_toggled = Signal(bool)
    seek_requested = Signal(float, bool)  # t, exact
    rate_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setLayout(QHBoxLayout())
        self.layout().setContentsMargins(5, 5, 5, 5)

        self.play_btn = QPushButton("Play")
        self.play_btn.setCheckable(True)
        self.play_btn.clicked.connect(self._on_play_clicked)
        self.layout().addWidget(self.play_btn)

        self.time_lbl = QLabel("00:00:00.00")
        self.layout().addWidget(self.time_lbl)

        self.slider = JumpSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 10000)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.layout().addWidget(self.slider)

        self.rate_combo = QComboBox()
        for r in [0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0]:
            self.rate_combo.addItem(f"{r}x", r)
        self.rate_combo.setCurrentText("1.0x")
        self.rate_combo.currentIndexChanged.connect(self._on_rate_changed)
        self.layout().addWidget(self.rate_combo)

        self._bounds = (0.0, 0.0)
        self._is_scrubbing = False

    def set_bounds(self, t0: float, t1: float) -> None:
        """Set the absolute time bounds of the slider."""
        self._bounds = (t0, t1)

    def set_time(self, t: float) -> None:
        """Update the UI to reflect the current time."""
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        self.time_lbl.setText(f"{h:02d}:{m:02d}:{s:05.2f}")

        if not self._is_scrubbing:
            duration = self._bounds[1] - self._bounds[0]
            if duration > 0:
                val = int((t - self._bounds[0]) / duration * 10000)
                # clamp
                val = max(0, min(10000, val))
                # block signals so we don't trigger scrub events programmatically
                self.slider.blockSignals(True)
                self.slider.setValue(val)
                self.slider.blockSignals(False)

    def set_playing(self, playing: bool) -> None:
        self.play_btn.blockSignals(True)
        self.play_btn.setChecked(playing)
        self.play_btn.setText("Pause" if playing else "Play")
        self.play_btn.blockSignals(False)

    def _t_from_slider(self, val: int) -> float:
        duration = self._bounds[1] - self._bounds[0]
        return self._bounds[0] + (val / 10000.0) * duration

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
