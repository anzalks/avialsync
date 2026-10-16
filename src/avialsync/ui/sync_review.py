"""Review navigation, live-context checks and report export for alignment."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QPushButton, QVBoxLayout

from avialsync.core.errors import ExportError
from avialsync.core.sync import AlignmentMethod, ExactSyncFit, SyncFit, SyncProposal
from avialsync.core.timeline import PreparedExactMapping, TimeMap
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow
    from avialsync.ui.sync_wizard import SyncWizard


def install_review(wizard: SyncWizard) -> None:
    """Offer direct verification points without hiding the recording window."""
    row = QHBoxLayout()
    buttons: list[QPushButton] = []
    for text, fraction in (
        (tr("Beginning"), 0.0),
        (tr("Middle"), 0.5),
        (tr("End"), 1.0),
    ):
        button = QPushButton(text, wizard)
        button.setAccessibleName(text)
        button.setAccessibleDescription(tr("Seek to an observed event to compare the recordings."))
        button.clicked.connect(lambda _checked=False, part=fraction: seek_check(wizard, part))
        row.addWidget(button)
        buttons.append(button)
    export = QPushButton(tr("Export report…"), wizard)
    export.setAccessibleName(tr("Export proposed alignment report"))
    export.setAccessibleDescription(
        tr("Write the current proposal and its evidence to a JSON report.")
    )
    from avialsync.ui.sync_lifecycle import as_window

    export.clicked.connect(lambda: export_report(as_window(wizard.parentWidget()), wizard))
    row.addWidget(export)
    buttons.append(export)
    wizard._review_buttons = list(buttons)
    outer = wizard.layout()
    assert isinstance(outer, QVBoxLayout)
    outer.insertLayout(outer.count() - 2, row)
    set_review_enabled(wizard, False)


def set_review_enabled(wizard: SyncWizard, enabled: bool) -> None:
    for index, button in enumerate(wizard._review_buttons):
        if button is not None:
            button.setEnabled(
                enabled and (index == 3 or bool(wizard.proposal and wizard.proposal.matches))
            )


def manual_proposal(wizard: SyncWizard) -> SyncProposal:
    """Interpret the typed correction in the same domain as source-card edits."""
    from avialsync.ui.sync_lifecycle import as_window, source_mapping

    parent = as_window(wizard.parentWidget())
    target = wizard._targets[wizard._target_combo.currentIndex()]
    offset = wizard._manual_offset.value()
    if parent is not None and hasattr(parent, "effective_offset"):
        offset = parent.effective_offset(target.source_id, offset)
    fit: SyncFit = SyncFit(
        offset, wizard._manual_drift.value(), 0.0, 0.0, 0, 0, method=AlignmentMethod.MANUAL
    )
    mapping = source_mapping(parent, target.source_id) if parent is not None else None
    if mapping is not None and mapping.has_exact_mapping:
        master, source = mapping._exact_master, mapping._exact_source
        assert master is not None and source is not None
        fit = ExactSyncFit(
            offset,
            wizard._manual_drift.value(),
            0.0,
            0.0,
            0,
            0,
            method=AlignmentMethod.MANUAL,
            exact_master=master,
            exact_source=source,
            prepared_mapping=PreparedExactMapping.adopt(master, source),
            exact_offset_anchor=mapping._exact_offset_anchor,
            exact_drift_anchor=mapping._exact_drift_anchor,
        )
    return SyncProposal("manual", target.source_id, fit, (), 0.0, settings={"strategy": "manual"})


def prefill_manual(wizard: SyncWizard) -> None:
    """Start from the selected recording's current correction, without applying it."""
    from avialsync.ui.sync_lifecycle import as_window, source_mapping

    parent = as_window(wizard.parentWidget())
    if parent is None or not wizard._targets or wizard._mode_combo.currentData() != "manual":
        return
    source_id = wizard._targets[wizard._target_combo.currentIndex()].source_id
    mapping = source_mapping(parent, source_id)
    if mapping is None:
        return
    for spin, value in (
        (wizard._manual_offset, parent.user_offset(source_id, mapping.offset)),
        (wizard._manual_drift, mapping.drift_ms_per_hour),
    ):
        blocked = spin.blockSignals(True)
        spin.setValue(value)
        spin.blockSignals(blocked)


