"""Capture corresponding observed events through the single master clock."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.video_timing import frame_index_at
from avialsync.engine.sync_worker import EventEvidenceSpec, EvidenceSpec
from avialsync.ui.i18n import tr
from avialsync.ui.tables import ThemedTable

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow
    from avialsync.ui.sync_wizard import SyncWizard


def visual_evidence(window: MainWindow) -> list[EvidenceSpec]:
    """All placeable source clocks as candidates for explicit visual correspondence."""
    from avialsync.ui.sync_acceptance import collect_sync_evidence
    from avialsync.ui.sync_lifecycle import source_mapping

    _, targets = collect_sync_evidence(window)
    kept: dict[str, EvidenceSpec] = {}
    for spec in targets:
        mapping = source_mapping(window, spec.source_id)
        if mapping is not None and spec.source_id not in kept:
            kept[spec.source_id] = dataclasses.replace(spec, accepted_mapping=mapping.copy())
    return list(kept.values())


class LandmarkPanel(QWidget):
    """Collect pairs without moving a recording or making an implicit match."""

    changed = Signal()

    def __init__(self, wizard: SyncWizard) -> None:
        super().__init__(wizard)
        self._wizard = wizard
        self._pairs: list[tuple[float, float]] = []
        layout = QVBoxLayout(self)
        note = QLabel(
            tr(
                "Scrub to the same event in each recording and capture each time, "
                "then add the pair. Use separated events to measure drift."
            ),
            self,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.reference_time = self._time(tr("Reference event time"))
        self.target_time = self._time(tr("Target event time"))
        form.addRow(tr("Reference time (s):"), self.reference_time)
        form.addRow(tr("Target time (s):"), self.target_time)
        self.resolution = self._time(tr("Visual observation resolution"))
        self.resolution.setRange(0.000001, 10.0)
        self.resolution.setValue(1.0 / 30.0)
        form.addRow(tr("Observation resolution (s):"), self.resolution)
        self.resolution.valueChanged.connect(self.changed)
        layout.addLayout(form)
        captures = QHBoxLayout()
        for text, reference in ((tr("Capture reference"), True), (tr("Capture target"), False)):
            button = QPushButton(text, self)
            button.setAccessibleName(text)
            button.setAccessibleDescription(
                tr("Use this recording's frame or sample time at the current playhead.")
            )
            button.clicked.connect(lambda _checked=False, ref=reference: self.capture(ref))
            captures.addWidget(button)
        layout.addLayout(captures)
        self.table = ThemedTable(0, 2, self)
        self.table.setHorizontalHeaderLabels([tr("Reference (s)"), tr("Target (s)")])
        self.table.setAccessibleName(tr("Corresponding observed events"))
        self.table.setAccessibleDescription(
            tr("Each row is one event explicitly paired between recordings.")
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(100)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        for text, action in (
            (tr("Add pair"), self.add_pair),
            (tr("Remove selected pair"), self.remove_pair),
        ):
            button = QPushButton(text, self)
            button.setAccessibleName(text)
            button.setAccessibleDescription(tr("Change the explicitly paired visual evidence."))
            button.clicked.connect(action)
            row.addWidget(button)
        layout.addLayout(row)

    def _time(self, label: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox(self)
        spin.setRange(-1e12, 1e12)
        spin.setDecimals(6)
        spin.setKeyboardTracking(False)
        spin.setAccessibleName(label)
        spin.setAccessibleDescription(tr("Time in this recording's original clock, in seconds."))
        return spin

    def capture(self, reference: bool) -> None:
        """Read the playhead, using the actual stored frame where available."""
        from avialsync.ui.sync_lifecycle import as_window

        parent = as_window(self._wizard.parentWidget())
        if parent is None or not hasattr(parent, "clock"):
            self._wizard._status.setText(
                tr(
                    "Enter event times, or open alignment from the recording window "
                    "to capture them."
                )
            )
            return
        from avialsync.ui.sync_lifecycle import source_mapping

        specs = self._wizard._references if reference else self._wizard._targets
        combo = self._wizard._reference_combo if reference else self._wizard._target_combo
        if not specs:
            return
        spec = specs[combo.currentIndex()]
        mapping = source_mapping(parent, spec.clock_id or spec.source_id)
        if mapping is None:
            return
        raw_time = mapping.to_source(parent.clock.state.t)
        if isinstance(spec, EventEvidenceSpec) and spec.is_frame_time_axis and len(spec.times):
            if raw_time < spec.times[0] or raw_time > spec.times[-1]:
                self._wizard._status.setText(
                    tr("Seek inside this recording before capturing its event.")
                )
                return
            raw_time = float(spec.times[frame_index_at(spec.times, raw_time)])
        (self.reference_time if reference else self.target_time).setValue(raw_time)

    def add_pair(self) -> None:
        """Keep the person's correspondence in its original time domains."""
        self._pairs.append((self.reference_time.value(), self.target_time.value()))
        self._pairs.sort()
        self._redraw()

    def remove_pair(self) -> None:
        """Remove only the selected pair."""
        index = self.table.currentRow()
        if 0 <= index < len(self._pairs):
            self._pairs.pop(index)
            self._redraw()

    def clear(self) -> None:
        """Pairs belong to the selected sources and never transfer to another pair."""
        self._pairs.clear()
        self._redraw()

    def pairs(self) -> tuple[tuple[float, float], ...]:
        """Return the explicitly paired raw timestamps."""
        return tuple(self._pairs)

    def _redraw(self) -> None:
        self.table.setRowCount(len(self._pairs))
        for row, pair in enumerate(self._pairs):
            for column, value in enumerate(pair):
                self.table.setItem(row, column, QTableWidgetItem(f"{value:.6f}"))
        self.changed.emit()
