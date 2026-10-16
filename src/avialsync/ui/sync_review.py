"""Review navigation, live-context checks and report export for alignment."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.errors import ExportError
from avialsync.core.sync import AlignmentMethod, ExactSyncFit, SyncFit, SyncProposal
from avialsync.core.timeline import PreparedExactMapping, TimeMap
from avialsync.ui.design_tokens import ControlRole, apply_role
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread
from avialsync.ui.menu_button import MenuGlyphButton

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow
    from avialsync.ui.sync_wizard import SyncWizard


def install_review(wizard: SyncWizard) -> None:
    """Offer direct verification points without hiding the recording window."""
    wizard._review_controls = QWidget(wizard._results)
    row = QHBoxLayout(wizard._review_controls)
    row.setContentsMargins(0, 0, 0, 0)
    wizard._check_button = QPushButton(tr("Check alignment"), wizard._review_controls)
    wizard._check_button.setAccessibleName(tr("Check alignment"))
    wizard._check_button.setAccessibleDescription(
        tr("Choose a matched event at the beginning, middle or end.")
    )
    menu = QMenu(wizard._check_button)
    wizard._check_button.setMenu(menu)
    actions = []
    for text, fraction in (
        (tr("Beginning"), 0.0),
        (tr("Middle"), 0.5),
        (tr("End"), 1.0),
    ):
        action = menu.addAction(text)
        action.setToolTip(tr("Seek to an observed event to compare the recordings."))
        action.triggered.connect(lambda _checked=False, part=fraction: seek_check(wizard, part))
        actions.append(action)
    row.addWidget(wizard._check_button)
    row.addStretch(1)
    overflow = MenuGlyphButton("more", tr("Alignment result options"), wizard._review_controls)
    overflow.setAccessibleDescription(tr("Export the proposed alignment and its evidence."))
    export = overflow.menu().addAction(tr("Export report…"))
    from avialsync.ui.sync_lifecycle import as_window

    export.triggered.connect(lambda: export_report(as_window(wizard.parentWidget()), wizard))
    row.addWidget(overflow)
    actions.append(export)
    wizard._review_buttons = actions
    outer = wizard._results.layout()
    assert isinstance(outer, QVBoxLayout)
    outer.insertWidget(1, wizard._review_controls)
    set_review_enabled(wizard, False)


def set_review_enabled(wizard: SyncWizard, enabled: bool) -> None:
    wizard._review_controls.setVisible(enabled)
    wizard._check_button.setEnabled(enabled and bool(wizard.proposal and wizard.proposal.matches))
    for index, button in enumerate(wizard._review_buttons):
        if button is not None:
            button.setEnabled(
                enabled and (index == 3 or bool(wizard.proposal and wizard.proposal.matches))
            )


def update_primary(wizard: SyncWizard) -> None:
    """Present one primary action and require a deliberate Apply gesture."""
    apply = wizard._buttons.button(QDialogButtonBox.StandardButton.Ok)
    current = bool(wizard.proposal and wizard.proposal.applicable)
    apply.setVisible(current)
    apply.setEnabled(current)
    apply.setDefault(False)
    wizard._preview_button.setVisible(not current)
    wizard._preview_button.setDefault(False)
    apply_role(apply, ControlRole.PRIMARY if current else ControlRole.SECONDARY)
    apply_role(wizard._preview_button, ControlRole.SECONDARY if current else ControlRole.PRIMARY)


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
    from avialsync.ui import sync_form

    sync_form.update_fields(wizard)


def headline(wizard: SyncWizard, proposal: SyncProposal) -> str:
    """Describe the proposal's actual effect rather than the internal offset sign."""
    from avialsync.ui.sync_lifecycle import as_window, source_mapping

    parent = as_window(wizard.parentWidget())
    current = source_mapping(parent, proposal.target_id) if parent else None
    current = current or TimeMap()
    anchor = proposal.matches[0].target_time if proposal.matches else 0.0
    delta = proposal.fit.to_time_map().to_master(anchor) - current.to_master(anchor)
    direction = tr("later") if delta >= 0 else tr("earlier")
    index = next(
        (i for i, spec in enumerate(wizard._targets) if spec.source_id == proposal.target_id), -1
    )
    name = wizard._target_combo.itemText(index) if index >= 0 else Path(proposal.target_id).name
    movement = tr("{recording} moves {seconds:.3f} s {direction}").format(
        recording=name, seconds=abs(delta), direction=direction
    )
    precision = (
        tr("precision verified") if proposal.fit.precision_verified else tr("precision unverified")
    )
    if not proposal.applicable:
        return tr("Choose different evidence before applying this alignment.")
    return tr("{movement} · {precision}").format(movement=movement, precision=precision)


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
    if parent.session_runtime.generation != wizard._session_generation:
        return (("session", None),)
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