def headline(wizard: SyncWizard, proposal: SyncProposal) -> str:
    """Describe the proposal's actual effect rather than the internal offset sign."""
    from avialsync.ui.sync_lifecycle import as_window, source_mapping

    parent = as_window(wizard.parentWidget())
    current = source_mapping(parent, proposal.target_id) if parent else None
    current = current or TimeMap()
    anchor = proposal.matches[0].target_time if proposal.matches else 0.0
    delta = proposal.fit.to_time_map().to_master(anchor) - current.to_master(anchor)
    direction = tr("later") if delta >= 0 else tr("earlier")
    movement = tr("Start moves {seconds:.3f} s {direction}").format(
        seconds=abs(delta), direction=direction
    )
    state = tr("Ready to accept") if proposal.applicable else tr("Needs different evidence")
    precision = (
        tr("timestamp precision verified")
        if proposal.fit.precision_verified
        else tr("timestamp precision unverified")
    )
    return tr("{state} · {movement} · {precision}").format(
        state=state, movement=movement, precision=precision
    )


def seek_check(wizard: SyncWizard, fraction: float) -> None:
    """Seek to actual matched evidence rather than inventing verification points."""
    proposal = wizard.proposal
    if proposal is not None and proposal.matches:
        index = round(fraction * (len(proposal.matches) - 1))
        wizard.seek_requested.emit(proposal.matches[index].reference_time)


def context_signature(wizard: SyncWizard) -> tuple[object, ...]:
    """Capture only live clock identity and scalar values; never scan frame arrays."""
    from avialsync.ui.sync_lifecycle import as_window, source_mapping

    parent = as_window(wizard.parentWidget())
    if parent is None:
        return ()
    signature: list[object] = []
    for specs, combo in (
        (wizard._references, wizard._reference_combo),
        (wizard._targets, wizard._target_combo),
    ):
        if specs is wizard._references and wizard._mode_combo.currentData() == "manual":
            continue
        if not specs:
            continue
        spec = specs[combo.currentIndex()]
        mapping = source_mapping(parent, spec.clock_id or spec.source_id)
        signature.append(
            (
                spec.source_id,
                None
                if mapping is None
                else (
                    mapping.offset,
                    mapping.drift_ms_per_hour,
                    id(mapping._exact_master),
                    id(mapping._exact_source),
                    mapping._exact_offset_anchor,
                    mapping._exact_drift_anchor,
                ),
            )
        )
    return tuple(signature)


def sources_available(wizard: SyncWizard) -> bool:
    """A removed recording cannot be a proposal's source or target."""
    return all(
        value[1] is not None for value in context_signature(wizard) if isinstance(value, tuple)
    )


def export_report(window: MainWindow | None, wizard: SyncWizard | None = None) -> None:
    """Export through MainWindow's worker manager and its existing feedback surface."""
    if window is None or not hasattr(window, "_run_job"):
        return
    from avialsync.engine.sync_report import SyncReportWorker
    from avialsync.ui.sync_lifecycle import source_mapping

    proposal = wizard.proposal if wizard else None
    if wizard is not None and proposal is None:
        return
    chosen, _ = QFileDialog.getSaveFileName(
        window, tr("Export Alignment Report"), "alignment.json", tr("JSON reports (*.json)")
    )
    if not chosen:
        return
    records = window.accepted_alignment_records() if wizard is None else ()
    mappings = {}
    for record in records:
        mapping = source_mapping(window, record.target_id)
        if mapping is not None:
            mappings[record.target_id] = mapping.copy()
    worker = SyncReportWorker(Path(chosen), proposal, records, mappings)

    def configure(_thread: QThread) -> None:
        worker.finished.connect(
            on_ui_thread(
                lambda _path: window.notifications.show_success(tr("Alignment report saved.")),
                window,
            )
        )
        worker.error.connect(
            on_ui_thread(
                lambda message: window.report_failure(
                    ExportError(message), doing=tr("Saving alignment report")
                ),
                window,
            )
        )

    window._run_job(worker, label=tr("Saving alignment report"), configure=configure)
