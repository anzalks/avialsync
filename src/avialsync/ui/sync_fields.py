"""Construct alignment fields separately from proposal and worker lifetime."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
)

from avialsync.engine.sync_worker import SignalEvidenceSpec
from avialsync.ui.drift_spin import DriftSpinBox
from avialsync.ui.i18n import tr
from avialsync.ui.ms_spin import MillisecondSpinBox

if TYPE_CHECKING:
    from avialsync.ui.sync_wizard import SyncWizard


def initialize_fields(self: SyncWizard) -> None:
    """Build existing field identities once, before their contextual placement."""
    self._evidence_form = QFormLayout()
    self._advanced_form = QFormLayout()
    # Long rows wrap rather than widen the column past its viewport: the
    # settings column never scrolls sideways, so a wider form was clipped at
    # its left edge as soon as focus scrolled it ("ecording:").
    for form in (self._evidence_form, self._advanced_form):
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    _signals(self)
    _event_options(self)
    _strategy(self)
    _precision(self)
    _manual(self)


def _signals(self: SyncWizard) -> None:
    form = self._evidence_form
    self._reference_combo = QComboBox(self)
    self._target_combo = QComboBox(self)
    for spec in self._references:
        self._reference_combo.addItem(spec.display_name or spec.source_id)
    for spec in self._targets:
        self._target_combo.addItem(spec.display_name or spec.source_id)
    # The line's own midpoint unless typed, like the target's: a fixed 0.5
    # suited a 0-1 line and found nothing on a 3.3 V, 5 V or mV-scaled one.
    self._threshold = QDoubleSpinBox(self)
    self._threshold.setRange(-1e12, 1e12)
    self._threshold.setDecimals(3)
    self._threshold.setSpecialValueText(tr("Midpoint of the signal"))
    self._threshold.setValue(self._threshold.minimum())
    self._threshold.setToolTip(
        tr(
            "Logical high threshold for a signal-channel TTL reference, in the "
            "channel's own units. At its lowest value it is halfway between the "
            "channel's lowest and highest samples."
        )
    )
    form.addRow(tr("TTL high threshold:"), self._threshold)
    # A sensor chosen as the target is thresholded too, and its levels need
    # not be the reference's: a fixed 0.5 found no pulses on a line that
    # never crossed it. Left at its lowest value it is the line's midpoint.
    self._target_threshold = QDoubleSpinBox(self)
    self._target_threshold.setRange(-1e12, 1e12)
    self._target_threshold.setDecimals(3)
    self._target_threshold.setSpecialValueText(tr("Midpoint of the signal"))
    self._target_threshold.setValue(self._target_threshold.minimum())
    self._target_threshold.setAccessibleName(tr("Target TTL high threshold"))
    self._target_threshold.setToolTip(
        tr(
            "Logical high threshold for a sensor-channel target. At its lowest "
            "value it is halfway between the channel's lowest and highest samples."
        )
    )
    self._target_threshold.setAccessibleDescription(self._target_threshold.toolTip())
    form.addRow(tr("Target TTL high threshold:"), self._target_threshold)


def _event_options(self: SyncWizard) -> None:
    form = self._evidence_form
    self._use_all_times_chk = QCheckBox(tr("Event timestamps"))
    self._use_all_times_chk.setToolTip(
        tr(
            "Check this if your reference data is a list of event timestamps "
            "(such as a CSV of frame triggers) rather than a continuous voltage signal."
        )
    )
    self._use_all_times_chk.toggled.connect(lambda checked: self._threshold.setEnabled(not checked))
    form.addRow("", self._use_all_times_chk)
    self._recorded_strobe = QCheckBox(tr("Recorded exposure strobe"), self)
    self._recorded_strobe.setToolTip(
        tr(
            "Select only when the camera sent one measured strobe per exposure "
            "into the reference recorder. A frame timestamp or trigger request is insufficient."
        )
    )
    form.addRow("", self._recorded_strobe)
    for changed in (
        self._reference_combo.currentIndexChanged,
        self._target_combo.currentIndexChanged,
        self._threshold.valueChanged,
        self._target_threshold.valueChanged,
        self._use_all_times_chk.toggled,
        self._recorded_strobe.toggled,
    ):
        changed.connect(self._on_evidence_changed)
    self._target_threshold.setEnabled(
        bool(self._targets)
        and isinstance(self._targets[self._target_combo.currentIndex()], SignalEvidenceSpec)
    )
    # Fitting choices most alignments never touch: behind More….


def _strategy(self: SyncWizard) -> None:
    advanced = self._advanced_form

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
    self._strategy_combo.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    self._strategy_combo.setMinimumContentsLength(12)
    advanced.addRow(tr("Alignment strategy:"), self._strategy_combo)

    self._index_offset = QSpinBox(self)
    self._index_offset.setRange(-1000000, 1000000)
    self._index_offset.setValue(0)
    self._index_offset.setToolTip(
        tr(
            "Exact mapping starts at the first stored frame; "
            "a shifted index cannot prove frame identity."
        )
    )
    self._index_offset.setEnabled(False)
    self._strategy_combo.currentIndexChanged.connect(
        lambda: self._index_offset.setEnabled(self._strategy_combo.currentData() == "exact_index")
    )
    advanced.addRow(tr("Index Offset:"), self._index_offset)


def _precision(self: SyncWizard) -> None:
    advanced = self._advanced_form
    self._tolerance = MillisecondSpinBox(self)
    self._tolerance.setRange(0.0, 1e6)
    self._tolerance.setSpecialValueText(tr("from the pulse rate"))
    self._tolerance.setToolTip(
        tr(
            "How far a pair may be apart and still count as matched. Left at zero "
            "it is a quarter of the smaller median interval between events."
        )
    )
    self._tolerance.valueChanged.connect(self._on_tolerance_changed)
    advanced.addRow(tr("Match tolerance:"), self._tolerance)
    self._effective_tolerance = QLabel(tr("Calculated when you preview the evidence."), self)
    advanced.addRow(tr("Effective match tolerance:"), self._effective_tolerance)
    self._precision_requirement = MillisecondSpinBox(self)
    self._precision_requirement.setRange(0.000001, 1.0)
    self._precision_requirement.setValue(0.001)
    self._precision_requirement.setToolTip(
        tr(
            "Required timing precision. Matching may search a wider window, "
            "but residuals and unsupported intervals are judged against this value."
        )
    )
    advanced.addRow(tr("Required precision:"), self._precision_requirement)

    self._restrict = QCheckBox(tr("Limit fit window"))
    self._restrict.setToolTip(
        tr(
            "Drag the shaded window on the residual plot to choose it. A fit over "
            "part of a recording claims nothing about the rest, and is recorded "
            "as such."
        )
    )
    self._restrict.toggled.connect(self._on_restrict_toggled)
    advanced.addRow("", self._restrict)


def _manual(self: SyncWizard) -> None:
    self._manual_offset = QDoubleSpinBox(self)
    self._manual_offset.setRange(-1e9, 1e9)
    self._manual_offset.setDecimals(6)
    self._manual_offset.setSuffix(" s")
    # Milliseconds gained per hour, the unit the mapping uses.
    self._manual_drift = DriftSpinBox(self)
    self._summary = QLabel(tr("Choose evidence and preview the proposed fit."), self)
    self._summary.setWordWrap(True)
    self._preview_button = QPushButton(tr("Preview alignment"), self)
    self._preview_button.clicked.connect(self._preview)
    # Both routes use the one visible Preview command in the fixed footer.
    self._manual_button = self._preview_button
    self._buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
        self,
    )
    self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Apply alignment"))
    self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
    for button in (
        self._preview_button,
        self._buttons.button(QDialogButtonBox.StandardButton.Ok),
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel),
    ):
        button.setAutoDefault(False)
    # Wired to Apply itself: Preview shares the accept slot in the footer (so it
    # sits where Apply appears on every platform) and must never emit accepted.
    self._buttons.button(QDialogButtonBox.StandardButton.Ok).clicked.connect(self.accept)
    self._buttons.rejected.connect(self.reject)
