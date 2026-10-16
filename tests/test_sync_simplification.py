"""The simplified workflow keeps choices clear without weakening acceptance."""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox
from pytestqt.qtbot import QtBot

from avialsync.core.triggers import TriggerKind
from avialsync.engine.sync_worker import EventEvidenceSpec, SignalEvidenceSpec
from avialsync.ui.app_settings import app_settings
from avialsync.ui.design_tokens import ControlRole, role_of
from avialsync.ui.main_window import MainWindow
from avialsync.ui.sync_wizard import SyncWizard


@pytest.fixture(autouse=True)
def isolated_alignment_preferences() -> Iterator[None]:
    store = app_settings()
    store.remove("alignment")
    yield
    store.remove("alignment")


@pytest.fixture
def wizard(qtbot: QtBot) -> SyncWizard:
    times = np.cumsum(np.random.default_rng(73).uniform(0.8, 1.2, 50))
    widget = SyncWizard(
        [EventEvidenceSpec("DAQ", times)], [EventEvidenceSpec("front.mp4", times + 1.25)]
    )
    qtbot.addWidget(widget)
    widget.show()
    widget.resize(760, 560)
    return widget


def preview(wizard: SyncWizard, qtbot: QtBot) -> None:
    wizard._preview_button.click()
    qtbot.waitUntil(lambda: wizard._thread is None, timeout=5000)
    assert wizard.proposal is not None


def test_narrow_layout_has_one_full_height_page_and_a_fixed_footer(wizard: SyncWizard) -> None:
    assert wizard._pages.count() == 2
    assert wizard._pages.currentWidget() is wizard._scroll
    assert wizard._body.isHidden()
    assert wizard.rect().contains(wizard._buttons.geometry())


def test_preview_apply_and_invalidated_preview_have_one_primary_action(
    wizard: SyncWizard, qtbot: QtBot
) -> None:
    apply = wizard._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert apply.isHidden()
    assert role_of(wizard._preview_button) == ControlRole.PRIMARY
    preview(wizard, qtbot)
    assert wizard._pages.currentWidget() is wizard._result_scroll
    assert not apply.isHidden() and wizard._preview_button.isHidden()
    assert role_of(apply) == ControlRole.PRIMARY
    wizard._precision_requirement.setValue(0.01)
    assert apply.isHidden() and not wizard._preview_button.isHidden()
    assert wizard.proposal is None


def test_resizing_reuses_the_same_evidence_and_proposal(wizard: SyncWizard, qtbot: QtBot) -> None:
    preview(wizard, qtbot)
    proposal, plot = wizard.proposal, wizard._evidence._plot
    wizard.setMaximumSize(2000, 1500)
    wizard.resize(1600, 700)
    qtbot.waitUntil(lambda: wizard._pages.count() == 0)
    assert wizard._body.count() == 2 and not wizard._body.isHidden()
    wizard.resize(760, 560)
    qtbot.waitUntil(lambda: wizard._pages.count() == 2)
    assert wizard.proposal is proposal and wizard._evidence._plot is plot


def test_hidden_drift_remains_effective_in_a_manual_preview(wizard: SyncWizard) -> None:
    wizard._mode_combo.setCurrentIndex(wizard._mode_combo.findData("manual"))
    wizard._manual_drift.setValue(54.0)
    wizard._drift_toggle.setChecked(False)
    assert wizard._manual_drift.isHidden()
    assert "54" in wizard._drift_summary.text()
    wizard._preview_button.click()
    assert wizard.proposal is not None and wizard.proposal.fit.drift_ms_per_hour == 54.0


def test_check_menu_seeks_actual_matched_evidence(wizard: SyncWizard, qtbot: QtBot) -> None:
    assert wizard._review_controls.isHidden()
    preview(wizard, qtbot)
    seen: list[float] = []
    wizard.seek_requested.connect(seen.append)
    wizard._check_button.menu().actions()[-1].trigger()
    assert wizard.proposal is not None
    assert seen == [wizard.proposal.matches[-1].reference_time]
    assert wizard._review_buttons[-1].text() == "Export report…"


def test_return_cannot_accept_a_new_async_result(wizard: SyncWizard, qtbot: QtBot) -> None:
    accepted: list[bool] = []
    wizard.accepted.connect(lambda: accepted.append(True))
    preview(wizard, qtbot)
    wizard._evidence.setFocus()
    qtbot.keyClick(wizard, Qt.Key.Key_Return)
    assert not accepted and wizard.result() == 0


