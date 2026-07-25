"""Non-blocking wizard for inspecting and accepting synchronization evidence."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from PySide6.QtCore import QThread, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from avialview.core.sync import SyncFit, SyncProposal
from avialview.engine.sync_worker import EvidenceSpec, SignalEvidenceSpec, SyncWorker


class SyncWizard(QDialog):
    """Select evidence, inspect a fit, and explicitly accept a proposal."""

    def __init__(
        self,
        references: Sequence[EvidenceSpec],
        targets: Sequence[EvidenceSpec],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Synchronize TTL / events")
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
        self._threshold.setToolTip("Logical high threshold for a signal-channel TTL reference")
        form.addRow("TTL high threshold:", self._threshold)
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
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Accept mapping")
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

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
            reference = dataclasses.replace(reference, threshold=self._threshold.value())
        self._proposal = None
        self._preview_button.setEnabled(False)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._summary.setText("Extracting event evidence and fitting alignment…")

        self._thread = QThread(self)
        self._worker = SyncWorker(reference, target)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _use_manual_mapping(self) -> None:
        """Provide an explicit fallback when evidence is sparse or ambiguous."""
        self._proposal = SyncProposal(
            reference_id=self._reference_combo.currentText(),
            target_id=self._target_combo.currentText(),
            fit=SyncFit(
                offset=self._manual_offset.value(),
                drift_ppm=self._manual_drift.value(),
                rms_residual=0.0,
                max_residual=0.0,
                matched_count=3,
                rejected_count=0,
            ),
            matches=(),
            tolerance=0.0,
        )
        self._summary.setText("Manual mapping selected. Accept it to apply and persist it.")
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    @Slot(object)
    def _on_finished(self, proposal: object) -> None:
        if not isinstance(proposal, SyncProposal):
            self._on_error("Synchronization worker returned an invalid proposal.")
            return
        self._proposal = proposal
        fit = proposal.fit
        self._summary.setText(
            f"{fit.matched_count} matched events; {fit.rejected_count} unmatched; "
            f"offset {fit.offset:.6f} s; drift {fit.drift_ppm:.3f} ppm; "
            f"maximum residual {fit.max_residual * 1000:.3f} ms."
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(proposal.acceptable)

    @Slot(str)
    def _on_error(self, message: str) -> None:
        self._summary.setText(f"No mapping proposed: {message}")
        QMessageBox.warning(self, "Synchronization evidence", message)

    @Slot()
    def _on_thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self._preview_button.setEnabled(True)
