"""Shared fixed-window sweep state and controls for time-series plots."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QWidget,
)


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
        if clip_width <= 0.0:
            return
        if self._sweep_position >= bounds.right():
            super().paint(painter, option, widget)
            return
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
    """One bounded duration control and deterministic sweep calculator."""

    window_changed = Signal(float)

    _SLIDER_STEPS = 2000
    _MIN_WINDOW_SECONDS = 0.001
    _DEFAULT_WINDOW_SECONDS = 10.0
    _DRAG_REFRESH_MS = 33
    _UNITS = (("ms", 0.001), ("s", 1.0), ("min", 60.0), ("h", 3600.0))

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bounds = (0.0, 0.0)
        self._window_seconds = self._DEFAULT_WINDOW_SECONDS
        self._limit_seconds = self._DEFAULT_WINDOW_SECONDS
        self._last_master_t = 0.0
        self._sweep_start: float | None = None
        self._pending_window_seconds: float | None = None
        self._slider_drag_active = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.addWidget(QLabel("Window limit", self))

        self.limit_spin = QDoubleSpinBox(self)
        self.limit_spin.setDecimals(3)
        self.limit_spin.setRange(0.001, 999_999.0)
        self.limit_spin.setSingleStep(1.0)
        self.limit_spin.setKeyboardTracking(False)
        self.limit_spin.setAccessibleName("Shared plot window limit")
        self.limit_spin.setToolTip("Maximum duration available on the shared window slider")
        self.limit_spin.setValue(self._DEFAULT_WINDOW_SECONDS)
        self.limit_spin.valueChanged.connect(self._on_limit_value_changed)
        layout.addWidget(self.limit_spin)

        self.unit_combo = QComboBox(self)
        for label, seconds in self._UNITS:
            self.unit_combo.addItem(label, seconds)
        self.unit_combo.setCurrentText("s")
        self.unit_combo.setAccessibleName("Shared plot window limit unit")
        self.unit_combo.setToolTip("Choose milliseconds, seconds, minutes, or hours")
        self.unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        layout.addWidget(self.unit_combo)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(1, self._SLIDER_STEPS)
        self.slider.setAccessibleName("Shared plot window slider")
        self.slider.setToolTip(
            "Shared oscilloscope window for every plot; drag within the selected limit"
        )
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.slider, 1)
        self.value_label = QLabel(self._format_window(self._window_seconds), self)
        self.value_label.setMinimumWidth(72)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.value_label)
        self.slider.setEnabled(False)

        self._drag_timer = QTimer(self)
        self._drag_timer.setSingleShot(True)
        self._drag_timer.setInterval(self._DRAG_REFRESH_MS)
        self._drag_timer.timeout.connect(self._commit_pending_window)

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
        self._pending_window_seconds = None
        self._drag_timer.stop()
        first_bounds = self._timeline_duration() <= 0
        self._bounds = (t0, t1)
        total = self._timeline_duration()
        if first_bounds and total > 0:
            self._window_seconds = min(
                max(self._window_seconds, self._minimum_window()),
                total,
            )
            self._last_master_t = t0
        elif total > 0:
            self._window_seconds = min(self._window_seconds, total)
        self._sweep_start = None
        self._sync_widgets()
        self.window_changed.emit(self._window_seconds)

    def set_window_duration(self, seconds: float) -> None:
        """Set and emit a duration clamped to the current master bounds."""
        if not math.isfinite(seconds):
            raise ValueError("Plot window duration must be finite")
        self._pending_window_seconds = None
        self._drag_timer.stop()
        if seconds > self._limit_seconds:
            self._set_limit_seconds(seconds)
        self._commit_window(seconds)

    def reset_window(self) -> None:
        """Expand the sweep to the complete master timeline."""
        total = self._timeline_duration()
        if total > 0:
            if total > self._limit_seconds:
                self._set_limit_seconds(total)
            self._commit_window(total)

    def zoom_in(self) -> None:
        """Move the continuous slider one small step inward."""
        self.slider.setValue(max(self.slider.minimum(), self.slider.value() - 50))

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
        """Map a duration linearly within the user-selected limit."""
        minimum = self._minimum_window()
        maximum = self._maximum_window()
        if maximum <= minimum or seconds <= minimum:
            return 1
        fraction = (seconds - minimum) / (maximum - minimum)
        usable_steps = self._SLIDER_STEPS - 1
        return 1 + round(max(0.0, min(1.0, fraction)) * usable_steps)

    def _timeline_duration(self) -> float:
        return max(0.0, self._bounds[1] - self._bounds[0])

    def _minimum_window(self) -> float:
        maximum = self._maximum_window()
        return min(self._MIN_WINDOW_SECONDS, maximum) if maximum > 0 else 0.0

    def _maximum_window(self) -> float:
        total = self._timeline_duration()
        return min(self._limit_seconds, total) if total > 0 else self._limit_seconds

    def _duration_from_slider(self, value: int) -> float:
        minimum = self._minimum_window()
        maximum = self._maximum_window()
        if maximum <= minimum:
            return maximum
        usable_steps = self._SLIDER_STEPS - 1
        fraction = (value - 1) / usable_steps
        return minimum + fraction * (maximum - minimum)

    def _on_slider_changed(self, value: int) -> None:
        duration = self._duration_from_slider(value)
        if duration <= 0:
            return
        self._pending_window_seconds = duration
        self.value_label.setText(self._format_window(duration))
        if self._slider_drag_active:
            if not self._drag_timer.isActive():
                self._drag_timer.start()
        else:
            self._commit_pending_window()

    def _on_slider_pressed(self) -> None:
        self._slider_drag_active = True

    def _on_slider_released(self) -> None:
        self._slider_drag_active = False
        self._drag_timer.stop()
        self._commit_pending_window()

    def _commit_pending_window(self) -> None:
        duration = self._pending_window_seconds
        self._pending_window_seconds = None
        if duration is not None:
            self._commit_window(duration)

    def _commit_window(self, seconds: float) -> None:
        maximum = self._maximum_window()
        duration = min(seconds, maximum) if maximum > 0 else seconds
        duration = max(self._minimum_window(), duration)
        changed = not math.isclose(duration, self._window_seconds, abs_tol=1e-12)
        if not changed:
            self._sync_widgets()
            return
        self._window_seconds = duration
        self._sweep_start = None
        self._sync_widgets()
        self.window_changed.emit(self._window_seconds)

    def _on_limit_value_changed(self, value: float) -> None:
        self._limit_seconds = value * self._unit_seconds()
        self._apply_limit_change()

    def _on_unit_changed(self, _index: int) -> None:
        self._limit_seconds = self.limit_spin.value() * self._unit_seconds()
        self._apply_limit_change()

    def _apply_limit_change(self) -> None:
        maximum = self._maximum_window()
        if maximum > 0 and self._window_seconds > maximum:
            self._commit_window(maximum)
        else:
            self._sync_widgets()

    def _set_limit_seconds(self, seconds: float) -> None:
        self._limit_seconds = max(self._MIN_WINDOW_SECONDS, seconds)
        unit_seconds = self._unit_seconds()
        self.limit_spin.blockSignals(True)
        self.limit_spin.setValue(self._limit_seconds / unit_seconds)
        self.limit_spin.blockSignals(False)

    def _unit_seconds(self) -> float:
        return float(self.unit_combo.currentData())

    def _sync_widgets(self) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(self.slider_from_duration(self._window_seconds))
        self.slider.blockSignals(False)
        self.slider.setEnabled(
            self._timeline_duration() > 0 and self._maximum_window() > self._minimum_window()
        )
        self.value_label.setText(self._format_window(self._window_seconds))

    def _format_window(self, seconds: float) -> str:
        unit = self.unit_combo.currentText()
        value = seconds / self._unit_seconds()
        if unit == "ms":
            return f"{value:.1f} ms"
        return f"{value:.3f} {unit}"
