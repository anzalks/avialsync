"""Non-blocking wizard for inspecting and accepting synchronization evidence."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.sync import AlignmentMethod, SyncFit, SyncProposal
from avialsync.engine.sync_worker import EvidenceSpec, SignalEvidenceSpec, SyncWorker
from avialsync.ui.coverage_lanes import SourceCoverage
from avialsync.ui.i18n import tr
from avialsync.ui.sync_evidence_view import SyncEvidenceView


class SyncWizard(QDialog):
    """Select evidence, inspect a fit, and explicitly accept a proposal.

    Shown without blocking. The natural question at a forty-millisecond outlier
    is what the footage looks like there, and under ``exec()`` it could not be
    asked: the dialog blocked the window it was asking the user to judge, in
    the one place where cross-examining the evidence matters most. Rule 11
    permits a modal for a dialog the user asked for; this one declines it.
    """

    #: A point on the evidence was clicked, in the reference source's clock.
    seek_requested = Signal(float)

    def __init__(
        self,
        references: Sequence[EvidenceSpec],
        targets: Sequence[EvidenceSpec],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Synchronize TTL / events"))
        self._references = list(references)
        self._targets = list(targets)
        self._proposal: SyncProposal | None = None
        self._thread: QThread | None = None
        self._worker: SyncWorker | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Choose reference and video event evidence. The proposed mapping is not applied "
                "until you explicitly accept it."
            )
        )
        self._evidence = SyncEvidenceView(self)
        self._evidence.point_selected.connect(self.seek_requested)
        layout.addWidget(self._evidence)
        form = QFormLayout()
        self._reference_combo = QComboBox(self)
        self._target_combo = QComboBox(self)
        for spec in self._references:
            self._reference_combo.addItem(spec.source_id)
        for spec in self._targets:
            self._target_combo.addItem(spec.source_id)
        form.addRow("Reference evidence:", self._reference_combo)
        form.addRow("Target video evidence:", self._target_combo)
        self._threshold = QDoubleSpinBox(self)
        self._threshold.setRange(-1e12, 1e12)
        self._threshold.setDecimals(6)
        self._threshold.setValue(0.5)
        self._threshold.setToolTip(tr("Logical high threshold for a signal-channel TTL reference"))
        form.addRow("TTL high threshold:", self._threshold)

        self._use_all_times_chk = QCheckBox("Use all samples as events (ignore threshold)")
        self._use_all_times_chk.setToolTip(
            tr(
                "Check this if your reference data is a list of event timestamps "
                "(such as a CSV of frame triggers) rather than a continuous voltage signal."
            )
        )
        self._use_all_times_chk.toggled.connect(
            lambda checked: self._threshold.setEnabled(not checked)
        )
        form.addRow("", self._use_all_times_chk)

        self._strategy_combo = QComboBox(self)
        # Automatic first, and the default. A strategy dropdown asks the user to
        # certify something only the data knows -- whether the span can support
        # a rate, whether the pulses are regular enough to interpolate between
        # -- so the ladder decides unless someone overrides it deliberately.
        self._strategy_combo.addItem(tr("Automatic (from the evidence)"), "auto")
        self._strategy_combo.addItem(tr("Affine fit (offset and drift)"), "affine")
        self._strategy_combo.addItem(tr("Exact index (1:1 frame mapping)"), "exact_index")
        self._strategy_combo.setToolTip(
            tr(
                "Automatic picks the strongest model this evidence supports: exact where "
                "frames are paired, interpolated between sync edges where a shared train "
                "exists, a fitted rate where the recording is long enough to measure one, "
                "and an offset alone where it is not."
            )
        )
        form.addRow(tr("Alignment strategy:"), self._strategy_combo)

        self._index_offset = QSpinBox(self)
        self._index_offset.setRange(-1000000, 1000000)
        self._index_offset.setValue(0)
        self._index_offset.setToolTip(tr("Video Frame 0 maps to CSV Index N. Default is 0."))
        self._index_offset.setEnabled(False)
        self._strategy_combo.currentIndexChanged.connect(
            lambda: self._index_offset.setEnabled(
                self._strategy_combo.currentData() == "exact_index"
            )
        )
        form.addRow("Index Offset:", self._index_offset)

        # The number that decided which events counted, shown rather than
        # implied. Left at zero it is derived from the pulse rate -- a quarter
        # of the median interval -- which is a heuristic about telling one
        # pulse from the next and says nothing about the precision the work
        # needs. At 1 Hz that is 250 ms, and it will accept a 100 ms
        # misalignment without complaint; a user who needs better cannot know
        # to ask for it while the figure is invisible.
        self._tolerance = QDoubleSpinBox(self)
        self._tolerance.setRange(0.0, 1e6)
        self._tolerance.setDecimals(6)
        self._tolerance.setSuffix(" s")
        self._tolerance.setSpecialValueText(tr("from the pulse rate"))
        self._tolerance.setToolTip(
            tr(
                "How far a pair may be apart and still count as matched. Left at zero "
                "it is a quarter of the smaller median interval between events."
            )
        )
        form.addRow(tr("Match tolerance:"), self._tolerance)

        self._restrict = QCheckBox(tr("Fit only part of the recording"))
        self._restrict.setToolTip(
            tr(
                "Drag the shaded window on the residual plot to choose it. A fit over "
                "part of a recording claims nothing about the rest, and is recorded "
                "as such."
            )
        )
        self._restrict.toggled.connect(self._on_restrict_toggled)
        form.addRow("", self._restrict)

        self._manual_offset = QDoubleSpinBox(self)
        self._manual_offset.setRange(-1e9, 1e9)
        self._manual_offset.setDecimals(6)
        self._manual_offset.setSuffix(" s")
        self._manual_drift = QDoubleSpinBox(self)
        self._manual_drift.setRange(-1e6, 1e6)
        self._manual_drift.setDecimals(3)
        self._manual_drift.setSuffix(" ppm")
        form.addRow("Manual offset:", self._manual_offset)
        form.addRow("Manual drift:", self._manual_drift)
        layout.addLayout(form)

        self._summary = QLabel("Choose evidence and preview the proposed fit.", self)
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        self._preview_button = QPushButton("Preview alignment", self)
        self._preview_button.clicked.connect(self._preview)
        layout.addWidget(self._preview_button)
        self._manual_button = QPushButton("Use manual mapping", self)
        self._manual_button.clicked.connect(self._use_manual_mapping)
        layout.addWidget(self._manual_button)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            self,
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Accept mapping"))
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def set_coverage(self, sources: list[SourceCoverage]) -> None:
        """Show where the loaded recordings sit before anything is fitted."""
        self._evidence.set_coverage(sources)

    @property
    def proposal(self) -> SyncProposal | None:
        """Return the proposal selected by the user after accepted execution."""
        return self._proposal

    @property
    def target_id(self) -> str:
        """Return the target identifier associated with the accepted proposal."""
        return self._target_combo.currentText()

    def _preview(self) -> None:
        if self._thread is not None:
            return
        reference = self._references[self._reference_combo.currentIndex()]
        target = self._targets[self._target_combo.currentIndex()]
        if isinstance(reference, SignalEvidenceSpec):
            reference = dataclasses.replace(
                reference,
                threshold=self._threshold.value(),
                use_all_times=self._use_all_times_chk.isChecked(),
            )
        self._proposal = None
        self._preview_button.setEnabled(False)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._summary.setText(tr("Extracting event evidence and fitting alignment…"))

        self._thread = QThread(self)
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
            restrict_to=self._evidence.restriction(),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        # No `self._thread.finished.connect(self._worker.deleteLater)`:
        # `finished` is emitted in the worker thread and the worker lives
        # there, so that connection is direct and ~QObject would run inside
        # the dying thread — severing connections while holding one of Qt's
        # pooled signal/slot mutexes and then taking the GIL for PySide's
        # disconnectNotify, deadlocking a UI thread that holds the GIL and
        # waits on a colliding mutex from that pool (D-062).
        # `_on_thread_finished` drops the reference on the UI thread instead.
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_restrict_toggled(self, checked: bool) -> None:
        """Show a window over the middle half of the evidence, or clear it.

        The middle half rather than all of it: a window covering everything is
        indistinguishable from no window, and would record a restriction that
        restricted nothing.
        """
        if not checked:
            self._evidence.set_restriction(None)
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

    def _use_manual_mapping(self) -> None:
        """Provide an explicit fallback when evidence is sparse or ambiguous.

        It used to declare three matched events and a zero maximum residual, so
        that `SyncProposal.acceptable` -- which needs at least three matches --
        would let it through. Those numbers went into the session and came back
        out of it as "aligned to X ± 0.0 ms from 3 events": a figure nobody
        measured, presented as the most confident record in the file.

        A manual mapping now counts nothing and claims nothing. It is
        *applicable* because the user chose it, which is a different question
        from whether it is acceptable on evidence, and it has none.
        """
        self._proposal = SyncProposal(
            reference_id=self._reference_combo.currentText(),
            target_id=self._target_combo.currentText(),
            fit=SyncFit(
                offset=self._manual_offset.value(),
                drift_ppm=self._manual_drift.value(),
                rms_residual=0.0,
                max_residual=0.0,
                matched_count=0,
                rejected_count=0,
                method=AlignmentMethod.MANUAL,
            ),
            matches=(),
            tolerance=0.0,
            unmatched_references=(),
        )
        self._evidence.show_proposal(None)
        self._summary.setText(
            tr(
                "Manual mapping: offset {offset:+.6f} s, drift {drift:+.3f} ppm. This is "
                "recorded as set by hand, with no evidence behind it, and will be reported "
                "that way wherever the alignment is shown."
            ).format(offset=self._manual_offset.value(), drift=self._manual_drift.value())
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    @Slot(object)
    def _on_finished(self, proposal: object) -> None:
        if not isinstance(proposal, SyncProposal):
            self._on_error("Synchronization worker returned an invalid proposal.")
            return
        self._proposal = proposal
        fit = proposal.fit
        # The plot, not just the sentence. BLUEPRINT principle 8 asks for the
        # matched evidence; four numbers are a summary of it (WP-10).
        self._evidence.show_proposal(proposal)
        # Say what the tolerance was, whoever chose it: a fit judged by a
        # quarter-second band is a different claim from one judged by a
        # millisecond, and the number was previously nowhere on the dialog.
        self._show_tolerance(proposal.tolerance)
        summary = fit.describe()
        refusal = proposal.refusal
        if refusal:
            # Why, beside the disabled button, rather than a greyed control the
            # user has to guess at (rule 15). The next move is to change the
            # evidence, and this says which part of it.
            summary = f"{summary}\n\nCannot accept: {refusal}"
        self._summary.setText(summary)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(proposal.applicable)

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

    @Slot(str)
    def _on_error(self, message: str) -> None:
        """Say why no mapping was proposed, in the summary that is already there.

        This used to say it twice: once in the summary line, and again in a
        modal on top of the wizard carrying the same text (D-107). The modal
        added nothing but a click, and the wizard stays open either way — the
        user's next move is to pick different evidence, which is behind it.
        """
        self._summary.setText(tr("No mapping proposed: {reason}").format(reason=message))

    @Slot()
    def _on_thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self._preview_button.setEnabled(True)
