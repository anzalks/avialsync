"""Shared fixed-window sweep state and controls for time-series plots."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget


class SweepCurveItem(pg.PlotCurveItem):
    """Curve whose already-decimated data is revealed by a moving sweep edge."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._sweep_position = 0.0

    def set_sweep_position(self, position: float) -> None:
        """Move the paint clip without rebuilding or re-querying curve data."""
        if math.isclose(position, self._sweep_position, abs_tol=1e-12):
            return
        self._sweep_position = position
        self.update()

    def paint(self, painter: Any, option: Any, widget: Any = None) -> None:
        """Paint only data at or left of the sweep edge."""
        bounds = self.boundingRect()
        clip_width = max(0.0, self._sweep_position - bounds.left())
        painter.save()
        try:
            painter.setClipRect(
                QRectF(bounds.left(), bounds.top(), clip_width, bounds.height()),
                Qt.ClipOperation.IntersectClip,
            )
            super().paint(painter, option, widget)
        finally:
            painter.restore()


@dataclass(frozen=True)
class SweepPosition:
    """Display position derived from one authoritative master-clock value."""

    start: float
    phase: float
    changed: bool


class SweepWindowControl(QWidget):
    """One continuous duration control and deterministic sweep calculator."""

    window_changed = Signal(float)

    _SLIDER_STEPS = 2000
    _MIN_WINDOW_SECONDS = 0.01
    _DEFAULT_WINDOW_SECONDS = 10.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bounds = (0.0, 0.0)
        self._window_seconds = self._DEFAULT_WINDOW_SECONDS
        self._last_master_t = 0.0
        self._sweep_start: float | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.addWidget(QLabel("Window", self))
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, self._SLIDER_STEPS)
        self.slider.setAccessibleName("Shared plot window slider")
        self.slider.setToolTip(
            "Shared oscilloscope window for every plot; drag for continuous X-axis zoom"
        )
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.slider, 1)
        self.value_label = QLabel(self._format_window(self._window_seconds), self)
        self.value_label.setMinimumWidth(72)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.value_label)
        self.slider.setEnabled(False)

    @property
    def window_duration(self) -> float:
        """Return the shared sweep duration in seconds."""
        return self._window_seconds

    @property
    def sweep_start(self) -> float | None:
        """Return the absolute master time at the current sweep's left edge."""
        return self._sweep_start

    @property
    def last_master_time(self) -> float:
        """Return the latest master-clock value supplied by the player."""
        return self._last_master_t

    def set_bounds(self, t0: float, t1: float) -> None:
        """Set master bounds and anchor all future sweeps to their start."""
        if t1 < t0:
            raise ValueError("Plot timeline bounds require t1 >= t0")
        first_bounds = self._timeline_duration() <= 0
        self._bounds = (t0, t1)
        total = self._timeline_duration()
        if first_bounds:
            self._window_seconds = min(self._window_seconds, total) if total > 0 else 0.0
            self._last_master_t = t0
        elif total > 0:
            self._window_seconds = min(self._window_seconds, total)
        self._sweep_start = None
        self.slider.setEnabled(total > self._minimum_window())
        self._sync_widgets()
        self.window_changed.emit(self._window_seconds)

    def set_window_duration(self, seconds: float) -> None:
        """Set and emit a duration clamped to the current master bounds."""
        total = self._timeline_duration()
        duration = min(seconds, total) if total > 0 else seconds
        self._window_seconds = max(self._minimum_window(), duration)
        self._sweep_start = None
        self._sync_widgets()
        self.window_changed.emit(self._window_seconds)

    def reset_window(self) -> None:
        """Expand the sweep to the complete master timeline."""
        total = self._timeline_duration()
        if total > 0:
            self.set_window_duration(total)

    def zoom_in(self) -> None:
        """Move the continuous slider one small step inward."""
        self.slider.setValue(max(0, self.slider.value() - 50))

    def zoom_out(self) -> None:
        """Move the continuous slider one small step outward."""
        self.slider.setValue(min(self._SLIDER_STEPS, self.slider.value() + 50))

    def advance(self, master_t: float) -> SweepPosition:
        """Derive the current sweep solely from a master-clock timestamp."""
        self._last_master_t = master_t
        duration = self._window_seconds
        if duration <= 0:
            return SweepPosition(0.0, 0.0, False)

        t0, t1 = self._bounds
        bounded_t = min(max(master_t, t0), t1) if t1 > t0 else master_t
        elapsed = max(0.0, bounded_t - t0)
        sweep_start = t0 + math.floor(elapsed / duration) * duration
        phase = bounded_t - sweep_start
        if bounded_t == t1 and elapsed > 0 and math.isclose(phase, 0.0, abs_tol=1e-9):
            sweep_start -= duration
            phase = duration

        changed = self._sweep_start is None or not math.isclose(
            sweep_start, self._sweep_start, abs_tol=1e-9
        )
        self._sweep_start = sweep_start
        return SweepPosition(sweep_start, phase, changed)

    def slider_from_duration(self, seconds: float) -> int:
        """Map a duration to the fine-grained logarithmic slider."""
        minimum = self._minimum_window()
        maximum = self._timeline_duration()
        if maximum <= minimum or seconds <= minimum:
            return 0
        fraction = math.log(seconds / minimum) / math.log(maximum / minimum)
        return round(max(0.0, min(1.0, fraction)) * self._SLIDER_STEPS)

    def _timeline_duration(self) -> float:
        return max(0.0, self._bounds[1] - self._bounds[0])

    def _minimum_window(self) -> float:
        total = self._timeline_duration()
        return min(self._MIN_WINDOW_SECONDS, total) if total > 0 else self._MIN_WINDOW_SECONDS

    def _duration_from_slider(self, value: int) -> float:
        minimum = self._minimum_window()
        maximum = self._timeline_duration()
        if maximum <= minimum:
            return maximum
        fraction = value / self._SLIDER_STEPS
        return math.exp(math.log(minimum) + fraction * math.log(maximum / minimum))

    def _on_slider_changed(self, value: int) -> None:
        duration = self._duration_from_slider(value)
        if duration > 0:
            self.set_window_duration(duration)

    def _sync_widgets(self) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(self.slider_from_duration(self._window_seconds))
        self.slider.blockSignals(False)
        self.value_label.setText(self._format_window(self._window_seconds))

    @staticmethod
    def _format_window(seconds: float) -> str:
        if seconds < 1.0:
            return f"{seconds * 1000:.1f} ms"
        if seconds < 100.0:
            return f"{seconds:.3f} s"
        return f"{seconds:.1f} s"