def test_duplicate_filenames_are_distinguishable_without_changing_ids(
    qtbot: QtBot, tmp_path: Path
) -> None:
    targets = [
        EventEvidenceSpec(str(tmp_path / rig / "camera.mp4"), np.arange(10.0))
        for rig in ("rig_a", "rig_b")
    ]
    widget = SyncWizard([], targets, visual_references=targets)
    qtbot.addWidget(widget)
    labels = [widget._target_combo.itemText(i) for i in range(2)]
    assert labels[0] != labels[1]
    assert "rig_a" in labels[0] and "rig_b" in labels[1]
    assert widget._targets == targets


def test_session_labels_are_used_even_when_they_contain_slashes(qtbot: QtBot) -> None:
    parent = MainWindow()
    qtbot.addWidget(parent)
    parent.session_runtime.item_labels["/rig/camera.mp4"] = "Left / overview"
    widget = SyncWizard([], [EventEvidenceSpec("/rig/camera.mp4", np.arange(10.0))], parent)
    qtbot.addWidget(widget)
    assert widget._target_combo.itemText(0) == "Left / overview"


def test_suggestion_does_not_declare_an_exposure_strobe(qtbot: QtBot, tmp_path: Path) -> None:
    reference = SignalEvidenceSpec("daq : ttl", tmp_path, "ttl", clock_id="daq")
    widget = SyncWizard(
        [reference], [EventEvidenceSpec("camera", np.arange(10.0), clock_id="camera")]
    )
    qtbot.addWidget(widget)
    assert widget._mode_combo.currentData() == "events"
    assert not widget._recorded_strobe.isChecked()
    assert reference.kind is TriggerKind.SPARSE_EVENTS


def test_selection_memory_is_session_scoped_and_never_restores_a_proposal(qtbot: QtBot) -> None:
    parent = MainWindow()
    qtbot.addWidget(parent)
    reference = [EventEvidenceSpec("daq", np.arange(10.0))]
    targets = [EventEvidenceSpec(name, np.arange(10.0)) for name in ("a", "b")]
    first = SyncWizard(reference, targets, parent)
    qtbot.addWidget(first)
    first._mode_combo.setCurrentIndex(first._mode_combo.findData("manual"))
    first._target_combo.setCurrentIndex(1)
    first.reject()
    second = SyncWizard(reference, targets, parent)
    qtbot.addWidget(second)
    assert second._mode_combo.currentData() == "manual"
    assert second.target_id == "b" and second.proposal is None
    second.reject()
    parent.session_runtime.generation += 1
    third = SyncWizard(reference, targets, parent)
    qtbot.addWidget(third)
    assert third._mode_combo.currentData() == "events"
    assert third.target_id == "a" and third.proposal is None


def test_layout_expansion_memory_does_not_restore_timing_values(
    wizard: SyncWizard, qtbot: QtBot
) -> None:
    wizard.steps.more_toggle.setChecked(True)
    wizard._fit_details.more_toggle.setChecked(True)
    wizard._drift_toggle.setChecked(True)
    wizard._manual_drift.setValue(54.0)
    wizard.reject()
    reopened = SyncWizard(wizard._event_references, wizard._targets)
    qtbot.addWidget(reopened)
    reopened.show()
    assert reopened.size() == wizard.size()
    assert reopened.steps.more_toggle.isChecked()
    assert reopened._fit_details.more_toggle.isChecked()
    assert reopened._drift_toggle.isChecked()
    assert reopened._manual_drift.value() == 0.0
    assert reopened.proposal is None and not reopened._recorded_strobe.isChecked()


def test_live_font_change_can_switch_to_full_height_pages(wizard: SyncWizard, qtbot: QtBot) -> None:
    wizard.setMaximumSize(2000, 1500)
    font = wizard.font()
    font.setPointSizeF(10.0)
    wizard.setFont(font)
    wizard.resize(1200, 700)
    qtbot.waitUntil(lambda: wizard._pages.count() == 0)
    font.setPointSizeF(30.0)
    wizard.setFont(font)
    qtbot.waitUntil(lambda: wizard._pages.count() == 2)
    assert wizard._scroll.widget().width() <= wizard._scroll.viewport().width()


