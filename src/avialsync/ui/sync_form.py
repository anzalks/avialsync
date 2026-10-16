"""Screen-bounded, contextual controls for the non-modal alignment dialog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
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

from avialsync.core.drift import describe_drift
from avialsync.engine.sync_worker import EventEvidenceSpec, SignalEvidenceSpec
from avialsync.ui import sync_choices
from avialsync.ui.about import docs_url
from avialsync.ui.i18n import tr
from avialsync.ui.icons import set_svg_icon
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
    _manual_controls(wizard, setup)
    settings.addWidget(wizard._manual_fields)
    settings.addWidget(wizard._landmarks)
    wizard._guidance = QLabel(setup)
    wizard._guidance.setWordWrap(True)
    wizard._guidance.setAccessibleName(tr("Next alignment step"))
    settings.addWidget(wizard._guidance)
    wizard.steps = StepPanel(tr("Advanced matching"), setup)
    wizard.steps.set_instruction(tr("Override matching only when the recorded evidence needs it."))
    advanced = QWidget(setup)
    advanced.setLayout(wizard._advanced_form)
    wizard.steps.add_more(advanced)
    wizard.steps.set_learn_more(docs_url("tutorials/synchronization.html"))
    settings.addWidget(wizard.steps)
    settings.addStretch(1)
    wizard._scroll.setWidget(setup)
    _results(wizard)
    from avialsync.ui.sync_layout import install_pages

    install_pages(wizard, layout)
    wizard._buttons.addButton(wizard._preview_button, QDialogButtonBox.ButtonRole.AcceptRole)
    layout.addWidget(wizard._buttons)
    _accessibility(wizard)


def _manual_controls(wizard: SyncWizard, setup: QWidget) -> None:
    wizard._manual_fields = QGroupBox(tr("Manual adjustment"), setup)
    manual = QFormLayout(wizard._manual_fields)
    manual.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    manual.addRow(tr("Offset (positive moves earlier):"), wizard._manual_offset)
    wizard._drift_toggle = QPushButton(tr("Adjust clock drift"), wizard._manual_fields)
    wizard._drift_toggle.setCheckable(True)
    # A disclosure, like StepPanel's More…: a checked push button would read as a
    # second primary action beside the footer's Preview.
    wizard._drift_toggle.setFlat(True)
    set_svg_icon(wizard._drift_toggle, "chevron-right")
    wizard._drift_toggle.toggled.connect(
        lambda checked: set_svg_icon(
            wizard._drift_toggle, "chevron-down" if checked else "chevron-right"
        )
    )
    describe(
        wizard._drift_toggle,
        tr("Adjust clock drift"),
        tr("Show clock drift without resetting its current value."),
    )
    wizard._drift_summary = QLabel(wizard._manual_fields)
    wizard._drift_summary.setWordWrap(True)
    manual.addRow(wizard._drift_summary)
    manual.addRow(wizard._drift_toggle)
    manual.addRow(tr("Clock drift:"), wizard._manual_drift)
    wizard._manual_form = manual
    wizard._drift_toggle.toggled.connect(
        lambda checked: manual.setRowVisible(wizard._manual_drift, checked)
    )


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
        (tr("Recorded sync signals"), "events"),
        (tr("Adjust timing manually"), "manual"),
        (tr("Match visible events"), "landmarks"),
    ):
        wizard._mode_combo.addItem(label, value)
    selection.addRow(tr("Reference recording:"), wizard._reference_combo)
    selection.addRow(tr("Recording to move:"), wizard._target_combo)
    selection.addRow(tr("Align using:"), wizard._mode_combo)
    wizard._suggestion = QLabel(setup)
    wizard._suggestion.setWordWrap(True)
    selection.addRow(wizard._suggestion)
    _source_choices(wizard)
    return selection


def _results(wizard: SyncWizard) -> None:
    wizard._results = QWidget(wizard)
    layout = QVBoxLayout(wizard._results)
    wizard._status = QLabel(tr("Choose recordings, then preview an alignment."), wizard._results)
    wizard._status.setWordWrap(True)
    wizard._status.setAccessibleName(tr("Alignment result"))
    layout.addWidget(wizard._status)
    wizard._fit_details = StepPanel(tr("Fit details"), wizard._results)
    wizard._fit_details.set_instruction(
        tr("Inspect fitted values, evidence limits and diagnostics.")
    )
    wizard._fit_details.add_more(wizard._summary)
    layout.addWidget(wizard._evidence, 1)
    layout.addWidget(wizard._fit_details)
    # Zero stretch: the evidence keeps the space while shown; with it hidden
    # (manual mode) the spacer, not Fit details, absorbs the empty height.
    layout.addStretch(0)
    # The result sentence leads; the same statistics remain in Fit details.
    wizard._evidence._headline.hide()


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
    wizard._manual_form.setRowVisible(wizard._manual_drift, wizard._drift_toggle.isChecked())
    wizard._drift_summary.setText(
        tr("Current clock drift: {drift}").format(
            drift=describe_drift(wizard._manual_drift.value())
        )
        if wizard._manual_drift.value()
        else tr("Clock drift: unchanged at zero")
    )
    wizard._evidence.setVisible(not manual)
    wizard.steps.setVisible(not manual)
    reference = (
        wizard._references[wizard._reference_combo.currentIndex()] if wizard._references else None
    )
    target = wizard._targets[wizard._target_combo.currentIndex()] if wizard._targets else None
    signal = isinstance(reference, SignalEvidenceSpec)
    # Event lists need no threshold questions; an empty form would leave a blank band.
    wizard._event_fields.setVisible(events and (signal or isinstance(target, SignalEvidenceSpec)))
    guidance, ready = sync_choices.setup_guidance(wizard)
    wizard._guidance.setText(guidance)
    wizard._preview_button.setEnabled(ready and wizard._thread is None)
    wizard._preview_button.setToolTip(guidance)
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
    suggested = sync_choices.suggested_mode(wizard)
    label = wizard._mode_combo.itemText(wizard._mode_combo.findData(suggested))
    wizard._suggestion.setText(
        tr("Suggested: {method}. Confirm the evidence before previewing.").format(method=label)
    )
    from avialsync.ui.sync_review import update_primary

    update_primary(wizard)


def fit_screen(wizard: SyncWizard, *, initial: bool = False) -> None:
    """Bound the window, including expanded options, to its current screen."""
    available = wizard.screen().availableGeometry().adjusted(16, 32, -16, -32)
    wizard.setMaximumSize(available.size())
    if initial:
        from avialsync.ui.sync_preferences import preference

        wizard.resize(
            max(320, min(int(preference("window_width")), available.width())),
            max(320, min(int(preference("window_height")), available.height())),
        )
    frame = wizard.frameGeometry()
    wizard.move(
        max(available.left(), min(wizard.x(), available.right() - frame.width() + 1)),
        max(available.top(), min(wizard.y(), available.bottom() - frame.height() + 1)),
    )


def responsive_layout(wizard: SyncWizard) -> None:
    """Delegate responsive page ownership without rebuilding controls."""
    from avialsync.ui.sync_layout import responsive_layout as arrange

    arrange(wizard)


def _source_choices(wizard: SyncWizard) -> None:
    for combo in (wizard._reference_combo, wizard._target_combo):
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(12)
        combo.setMinimumWidth(0)
    sync_choices.refresh_labels(wizard)
