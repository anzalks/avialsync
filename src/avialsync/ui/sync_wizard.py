"""Non-blocking wizard for inspecting and accepting synchronization evidence."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QWidget,
)

from avialsync.core.drift import describe_drift
from avialsync.core.sync import SyncProposal
from avialsync.core.triggers import TriggerKind
from avialsync.engine.sync_worker import (
    EventEvidenceSpec,
    EvidenceSpec,
    SignalEvidenceSpec,
    SyncWorker,
)
from avialsync.ui import sync_form, sync_review
from avialsync.ui.coverage_lanes import SourceCoverage
from avialsync.ui.drift_spin import DriftSpinBox
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import JobManager
from avialsync.ui.step_panel import StepPanel
from avialsync.ui.sync_evidence_view import SyncEvidenceView
from avialsync.ui.sync_landmarks import LandmarkPanel


class SyncWizard(QDialog):
    """Inspect and explicitly accept alignment while keeping recordings interactive."""

    _reference_combo: QComboBox
    _target_combo: QComboBox
    _threshold: QDoubleSpinBox
    _target_threshold: QDoubleSpinBox
    _use_all_times_chk: QCheckBox
    _recorded_strobe: QCheckBox
    _strategy_combo: QComboBox
    _index_offset: QSpinBox
    _tolerance: QDoubleSpinBox
    _effective_tolerance: QLabel
    _precision_requirement: QDoubleSpinBox
    _restrict: QCheckBox
    _manual_offset: QDoubleSpinBox
    _manual_drift: DriftSpinBox
    _evidence_form: QFormLayout
    _advanced_form: QFormLayout
    _summary: QLabel
    _preview_button: QPushButton
    _manual_button: QPushButton
    _buttons: QDialogButtonBox

    _mode_combo: QComboBox
    _selection_form: QFormLayout
    _body: QSplitter
    _scroll: QScrollArea
    _manual_fields: QGroupBox
    _event_fields: QWidget
    _status: QLabel
    steps: StepPanel
    _landmarks: LandmarkPanel
    _review_buttons: list[QWidget | None]
    _context: tuple[object, ...]

    #: A point on the evidence was clicked, in the reference source's clock.
    seek_requested = Signal(float)

    def __init__(
        self,
        references: Sequence[EvidenceSpec],
        targets: Sequence[EvidenceSpec],
        parent: QWidget | None = None,
        *,
        visual_references: Sequence[EvidenceSpec] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Synchronize TTL / events"))
        self._event_references = list(references)
        self._visual_references = list(visual_references) or list(references)
        self._references = list(references)
        self._targets = list(targets)
        self._proposal: SyncProposal | None = None
        self._thread: QThread | None = None
        self._worker: SyncWorker | None = None
        self._local_jobs: JobManager | None = None

        self._revision = 0
        self._running_revision: int | None = None
        self._closed = False
        self._evidence = SyncEvidenceView(self)
        self._evidence.point_selected.connect(self.seek_requested)
        from avialsync.ui.sync_fields import initialize_fields

        initialize_fields(self)
        self._landmarks = LandmarkPanel(self)
        sync_form.build_form(self)
        sync_review.install_review(self)
        self._context = ()
        for changed in (
            self._precision_requirement.valueChanged,
            self._strategy_combo.currentIndexChanged,
            self._index_offset.valueChanged,
            self._manual_offset.valueChanged,
            self._manual_drift.valueChanged,
            self._evidence.restriction_changed,
        ):
            changed.connect(self._on_evidence_changed)
        self._mode_combo.currentIndexChanged.connect(self._mode_changed)
        self._reference_combo.currentIndexChanged.connect(self._landmarks.clear)
        self._target_combo.currentIndexChanged.connect(self._landmarks.clear)
        self._target_combo.currentIndexChanged.connect(lambda: sync_review.prefill_manual(self))
        self._reference_combo.currentIndexChanged.connect(self._configure_reference)
        self._landmarks.changed.connect(self._on_evidence_changed)
        self._evidence.restriction_changed.connect(self._restriction_changed)
        if not references:
            self._mode_combo.setCurrentIndex(2 if len(self._visual_references) > 1 else 1)
        sync_form.update_fields(self)
        self._configure_reference()
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.focusChanged.connect(self._focus_changed)

    def set_coverage(self, sources: list[SourceCoverage]) -> None:
        """Show where the loaded recordings sit before anything is fitted."""
        self._evidence.set_coverage(sources)

    @property
    def proposal(self) -> SyncProposal | None:
        """Return the proposal selected by the user after accepted execution."""
        return self._proposal

    @property
    def target_id(self) -> str:
        """The source the proposal was fitted for, or the selected one before a fit.

        Read from the proposal, never from the selector: changing the selector
        after a preview used to apply that preview's mapping to the newly
        selected source.
        """
        if self._proposal is not None:
            return self._proposal.target_id
        return self._targets[self._target_combo.currentIndex()].source_id

    def _preview(self) -> None:
        if self._thread is not None:
            return
        self._refresh_sources()
        self._context = sync_review.context_signature(self)
        if not sync_review.sources_available(self):
            self._on_error(
                tr("A selected recording was removed. Reopen alignment after loading it again.")
            )
            return
        if not self._references or not self._targets:
            self._on_error(tr("Choose two loaded recordings before previewing."))
            return
        reference, target = self._selected_evidence()
        self._running_revision = self._revision
        self._proposal = None
        self._preview_button.setEnabled(False)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._summary.setText(tr("Extracting event evidence and fitting alignment…"))
        self._status.setText(tr("Calculating alignment…"))
        self._effective_tolerance.setText(tr("Calculating from the selected evidence…"))

        mode = self._strategy_combo.currentData()
        index_offset = self._index_offset.value()
        # The reference's own declaration reaches the fit through the spec
        # itself. Before it did, the ladder saw SPARSE_EVENTS for everything, so
        # a user could declare a camera strobe or a shared sync train and never
        # get the model it licenses -- two of five rungs were unreachable.
        tolerance = self._tolerance.value() or None
        self._worker = SyncWorker(
            reference,
            target,
            mode=mode,
            index_offset=index_offset,
            tolerance=tolerance,
            precision_requirement=self._precision_requirement.value(),
            restrict_to=self._evidence.restriction(),
            landmarks=self._landmarks.pairs()
            if self._mode_combo.currentData() == "landmarks"
            else None,
            observation_resolution=self._landmarks.resolution.value(),
        )

        def configure(thread: QThread) -> None:
            assert self._worker is not None
            self._worker.finished.connect(self._on_finished)
            self._worker.error.connect(self._on_error)
            self._worker.cancelled.connect(self._on_cancelled)
            thread.finished.connect(self._on_thread_finished)

        parent = self.parentWidget()
        run_job = getattr(parent, "_run_job", None)
        if callable(run_job):
            self._thread = run_job(
                self._worker, label=tr("Fitting synchronization evidence"), configure=configure
            )
        else:
            # Standalone wizard previews still use the
            # same job lifetime machinery; production uses MainWindow._run_job.
            self._local_jobs = JobManager(self)
            self._thread = self._local_jobs.start(
                tr("Fitting synchronization evidence"), self._worker, configure=configure
            )

    def _selected_evidence(self) -> tuple[EvidenceSpec, EvidenceSpec]:
        reference = self._references[self._reference_combo.currentIndex()]
        target = self._targets[self._target_combo.currentIndex()]
        if isinstance(reference, SignalEvidenceSpec):
            reference = dataclasses.replace(
                reference,
                threshold=self._threshold.value(),
                use_all_times=self._use_all_times_chk.isChecked(),
                kind=TriggerKind.FRAME_STROBE
                if self._recorded_strobe.isChecked()
                else (
                    TriggerKind.SPARSE_EVENTS
                    if reference.kind is TriggerKind.FRAME_STROBE
                    else reference.kind
                ),
                strobe_for=target.clock_id
                if self._recorded_strobe.isChecked()
                else reference.strobe_for,
            )
        if isinstance(target, SignalEvidenceSpec):
            target = dataclasses.replace(target, threshold=self._chosen_target_threshold())
        if (
            isinstance(reference, EventEvidenceSpec)
            and reference.kind is TriggerKind.FRAME_STROBE
            and not reference.strobe_for
        ):
            # The file declaration says this is a measured strobe; "ask when
            # aligning" leaves its camera association to this explicit choice.
            reference = dataclasses.replace(reference, strobe_for=target.clock_id)
        return reference, target

    def _configure_reference(self) -> None:
        """Reflect declared signal semantics when a reference is selected."""
        if not self._references:
            return
        reference = self._references[self._reference_combo.currentIndex()]
        if not isinstance(reference, SignalEvidenceSpec):
            return
        for control, checked in (
            (self._recorded_strobe, reference.kind is TriggerKind.FRAME_STROBE),
            (self._use_all_times_chk, reference.use_all_times),
        ):
            blocked = control.blockSignals(True)
            control.setChecked(checked)
            control.blockSignals(blocked)
        sync_form.update_fields(self)

    def _on_restrict_toggled(self, checked: bool) -> None:
        """Show a window over the middle half of the evidence, or clear it.

        The middle half rather than all of it: a window covering everything is
        indistinguishable from no window, and would record a restriction that
        restricted nothing.
        """
        if not checked:
            self._evidence.set_restriction(None)
            self._on_evidence_changed()
            return
        span = self._evidence.evidence_span()
        if span is None:
            self._restrict.setChecked(False)
            self._summary.setText(
                tr("Preview a fit first: there is no evidence to choose a window from yet.")
            )
            return
        start, end = span
        quarter = (end - start) * 0.25
        self._evidence.set_restriction((start + quarter, end - quarter))
        self._on_evidence_changed()

    def _use_manual_mapping(self) -> None:
        """Preview an explicit correction without inventing measured evidence."""
        if not sync_review.sources_available(self):
            self._on_error(tr("The recording to move is no longer loaded."))
            return
        self._context = sync_review.context_signature(self)
        self._running_revision = -1
        if self._worker is not None:
            self._worker.cancel()
        self._proposal = sync_review.manual_proposal(self)
        self._evidence.show_proposal(None)
        self._summary.setText(
            tr(
                "Manual mapping: offset {offset:+.6f} s, drift {drift}. This is "
                "recorded as set by hand, with no evidence behind it, and will be reported "
                "that way wherever the alignment is shown."
            ).format(
                offset=self._manual_offset.value(),
                drift=describe_drift(self._manual_drift.value()),
            )
        )
        sync_review.set_review_enabled(self, True)
        self._status.setText(sync_review.headline(self, self._proposal))
        self._effective_tolerance.setText(tr("Not used for a manual mapping."))
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    @Slot(object)
    def _on_finished(self, proposal: object) -> None:
        if self._closed or (
            self._running_revision is not None and self._running_revision != self._revision
        ):
            return
        if not isinstance(proposal, SyncProposal):
            self._on_error("Synchronization worker returned an invalid proposal.")
            return
        if self._context and self._context != sync_review.context_signature(self):
            self.invalidate_sources()
            return
        self._proposal = proposal
        sync_review.set_review_enabled(self, True)
        fit = proposal.fit
        # The plot, not just the sentence. Acceptance needs the matched
        # evidence; four numbers are a summary of it.
        self._evidence.show_proposal(proposal)
        # Say what the tolerance was, whoever chose it: a fit judged by a
        # quarter-second band is a different claim from one judged by a
        # millisecond, and the number was previously nowhere on the dialog.
        self._show_tolerance(proposal.tolerance)
        provenance = (
            tr("derived from pulse spacing") if self._tolerance.value() == 0 else tr("set by you")
        )
        self._effective_tolerance.setText(
            tr("{value:.6g} s ({provenance})").format(
                value=proposal.tolerance,
                provenance=provenance,
            )
        )
        summary = fit.describe()
        refusal = proposal.refusal
        if refusal:
            # Why, beside the disabled button, rather than a greyed control the
            # user has to guess at. The next move is to change the
            # evidence, and this says which part of it.
            summary = f"{summary}\n\nCannot accept: {refusal}"
            self.steps.more_toggle.setChecked(True)
        self._summary.setText(summary)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(proposal.applicable)
        self._status.setText(sync_review.headline(self, proposal))

    def _show_tolerance(self, tolerance: float) -> None:
        """Reflect the tolerance a fit was actually judged by, without re-firing."""
        if self._tolerance.value():
            return  # The user set it; echoing it back would only round it.
        blocked = self._tolerance.blockSignals(True)
        try:
            self._tolerance.setToolTip(
                tr(
                    "Derived from the pulse rate: {value:.6f} s. Type a value to judge "
                    "this fit by the precision your work needs instead."
                ).format(value=tolerance)
            )
        finally:
            self._tolerance.blockSignals(blocked)

    def _on_tolerance_changed(self, _value: float) -> None:
        """Discard a proposal judged with a different tolerance."""
        self._discard_preview(tr("Match tolerance changed. Preview again before accepting."))

    def _on_evidence_changed(self, *_args: object) -> None:
        """Discard a proposal fitted to evidence that is no longer selected."""
        sync_form.update_fields(self)
        self._discard_preview(
            tr("The evidence or settings changed. Preview again before accepting.")
        )

    def _discard_preview(self, reason: str) -> None:
        self._revision += 1
        if self._worker is not None:
            self._worker.cancel()
        self._proposal = None
        sync_review.set_review_enabled(self, False)
        if self._evidence._proposal is not None:
            self._evidence._headline.setText(tr("Previous preview — out of date"))
        # Keep the plot and restriction available for choosing a different fit window.
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._summary.setText(reason)
        self._status.setText(tr("Preview needed: the previous result is out of date."))
        self._effective_tolerance.setText(tr("Preview is out of date; preview again."))

    def _mode_changed(self, _index: int) -> None:
        self._references = list(
            self._event_references
            if self._mode_combo.currentData() == "events"
            else self._visual_references
        )
        blocked = self._reference_combo.blockSignals(True)
        self._reference_combo.clear()
        for spec in self._references:
            self._reference_combo.addItem(spec.display_name or spec.source_id)
        self._reference_combo.blockSignals(blocked)
        if self._references and self._targets and self._mode_combo.currentData() != "manual":
            clock = self._references[0].clock_id or self._references[0].source_id
            index = next(
                (
                    i
                    for i, spec in enumerate(self._targets)
                    if (spec.clock_id or spec.source_id) != clock
                ),
                0,
            )
            self._target_combo.setCurrentIndex(index)
        self._landmarks.clear()
        sync_review.prefill_manual(self)
        self._on_evidence_changed()

    def accept(self) -> None:
        """Only accept a current proposal for sources that remain loaded."""
        if self._proposal is None or not self._proposal.applicable:
            return
        if not sync_review.sources_available(self) or (
            self._context and self._context != sync_review.context_signature(self)
        ):
            self.invalidate_sources()
            return
        super().accept()

    def invalidate_sources(self) -> None:
        """Reject a preview made before a source's timing or availability changed."""
        self._discard_preview(tr("Recording timing changed. Preview again before accepting."))

    def _refresh_sources(self) -> None:
        from avialsync.ui.sync_lifecycle import as_window

        parent = as_window(self.parentWidget())
        if parent is None:
            return
        from avialsync.ui.sync_acceptance import collect_sync_evidence

        references, targets = collect_sync_evidence(parent)
        if self._mode_combo.currentData() != "events":
            from avialsync.ui.sync_landmarks import visual_evidence

            references = visual_evidence(parent)
        current = {spec.source_id: spec for spec in references}
        self._references = [current.get(spec.source_id, spec) for spec in self._references]
        current = {spec.source_id: spec for spec in targets}
        self._targets = [current.get(spec.source_id, spec) for spec in self._targets]

    def _restriction_changed(self, _window: object) -> None:
        self._discard_preview(tr("Fit window changed. Preview again before accepting."))

    def showEvent(self, event: QShowEvent) -> None:
        """Open within the current display's usable area."""
        super().showEvent(event)
        sync_form.fit_screen(self, initial=not self.property("alignment_shown"))
        self.setProperty("alignment_shown", True)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep settings readable on narrow displays."""
        super().resizeEvent(event)
        if hasattr(self, "_body"):
            sync_form.responsive_layout(self)

    @Slot(QWidget, QWidget)
    def _focus_changed(self, _old: QWidget | None, current: QWidget | None) -> None:
        if current is None:
            return
        for area in self.findChildren(QScrollArea):
            content = area.widget()
            if content is not None and content.isAncestorOf(current):
                area.ensureWidgetVisible(current)

    def _chosen_target_threshold(self) -> float | None:
        """The typed target threshold, or None for the signal's own midpoint."""
        value = self._target_threshold.value()
        return None if value == self._target_threshold.minimum() else value

    @Slot(str)
    def _on_error(self, message: str) -> None:
        """Present an actionable cause inline, with its details scrolled into view."""
        if self._closed or (
            self._running_revision is not None and self._running_revision != self._revision
        ):
            return
        self._status.setText(tr("No mapping proposed. Change the evidence and preview again."))
        self._summary.setText(tr("No mapping proposed: {reason}").format(reason=message))
        self.steps.more_toggle.setChecked(True)
        self._scroll.ensureWidgetVisible(self._summary)
        self._effective_tolerance.setText(tr("Unavailable because preview did not produce a fit."))

    @Slot()
    def _on_cancelled(self) -> None:
        if self._running_revision == self._revision:
            self._summary.setText(tr("Synchronization preview cancelled."))
            self._status.setText(tr("Preview cancelled."))

    @Slot()
    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        sync_form.update_fields(self)

    def done(self, result: int) -> None:
        """Cancel a preview still running when the wizard closes: nothing reads it."""
        self._closed = True
        if self._worker is not None:
            self._worker.cancel()
        if self._local_jobs is not None:
            self._local_jobs.shutdown()
        super().done(result)