def test_missing_visual_pairs_have_an_actionable_disabled_preview(qtbot: QtBot) -> None:
    targets = [EventEvidenceSpec(name, np.arange(10.0)) for name in ("a", "b")]
    widget = SyncWizard([], targets, visual_references=targets)
    qtbot.addWidget(widget)
    assert widget._mode_combo.currentData() == "landmarks"
    assert not widget._preview_button.isEnabled()
    assert "Add at least one" in widget._guidance.text()
    widget._landmarks.add_pair()
    assert widget._preview_button.isEnabled()


def test_a_new_dialog_starts_with_different_clocks_when_available(qtbot: QtBot) -> None:
    specs = [EventEvidenceSpec(name, np.arange(10.0)) for name in ("daq_a", "daq_b")]
    widget = SyncWizard(specs, specs)
    qtbot.addWidget(widget)
    assert widget._reference_combo.currentIndex() != widget._target_combo.currentIndex()
    assert widget._preview_button.isEnabled()


def test_old_dialog_cannot_apply_after_the_session_generation_changes(qtbot: QtBot) -> None:
    from avialsync.loaders.video_standard import VideoStandardLoader

    parent = MainWindow()
    qtbot.addWidget(parent)
    path = Path("tests/fixtures/sample_session/camera_1.mp4").resolve()
    loader = VideoStandardLoader()
    loader.open(path, {})
    parent._on_video_opened(str(path), loader, str(path))
    parent._open_sync_wizard()
    widget = parent._sync_wizard
    assert widget is not None
    widget._mode_combo.setCurrentIndex(widget._mode_combo.findData("manual"))
    widget._manual_offset.setValue(0.2)
    widget._preview_button.click()
    assert widget.proposal is not None
    parent.session_runtime.generation += 1
    widget.accept()
    assert widget.result() == 0 and widget.proposal is None
    assert not parent.accepted_alignment_records()
    parent.close()


def test_keyboard_reaches_preview_then_apply_and_undo_restores_timing(qtbot: QtBot) -> None:
    from avialsync.loaders.video_standard import VideoStandardLoader

    parent = MainWindow()
    qtbot.addWidget(parent)
    path = Path("tests/fixtures/sample_session/camera_1.mp4").resolve()
    loader = VideoStandardLoader()
    loader.open(path, {})
    parent._on_video_opened(str(path), loader, str(path))
    mapping = parent.video_grid.panes[0].time_map
    before = mapping.to_master(1.0)
    parent._open_sync_wizard()
    widget = parent._sync_wizard
    assert widget is not None
    widget._mode_combo.setCurrentIndex(widget._mode_combo.findData("manual"))
    chain, seen = widget._manual_offset.nextInFocusChain(), 0
    while chain is not widget._preview_button and seen < 200:
        chain, seen = chain.nextInFocusChain(), seen + 1
    assert chain is widget._preview_button
    assert widget._preview_button.focusPolicy() & Qt.FocusPolicy.TabFocus
    widget._manual_offset.setValue(0.25)
    widget.activateWindow()
    qtbot.waitActive(widget)
    widget._preview_button.setFocus()
    qtbot.keyClick(widget, Qt.Key.Key_Return)
    assert widget.proposal is not None and widget.result() == 0
    apply = widget._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert apply.isVisible() and widget._preview_button.isHidden()
    apply.setFocus()
    qtbot.keyClick(widget, Qt.Key.Key_Return)
    assert widget.result() == 1
    assert mapping.to_master(1.0) == pytest.approx(before - 0.25)
    parent.document.undo(parent._mutations)
    assert mapping.to_master(1.0) == pytest.approx(before)
    parent.close()


def test_preview_takes_the_apply_slot_and_never_accepts(wizard: SyncWizard, qtbot: QtBot) -> None:
    apply = wizard._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert wizard._buttons.buttonRole(wizard._preview_button) == wizard._buttons.buttonRole(apply)
    accepted: list[bool] = []
    wizard.accepted.connect(lambda: accepted.append(True))
    preview(wizard, qtbot)
    assert not accepted and wizard.result() == 0


def test_event_lists_leave_no_empty_threshold_form(wizard: SyncWizard) -> None:
    assert wizard._mode_combo.currentData() == "events"
    assert wizard._event_fields.isHidden()
