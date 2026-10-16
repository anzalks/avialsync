"""Alignment dialog states that told the user something untrue or hid what mattered."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QDialogButtonBox
from pytestqt.qtbot import QtBot

from avialsync.core.sync import AlignmentMethod, SyncFit, SyncMatch, SyncProposal
from avialsync.engine.sync_worker import EventEvidenceSpec, SignalEvidenceSpec
from avialsync.ui import sync_review
from avialsync.ui.sync_wizard import SyncWizard


@pytest.fixture
def wizard(qtbot: QtBot) -> SyncWizard:
    times = np.cumsum(np.random.default_rng(73).uniform(0.8, 1.2, 50))
    widget = SyncWizard(
        [EventEvidenceSpec("DAQ : sync", times)],
        [EventEvidenceSpec("front.mp4", times + 1.25)],
    )
    qtbot.addWidget(widget)
    return widget


def _preview(wizard: SyncWizard, qtbot: QtBot) -> None:
    wizard._preview()
    qtbot.waitUntil(lambda: wizard._thread is None, timeout=5000)
    assert wizard.proposal is not None


def _apply(wizard: SyncWizard):
    return wizard._buttons.button(QDialogButtonBox.StandardButton.Ok)


def test_a_fresh_dialog_does_not_claim_a_stale_result(wizard: SyncWizard) -> None:
    """Restoring its own selection ran the discard path before any preview."""
    assert "out of date" not in wizard._status.text().lower()
    assert "out of date" not in wizard._effective_tolerance.text().lower()


def test_a_changed_setting_marks_the_drawn_evidence_stale(wizard: SyncWizard, qtbot: QtBot) -> None:
    _preview(wizard, qtbot)
    assert wizard._evidence._headline.isHidden()

    wizard._precision_requirement.setValue(0.002)

    assert "out of date" in wizard._status.text().lower()
    assert not wizard._evidence._headline.isHidden()
    assert "out of date" in wizard._evidence._headline.text().lower()
    assert wizard._evidence._reading.text() == ""


def test_coverage_leads_until_a_fit_exists(wizard: SyncWizard, qtbot: QtBot) -> None:
    panels = wizard._evidence._panels
    assert panels.currentIndex() == panels.count() - 1

    _preview(wizard, qtbot)

    assert panels.currentIndex() == 0


def test_the_result_states_the_numbers_it_is_judged_by(wizard: SyncWizard, qtbot: QtBot) -> None:
    _preview(wizard, qtbot)
    status = wizard._status.text()

    assert "moves" in status
    assert "events matched" in status
    assert "RMS" in status
    assert "precision" in status


def test_widening_a_narrowed_dialog_shows_both_pages(wizard: SyncWizard, qtbot: QtBot) -> None:
    """removeTab left the pages hidden, so only the footer remained."""
    wizard.show()
    wizard.setMaximumSize(2000, 1500)
    wizard.resize(600, 560)
    qtbot.waitUntil(lambda: wizard._pages.count() == 2)
    wizard.resize(1600, 700)
    qtbot.waitUntil(lambda: wizard._pages.count() == 0)

    assert not wizard._scroll.isHidden()
    assert not wizard._result_scroll.isHidden()


def test_narrowing_after_a_preview_keeps_the_result_in_view(
    wizard: SyncWizard, qtbot: QtBot
) -> None:
    wizard.show()
    wizard.setMaximumSize(2000, 1500)
    wizard.resize(1600, 700)
    qtbot.waitUntil(lambda: wizard._pages.count() == 0)
    _preview(wizard, qtbot)
    wizard.resize(600, 560)
    qtbot.waitUntil(lambda: wizard._pages.count() == 2)

    assert wizard._pages.currentWidget() is wizard._result_scroll


def _proposal(fit: SyncFit, tolerance: float) -> SyncProposal:
    matches = (SyncMatch(1.0, 2.25, 0.0), SyncMatch(5.0, 6.25, 0.0))
    return SyncProposal("DAQ : sync", "front.mp4", fit, matches, tolerance)


def test_a_refused_fit_opens_the_reason_where_it_is_written(wizard: SyncWizard) -> None:
    fit = SyncFit(1.25, 0.0, 0.0, 0.0, 2, 0, reference_count=50, target_count=50)
    wizard._on_finished(_proposal(fit, 0.25))

    assert wizard._fit_details.more_toggle.isChecked()
    assert "Cannot accept" in wizard._summary.text()
    assert wizard._status.text().startswith("Cannot apply:")
    assert "matched" in wizard._status.text()


def test_an_exact_mapping_says_no_tolerance_was_used(wizard: SyncWizard) -> None:
    fit = SyncFit(
        0.0, 0.0, 0.0, 0.0, 50, 0, reference_count=50, target_count=50,
        method=AlignmentMethod.EXACT,
    )  # fmt: skip
    wizard._on_finished(_proposal(fit, 0.0))

    assert "0 s" not in wizard._effective_tolerance.text()
    assert "Not used" in wizard._effective_tolerance.text()


def test_a_manual_preview_that_moves_nothing_cannot_be_applied(
    wizard: SyncWizard, qtbot: QtBot
) -> None:
    wizard._mode_combo.setCurrentIndex(wizard._mode_combo.findData("manual"))
    wizard._manual_offset.setValue(0.0)
    wizard._preview()

    assert wizard.proposal is None
    assert not _apply(wizard).isVisible() or not _apply(wizard).isEnabled()
    assert "current timing" in wizard._status.text()

    wizard._manual_offset.setValue(0.5)
    wizard._preview()

    assert wizard.proposal is not None
    assert "Set by hand" in wizard._status.text()


def test_a_double_click_on_preview_does_not_apply(wizard: SyncWizard, qtbot: QtBot) -> None:
    """Apply takes Preview's slot; the second click landed on it."""
    wizard.show()
    wizard._mode_combo.setCurrentIndex(wizard._mode_combo.findData("manual"))
    wizard._manual_offset.setValue(0.5)
    wizard._preview()
    apply = _apply(wizard)
    assert apply.isVisible()
    accepted: list[bool] = []
    wizard.accepted.connect(lambda: accepted.append(True))
    centre = QPointF(apply.rect().center())
    for kind in (QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease):
        event = QMouseEvent(
            kind,
            centre,
            apply.mapToGlobal(centre),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseButtonRelease else Qt.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(apply, event)

    assert accepted == []

    qtbot.mouseClick(apply, Qt.MouseButton.LeftButton)

    assert accepted == [True]


def test_the_sync_line_is_the_default_reference(qtbot: QtBot) -> None:
    """The first listed channel was the default: a sine, not the TTL two rows down."""
    cache = Path(".")
    widget = SyncWizard(
        [
            SignalEvidenceSpec("rig.csv : ch0", cache, "ch0", clock_id="rig.csv"),
            SignalEvidenceSpec("rig.csv : ch1", cache, "ch1", clock_id="rig.csv"),
            SignalEvidenceSpec("rig.csv : TTL", cache, "TTL", clock_id="rig.csv"),
        ],
        [EventEvidenceSpec("front.mp4", np.arange(10.0), is_video_time_axis=True)],
    )
    qtbot.addWidget(widget)

    assert widget._reference_combo.currentIndex() == 2


def test_the_reference_threshold_defaults_to_the_signal_midpoint(wizard: SyncWizard) -> None:
    assert wizard._chosen_reference_threshold() is None
    wizard._threshold.setValue(2.5)
    assert wizard._chosen_reference_threshold() == 2.5


def test_identical_names_are_numbered_not_given_full_paths(qtbot: QtBot) -> None:
    times = np.arange(10.0)
    deep = "/var/folders/xx/abc/tmpchlwqkns/signal_base.csv"
    widget = SyncWizard(
        [EventEvidenceSpec("DAQ", times)],
        [
            EventEvidenceSpec(deep, times, clock_id=deep, display_name="signal_base.csv"),
            EventEvidenceSpec(deep + "#2", times, clock_id=deep, display_name="signal_base.csv"),
        ],
    )
    qtbot.addWidget(widget)
    names = [widget._target_combo.itemText(i) for i in range(widget._target_combo.count())]

    assert all("/var/folders" not in name for name in names)
    assert len(set(names)) == 2


def test_quality_line_names_why_precision_is_unverified() -> None:
    fit = SyncFit(
        0.0, 0.0, 0.0001, 0.0002, 40, 0, reference_count=40, target_count=40,
        precision_requirement=0.001, precision_verified=False,
        precision_shortfall="a 9.000 s gap between matched events could hide 1.800 ms",
    )  # fmt: skip
    line = sync_review.quality_line(_proposal(fit, 0.25))

    assert "precision unverified at 1 ms: a 9.000 s gap" in line
    assert "40 of 40 events matched (100%)" in line


def test_tolerance_and_precision_read_in_milliseconds(wizard: SyncWizard) -> None:
    """Results are in ms; settings typed as "0.001000 s" beside them were not."""
    precision = wizard._precision_requirement

    assert precision.value() == pytest.approx(0.001)
    assert precision.text().endswith("ms")
    assert precision.text().startswith("1")

    precision.lineEdit().setText("2.5 ms")
    precision.interpretText()

    assert precision.value() == pytest.approx(0.0025)
    assert wizard._tolerance.text() == wizard._tolerance.specialValueText()


def test_drift_tooltip_also_states_ppm(wizard: SyncWizard) -> None:
    wizard._manual_drift.setValue(36.0)

    assert "+10 ppm" in wizard._manual_drift.toolTip()


def test_reopening_after_apply_offers_the_next_camera(qtbot: QtBot) -> None:
    """The remembered target was the camera the last Apply had already placed."""
    from avialsync.core.session import SyncProvenance
    from avialsync.ui.main_window import MainWindow

    parent = MainWindow()
    qtbot.addWidget(parent)
    reference = [EventEvidenceSpec("daq", np.arange(10.0))]
    targets = [EventEvidenceSpec(name, np.arange(10.0)) for name in ("a", "b", "c")]
    first = SyncWizard(reference, targets, parent)
    qtbot.addWidget(first)
    first.reject()
    parent._sync_provenance.append(SyncProvenance("daq", "a", 0.0, 0.0, 0.0, 0.0, 10, 0, 0.1))

    second = SyncWizard(reference, targets, parent)
    qtbot.addWidget(second)

    assert second.target_id == "b"


def test_manual_mode_shows_coverage_not_an_empty_fit_panel(wizard: SyncWizard) -> None:
    wizard._mode_combo.setCurrentIndex(wizard._mode_combo.findData("manual"))

    assert not wizard._evidence.isHidden()
    assert wizard._fit_details.isHidden()
    panels = wizard._evidence._panels
    assert panels.currentIndex() == panels.count() - 1

    wizard._mode_combo.setCurrentIndex(wizard._mode_combo.findData("events"))
    assert not wizard._fit_details.isHidden()
