"""Screen-bounded, contextual controls for the non-modal alignment dialog."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from avialsync.engine.sync_worker import EventEvidenceSpec, SignalEvidenceSpec
from avialsync.ui.about import docs_url
from avialsync.ui.i18n import tr
from avialsync.ui.step_panel import StepPanel

if TYPE_CHECKING:
    from avialsync.ui.sync_wizard import SyncWizard


def describe(widget: QWidget, name: str, help_text: str) -> None:
    """Give an interactive control a visible-in-context and accessible explanation."""
    widget.setAccessibleName(name)
    widget.setAccessibleDescription(help_text)
    widget.setToolTip(help_text)


def build_form(wizard: SyncWizard) -> None:
    """Reuse the fitting controls in a scrollable setup column with a fixed footer."""
    layout = QVBoxLayout(wizard)
    layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
    wizard._body = QSplitter(Qt.Orientation.Horizontal, wizard)
    wizard._body.setChildrenCollapsible(False)
    wizard._scroll = QScrollArea(wizard._body)
    wizard._scroll.setWidgetResizable(True)
    wizard._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    describe(
        wizard._scroll, tr("Alignment settings"), tr("Scroll to reach all alignment settings.")
    )
    setup = QWidget()
    setup.setMinimumWidth(0)
    setup.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    settings = QVBoxLayout(setup)
    settings.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
    wizard._selection_form = _selection(wizard, setup)
    settings.addLayout(wizard._selection_form)
    wizard._event_fields = QWidget(setup)
    wizard._event_fields.setLayout(wizard._evidence_form)
    settings.addWidget(wizard._event_fields)
    wizard._manual_fields = QGroupBox(tr("Manual adjustment"), setup)
    manual = QFormLayout(wizard._manual_fields)
    manual.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    manual.addRow(tr("Offset (positive moves earlier):"), wizard._manual_offset)
    manual.addRow(tr("Clock drift:"), wizard._manual_drift)
    settings.addWidget(wizard._manual_fields)
    settings.addWidget(wizard._landmarks)
    settings.addWidget(wizard._preview_button)
    settings.addWidget(wizard._manual_button)
    wizard.steps = StepPanel(tr("Fit settings and details"), setup)
    wizard.steps.set_instruction(tr("Advanced matching settings and detailed fit results."))
    wizard._advanced_form.addRow(wizard._summary)
    advanced = QWidget(setup)
    advanced.setLayout(wizard._advanced_form)
    wizard.steps.add_more(advanced)
    wizard.steps.set_learn_more(docs_url("tutorials/synchronization.html"))
    settings.addWidget(wizard.steps)
    settings.addStretch(1)
    wizard._scroll.setWidget(setup)
    wizard._body.addWidget(wizard._scroll)
    # A short screen must scroll the evidence instead of cropping its axis labels.
    evidence_scroll = QScrollArea(wizard._body)
    evidence_scroll.setWidgetResizable(True)
    evidence_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    describe(
        evidence_scroll, tr("Alignment evidence"), tr("Scroll to see the complete evidence view.")
    )
    evidence_scroll.setWidget(wizard._evidence)
    wizard._body.addWidget(evidence_scroll)
    wizard._body.setSizes([380, 620])
    layout.addWidget(wizard._body, 1)
    wizard._status = QLabel(tr("Choose recordings, then preview an alignment."), wizard)
    wizard._status.setWordWrap(True)
    wizard._status.setAccessibleName(tr("Alignment status"))
    layout.addWidget(wizard._status)
    layout.addWidget(wizard._buttons)
    _accessibility(wizard)


def _selection(wizard: SyncWizard, setup: QWidget) -> QFormLayout:
    selection = QFormLayout()
    selection.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    selection.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    wizard._mode_combo = QComboBox(setup)
    wizard._mode_combo.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    wizard._mode_combo.setMinimumContentsLength(12)
    for label, value in (
        (tr("Shared TTL / events"), "events"),
        (tr("Manual offset and drift"), "manual"),
        (tr("Corresponding visual events"), "landmarks"),
    ):
        wizard._mode_combo.addItem(label, value)
    selection.addRow(tr("Align using:"), wizard._mode_combo)
    selection.addRow(tr("Reference recording:"), wizard._reference_combo)
    selection.addRow(tr("Recording to move:"), wizard._target_combo)
    _source_choices(wizard)
    return selection


def _accessibility(wizard: SyncWizard) -> None:
    for widget, name, explanation in (
        (
            wizard._mode_combo,
            tr("Alignment method"),
            tr("Choose recorded events, manual values, or visual landmarks."),
        ),
        (
            wizard._reference_combo,
            tr("Reference recording"),
            tr("The recording whose timing is the reference."),
        ),
        (
            wizard._target_combo,
            tr("Recording to move"),
            tr("Only this recording moves when you accept the proposal."),
        ),
        (
            wizard._manual_offset,
            tr("Manual offset"),
            tr("Seconds added to source time. Positive moves the recording earlier."),
        ),
        (
            wizard._manual_drift,
            tr("Manual clock drift"),
            tr("Milliseconds the source clock gains per hour."),
        ),
    ):
        describe(widget, name, explanation)
    for control in wizard.findChildren(QWidget):
        if not isinstance(control, (QComboBox, QDoubleSpinBox, QSpinBox, QPushButton)):
            continue
        if not control.accessibleName():
            describe(
                control,
                control.toolTip() or tr("Alignment control"),
                control.toolTip() or tr("Adjust the alignment proposal before accepting."),
            )


def update_fields(wizard: SyncWizard) -> None:
    """Only ask questions the selected evidence can answer."""
    manual = wizard._mode_combo.currentData() == "manual"
    events = wizard._mode_combo.currentData() == "events"
    wizard._selection_form.setRowVisible(wizard._reference_combo, not manual)
    for control in (
        wizard._strategy_combo,
        wizard._tolerance,
        wizard._effective_tolerance,
        wizard._restrict,
    ):
        wizard._advanced_form.setRowVisible(control, events)
    wizard._advanced_form.setRowVisible(wizard._precision_requirement, not manual)
    wizard._landmarks.setVisible(wizard._mode_combo.currentData() == "landmarks")
    wizard._manual_fields.setVisible(manual)
    wizard._manual_button.setVisible(manual)
    wizard._event_fields.setVisible(events)
    wizard._preview_button.setVisible(not manual)
    reference = (
        wizard._references[wizard._reference_combo.currentIndex()] if wizard._references else None
    )
    target = wizard._targets[wizard._target_combo.currentIndex()] if wizard._targets else None
    signal = isinstance(reference, SignalEvidenceSpec)
    different = bool(
        reference
        and target
        and (reference.clock_id or reference.source_id) != (target.clock_id or target.source_id)
    )
    wizard._preview_button.setEnabled(different and wizard._thread is None)
    wizard._preview_button.setToolTip(
        tr("Preview timing from the selected evidence.")
        if different
        else tr("Choose recordings on different clocks before previewing.")
    )
    wizard._manual_button.setEnabled(target is not None)
    wizard._evidence_form.setRowVisible(wizard._threshold, events and signal)
    wizard._evidence_form.setRowVisible(
        wizard._target_threshold, events and isinstance(target, SignalEvidenceSpec)
    )
    wizard._evidence_form.setRowVisible(wizard._use_all_times_chk, events and signal)
    wizard._evidence_form.setRowVisible(
        wizard._recorded_strobe,
        events and signal and isinstance(target, EventEvidenceSpec) and target.is_frame_time_axis,
    )
    wizard._target_threshold.setEnabled(isinstance(target, SignalEvidenceSpec))
    wizard._threshold.setEnabled(not wizard._use_all_times_chk.isChecked())
    wizard._index_offset.setEnabled(False)
    wizard._advanced_form.setRowVisible(wizard._index_offset, False)
    wizard._index_offset.setToolTip(
        tr(
            "Exact mapping starts at the first stored frame; "
            "a shifted index cannot prove frame identity."
        )
    )


def fit_screen(wizard: SyncWizard, *, initial: bool = False) -> None:
    """Bound the window, including expanded options, to its current screen."""
    available = wizard.screen().availableGeometry().adjusted(16, 32, -16, -32)
    wizard.setMaximumSize(available.size())
    if initial:
        wizard.resize(min(1060, available.width()), min(720, available.height()))
    frame = wizard.frameGeometry()
    wizard.move(
        max(available.left(), min(wizard.x(), available.right() - frame.width() + 1)),
        max(available.top(), min(wizard.y(), available.bottom() - frame.height() + 1)),
    )


def responsive_layout(wizard: SyncWizard) -> None:
    """Stack setup and evidence when side-by-side text would be cramped."""
    wide = wizard.width() >= max(900, wizard.fontMetrics().horizontalAdvance("M") * 70)
    wizard._scroll.setMinimumHeight(0 if wide else min(180, wizard.height() // 3))
    orientation = Qt.Orientation.Horizontal if wide else Qt.Orientation.Vertical
    if wizard._body.orientation() != orientation:
        wizard._body.setOrientation(orientation)
        wizard._body.setSizes([380, 620] if wide else [250, 300])


def _source_choices(wizard: SyncWizard) -> None:
    for combo in (wizard._reference_combo, wizard._target_combo):
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(12)
        combo.setMinimumWidth(0)
        for index in range(combo.count()):
            full = combo.itemText(index)
            combo.setItemData(index, full, Qt.ItemDataRole.ToolTipRole)
            combo.setItemText(index, Path(full).name)
