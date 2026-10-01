"""Choose sensor-triggered windows for a comparison-grid video export."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.channel_reader import MappedChannelReader
from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.stimulus_grid_export import MAX_GRID_EVENTS
from avialsync.engine.stimulus_grid_worker import StimulusEventScanWorker
from avialsync.ui.i18n import tr
from avialsync.ui.playback_rates import PLAYBACK_RATE_STEPS, rate_label


@dataclass(frozen=True)
class StimulusChannelOption:
    """A visible channel and the worker-safe reference that reads it."""

    label: str
    reference: ReaderReference
    reader: MappedChannelReader


class StimulusGridDialog(QDialog):
    """Inspect a sensor timeline and choose event-aligned video windows."""

    scan_requested = Signal(object)

    def __init__(
        self, channels: list[StimulusChannelOption], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Export Stimulus Grid"))
        self.setMinimumSize(820, 640)
        self._channels = channels
        self._events: tuple[float, ...] = ()
        self._scan_worker: StimulusEventScanWorker | None = None
        self._updating_events = False

        layout = QVBoxLayout(self)
        intro = QLabel(
            tr(
                "Choose a sensor channel and rising threshold, review the detected events, "
                "then export selected windows as an aligned camera grid."
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        scan_form = QFormLayout()
        self.channel_combo = QComboBox(self)
        self.channel_combo.setAccessibleName(tr("Stimulus sensor channel"))
        self.channel_combo.setAccessibleDescription(tr("Choose the channel used to find stimuli"))
        for channel in channels:
            self.channel_combo.addItem(channel.label)
        self.threshold_spin = QDoubleSpinBox(self)
        self.threshold_spin.setRange(-1_000_000_000, 1_000_000_000)
        self.threshold_spin.setDecimals(6)
        self.threshold_spin.setSingleStep(0.1)
        self.threshold_spin.setValue(0.5)
        self.threshold_spin.setKeyboardTracking(False)
        self.threshold_spin.setAccessibleName(tr("Rising threshold"))
        self.threshold_spin.setAccessibleDescription(
            tr("An event starts when the sensor signal crosses this value upward")
        )
        self.min_interval_spin = QDoubleSpinBox(self)
        self.min_interval_spin.setRange(0, 600)
        self.min_interval_spin.setDecimals(3)
        self.min_interval_spin.setSingleStep(0.01)
        self.min_interval_spin.setValue(0.05)
        self.min_interval_spin.setSuffix(tr(" s"))
        self.min_interval_spin.setKeyboardTracking(False)
        self.min_interval_spin.setAccessibleName(tr("Minimum event spacing"))
        self.min_interval_spin.setAccessibleDescription(
            tr("Ignore repeated rising edges closer together than this interval")
        )
        scan_controls = QHBoxLayout()
        self.scan_button = QPushButton(tr("Scan events"), self)
        self.scan_button.setAccessibleName(tr("Scan for stimulus events"))
        self.scan_button.clicked.connect(self._scan)
        self.cancel_scan_button = QPushButton(tr("Cancel scan"), self)
        self.cancel_scan_button.setAccessibleName(tr("Cancel stimulus event scan"))
        self.cancel_scan_button.setVisible(False)
        self.cancel_scan_button.clicked.connect(self._cancel_scan)
        scan_controls.addWidget(self.scan_button)
        scan_controls.addWidget(self.cancel_scan_button)
        scan_form.addRow(tr("Sensor channel"), self.channel_combo)
        scan_form.addRow(tr("Rising threshold"), self.threshold_spin)
        scan_form.addRow(tr("Minimum spacing"), self.min_interval_spin)
        scan_form.addRow(tr("Detection"), scan_controls)
        layout.addLayout(scan_form)

        self.timeline = pg.PlotWidget(self)
        self.timeline.setAccessibleName(tr("Stimulus sensor timeline"))
        self.timeline.setAccessibleDescription(
            tr("Decimated sensor trace with detected event locations")
        )
        self.timeline.setMinimumHeight(170)
        self.timeline.setLabel("bottom", tr("Master time"), units="s")
        self.timeline.setLabel("left", tr("Sensor value"))
        layout.addWidget(self.timeline)

        self.event_table = QTableWidget(0, 2, self)
        self.event_table.setHorizontalHeaderLabels([tr("Use"), tr("Event time (s)")])
        self.event_table.horizontalHeader().setStretchLastSection(True)
        self.event_table.verticalHeader().hide()
        self.event_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.event_table.setAccessibleName(tr("Detected stimulus events"))
        self.event_table.setAccessibleDescription(
            tr("Select up to {count} events to compare").format(count=MAX_GRID_EVENTS)
        )
        layout.addWidget(self.event_table, 1)

        self.event_details = QLabel(tr("Scan the channel to see the first event and its window."))
        self.event_details.setWordWrap(True)
        self.event_details.setAccessibleName(tr("First selected event details"))
        layout.addWidget(self.event_details)
        self.scan_status = QLabel("")
        self.scan_status.setWordWrap(True)
        layout.addWidget(self.scan_status)

        window_form = QFormLayout()
        self.before_spin = self._seconds_spin(0, 600, 0.5, tr("Time before stimulus"))
        self.after_spin = self._seconds_spin(0.001, 600, 1.5, tr("Time after stimulus"))
        self.fps_spin = QSpinBox(self)
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(30)
        self.fps_spin.setSuffix(tr(" fps"))
        self.fps_spin.setAccessibleName(tr("Base output frame rate"))
        self.fps_spin.setAccessibleDescription(
            tr("Additional frames preserve every camera frame transition at its mapped time")
        )
        self.speed_combo = QComboBox(self)
        self.speed_combo.setAccessibleName(tr("Export playback speed"))
        self.speed_combo.setAccessibleDescription(
            tr("Select a playback speed preset or choose Custom to enter a precise speed")
        )
        for rate in PLAYBACK_RATE_STEPS:
            self.speed_combo.addItem(rate_label(rate), rate)
        self.speed_combo.addItem(tr("Custom…"), None)
        self.speed_combo.setCurrentIndex(PLAYBACK_RATE_STEPS.index(1.0))
        self.custom_speed_spin = QDoubleSpinBox(self)
        self.custom_speed_spin.setRange(0.01, 10.0)
        self.custom_speed_spin.setDecimals(6)
        self.custom_speed_spin.setSingleStep(0.01)
        self.custom_speed_spin.setValue(1.0)
        self.custom_speed_spin.setSuffix(tr("x"))
        self.custom_speed_spin.setKeyboardTracking(False)
        self.custom_speed_spin.setAccessibleName(tr("Custom export playback speed"))
        self.custom_speed_spin.setAccessibleDescription(
            tr("Source seconds played per output second, from 0.01 to 10")
        )
        self.custom_speed_spin.hide()
        speed_controls = QWidget(self)
        speed_layout = QHBoxLayout(speed_controls)
        speed_layout.setContentsMargins(0, 0, 0, 0)
        speed_layout.addWidget(self.speed_combo)
        speed_layout.addWidget(self.custom_speed_spin)
        window_form.addRow(tr("Before"), self.before_spin)
        window_form.addRow(tr("After"), self.after_spin)
        window_form.addRow(tr("Base frame rate"), self.fps_spin)
        window_form.addRow(tr("Playback speed"), speed_controls)
        layout.addLayout(window_form)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Continue to export"))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.channel_combo.currentIndexChanged.connect(self._channel_changed)
        self.threshold_spin.valueChanged.connect(self._detection_settings_changed)
        self.min_interval_spin.valueChanged.connect(self._detection_settings_changed)
        self.before_spin.valueChanged.connect(self._window_changed)
        self.after_spin.valueChanged.connect(self._window_changed)
        self.speed_combo.currentIndexChanged.connect(self._speed_changed)
        self.custom_speed_spin.valueChanged.connect(self._window_changed)
        self.event_table.itemChanged.connect(self._event_selection_changed)
        self._refresh_timeline()

    def _seconds_spin(
        self, minimum: float, maximum: float, value: float, accessible_name: str
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox(self)
        spin.setRange(minimum, maximum)
        spin.setDecimals(3)
        spin.setSingleStep(0.1)
        spin.setValue(value)
        spin.setSuffix(tr(" s"))
        spin.setKeyboardTracking(False)
        spin.setAccessibleName(accessible_name)
        return spin

    def channel_option(self) -> StimulusChannelOption:
        """Return the currently selected signal and its worker reference."""
        return self._channels[self.channel_combo.currentIndex()]

    def selected_events(self) -> tuple[float, ...]:
        """Return checked event times in chronological order."""
        selected: list[float] = []
        for row in range(self.event_table.rowCount()):
            check = self.event_table.item(row, 0)
            value = self.event_table.item(row, 1)
            if (
                check is not None
                and value is not None
                and check.checkState() == Qt.CheckState.Checked
            ):
                selected.append(float(cast(float, value.data(Qt.ItemDataRole.UserRole))))
        return tuple(selected)

    def playback_speed(self) -> float:
        """Return the selected source-time multiplier for the encoded movie."""
        preset = self.speed_combo.currentData()
        return self.custom_speed_spin.value() if preset is None else float(preset)

    @Slot()
    def _scan(self) -> None:
        self._clear_events()
        worker = StimulusEventScanWorker(
            self.channel_option().reference,
            self.threshold_spin.value(),
            self.min_interval_spin.value(),
        )
        self._scan_worker = worker
        self._set_scanning(True)
        self.scan_status.setText(tr("Scanning the selected channel…"))
        self.scan_requested.emit(worker)

    @Slot()
    def _cancel_scan(self) -> None:
        if self._scan_worker is not None:
            self._scan_worker.cancel()
            self.scan_status.setText(tr("Cancelling event scan…"))

    @Slot(object)
    def set_events(self, value: object) -> None:
        """Display completed event times and select the first event by default."""
        if not isinstance(value, (tuple, list)):
            self.set_scan_error("")
            return
        self._events = tuple(float(time) for time in value)
        self._updating_events = True
        self.event_table.setRowCount(len(self._events))
        for row, event_time in enumerate(self._events):
            use = QTableWidgetItem()
            use.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            use.setCheckState(
                Qt.CheckState.Checked if row < MAX_GRID_EVENTS else Qt.CheckState.Unchecked
            )
            time_item = QTableWidgetItem(f"{event_time:.6f}")
            time_item.setData(Qt.ItemDataRole.UserRole, event_time)
            time_item.setFlags(time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.event_table.setItem(row, 0, use)
            self.event_table.setItem(row, 1, time_item)
        self._updating_events = False
        self._scan_worker = None
        self._set_scanning(False)
        if self._events:
            self.scan_status.setText(
                tr("Found {count} rising events. Select up to {limit}.").format(
                    count=len(self._events), limit=MAX_GRID_EVENTS
                )
            )
        else:
            self.scan_status.setText(tr("No rising events found at this threshold."))
        self._event_selection_changed()

    @Slot(str)
    def set_scan_error(self, _message: str) -> None:
        """Show a plain-language scan failure without exposing worker details."""
        self._scan_worker = None
        self._set_scanning(False)
        self.scan_status.setText(
            tr("The channel could not be scanned. Check the source and retry.")
        )

    @Slot()
    def set_scan_cancelled(self) -> None:
        self._scan_worker = None
        self._set_scanning(False)
        self.scan_status.setText(tr("Event scan cancelled."))

    def _set_scanning(self, scanning: bool) -> None:
        self.scan_button.setEnabled(not scanning)
        self.cancel_scan_button.setVisible(scanning)
        self.channel_combo.setEnabled(not scanning)
        self.threshold_spin.setEnabled(not scanning)
        self.min_interval_spin.setEnabled(not scanning)

    def _clear_events(self) -> None:
        self._events = ()
        self._updating_events = True
        self.event_table.setRowCount(0)
        self._updating_events = False
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.event_details.setText(tr("Scan the channel to see the first event and its window."))
        self._refresh_timeline()

    @Slot(int)
    def _channel_changed(self, _index: int) -> None:
        self._clear_events()
        self._refresh_timeline()

    @Slot(float)
    def _detection_settings_changed(self, _value: float) -> None:
        self._clear_events()

    @Slot(float)
    def _window_changed(self, _value: float) -> None:
        self._update_event_details(self.selected_events())

    @Slot(int)
    def _speed_changed(self, _index: int) -> None:
        preset = self.speed_combo.currentData()
        if preset is not None:
            self.custom_speed_spin.setValue(float(preset))
        self.custom_speed_spin.setVisible(preset is None)
        self._update_event_details(self.selected_events())

    @Slot()
    def _event_selection_changed(self, _item: QTableWidgetItem | None = None) -> None:
        if self._updating_events:
            return
        selected = self.selected_events()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(selected))
        if len(selected) > MAX_GRID_EVENTS:
            self._updating_events = True
            if _item is not None and _item.checkState() == Qt.CheckState.Checked:
                _item.setCheckState(Qt.CheckState.Unchecked)
            self._updating_events = False
            selected = self.selected_events()
            self.scan_status.setText(
                tr("Choose no more than {count} events.").format(count=MAX_GRID_EVENTS)
            )
        self._update_event_details(selected)
        self._refresh_timeline()

    def _update_event_details(self, selected: tuple[float, ...]) -> None:
        if not selected:
            self.event_details.setText(
                tr("Scan the channel to see the first event and its window.")
            )
            return
        event_time = selected[0]
        start, end = event_time - self.before_spin.value(), event_time + self.after_spin.value()
        speed = self.playback_speed()
        output_duration = (self.before_spin.value() + self.after_spin.value()) / speed
        self.event_details.setText(
            tr(
                "First selected event: {time:.6f} s. Export window: {start:.6f} to {end:.6f} s. "
                "Video length: {duration:.2f} s at {speed:g}x."
            ).format(time=event_time, start=start, end=end, duration=output_duration, speed=speed)
        )

    def _refresh_timeline(self) -> None:
        self.timeline.clear()
        if not self._channels:
            return
        reader = self.channel_option().reader
        bounds = reader.coverage()
        if bounds is None or bounds[1] <= bounds[0]:
            return
        times, low, high, gaps = reader.query(*bounds, max_points=1200)
        if len(times):
            low_values = np.asarray(low, dtype=np.float64).copy()
            high_values = np.asarray(high, dtype=np.float64).copy()
            gap_mask = np.asarray(gaps, dtype=bool)
            low_values[gap_mask] = np.nan
            high_values[gap_mask] = np.nan
            self.timeline.plot(times, low_values, pen=pg.mkPen("#3d806c", width=1))
            self.timeline.plot(times, high_values, pen=pg.mkPen("#65b39b", width=1))
            self.timeline.setXRange(bounds[0], bounds[1], padding=0.01)
        threshold = pg.InfiniteLine(
            pos=self.threshold_spin.value(), angle=0, pen=pg.mkPen("#d78342", width=1)
        )
        self.timeline.addItem(threshold)
        selected = self.selected_events()
        if selected:
            values = [reader.value_at(event_time) for event_time in selected]
            markers = pg.ScatterPlotItem(
                x=list(selected), y=values, symbol="t1", size=10, pen=None, brush="#ef665d"
            )
            self.timeline.addItem(markers)
            self.timeline.addItem(
                pg.InfiniteLine(pos=selected[0], angle=90, pen=pg.mkPen("#ef665d", width=2))
            )

    def reject(self) -> None:
        if self._scan_worker is not None:
            self._scan_worker.cancel()
        super().reject()
