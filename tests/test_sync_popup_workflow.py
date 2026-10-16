"""Screen fit and proposal freshness in the alignment dialog."""

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox, QScrollArea
from pytestqt.qtbot import QtBot

from avialsync.engine.sync_worker import EventEvidenceSpec
from avialsync.ui.coverage_lanes import SourceCoverage
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


def preview(wizard: SyncWizard, qtbot: QtBot) -> None:
    wizard._preview()
    qtbot.waitUntil(lambda: wizard._thread is None, timeout=5000)
    assert wizard.proposal is not None


@pytest.mark.parametrize("control", ["_precision_requirement", "_manual_offset", "_manual_drift"])
def test_editing_a_parameter_requires_a_new_preview(
    wizard: SyncWizard, qtbot: QtBot, control: str
) -> None:
    preview(wizard, qtbot)
    spin = getattr(wizard, control)
    spin.setValue(spin.value() + spin.singleStep())
    assert wizard.proposal is None
    assert not wizard._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_strategy_changes_require_a_new_preview(wizard: SyncWizard, qtbot: QtBot) -> None:
    preview(wizard, qtbot)
    wizard._strategy_combo.setCurrentIndex(1)
    assert wizard.proposal is None


def test_expansion_and_results_do_not_move_the_footer_off_screen(
    wizard: SyncWizard, qtbot: QtBot
) -> None:
    wizard.show()
    wizard.resize(760, 560)
    preview(wizard, qtbot)
    # Preview now opens Results; expand controls on the Settings page itself.
    wizard._pages.setCurrentWidget(wizard._scroll)
    wizard.steps.more_toggle.setChecked(True)
    wizard._scroll.ensureWidgetVisible(wizard._restrict)
    qtbot.waitUntil(
        lambda: (
            wizard._scroll.viewport()
            .rect()
            .contains(
                wizard._restrict.rect().translated(
                    wizard._restrict.mapTo(
                        wizard._scroll.viewport(), wizard._restrict.rect().topLeft()
                    )
                )
            )
        )
    )
    footer = wizard._buttons
    assert wizard.rect().contains(footer.geometry())
    assert wizard.height() <= wizard.screen().availableGeometry().height()
    assert wizard._scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_manual_fields_are_revealed_by_the_mode(wizard: SyncWizard) -> None:
    wizard._mode_combo.setCurrentIndex(wizard._mode_combo.findData("manual"))
    assert not wizard._manual_fields.isHidden()
    assert wizard._threshold.isHidden()
    assert wizard._reference_combo.isHidden()
    assert wizard._strategy_combo.isHidden()


def test_a_result_from_invalidated_work_cannot_be_accepted(
    wizard: SyncWizard, qtbot: QtBot
) -> None:
    preview(wizard, qtbot)
    old = wizard.proposal
    wizard._preview()
    wizard._precision_requirement.setValue(0.0001)
    wizard._on_finished(old)
    qtbot.waitUntil(lambda: wizard._thread is None, timeout=5000)
    assert wizard.proposal is None


def test_evidence_tabs_keep_the_domain_after_resizing(wizard: SyncWizard, qtbot: QtBot) -> None:
    wizard.show()
    preview(wizard, qtbot)
    wizard.resize(760, 560)
    wizard._evidence._panels.setCurrentIndex(1)
    wizard._evidence._plot.getViewBox().setXRange(10.0, 20.0, padding=0.0)
    wizard._evidence._panels.setCurrentIndex(0)
    qtbot.waitUntil(
        lambda: abs(wizard._evidence._pairing.getViewBox().viewRange()[0][0] - 10.0) < 0.01
    )
    assert wizard._evidence._pairing.getViewBox().viewRange()[0] == pytest.approx([10.0, 20.0])


def test_larger_text_and_expanded_options_still_fit_without_horizontal_scrolling(
    wizard: SyncWizard, qtbot: QtBot
) -> None:
    font = wizard.font()
    font.setPointSizeF(font.pointSizeF() * 1.5)
    wizard.setFont(font)
    wizard.show()
    wizard.resize(760, 560)
    wizard.steps.more_toggle.setChecked(True)
    # Laid out once the expanded options are on screen. Whether the column
    # then also needs to scroll vertically depends on the platform's fonts;
    # that it never needs to scroll sideways does not.
    qtbot.waitUntil(lambda: wizard._strategy_combo.isVisible())
    # Eventually, not at once: a vertical bar appearing narrows the viewport
    # one layout pass before the content follows it.
    qtbot.waitUntil(lambda: wizard._scroll.widget().width() <= wizard._scroll.viewport().width())
    assert wizard.rect().contains(wizard._buttons.geometry())


def test_focus_never_scrolls_the_settings_sideways(wizard: SyncWizard, qtbot: QtBot) -> None:
    """With no horizontal bar, a sideways scroll clipped labels with no way back."""
    wizard.show()
    wizard.resize(420, 560)
    wizard.steps.more_toggle.setChecked(True)
    qtbot.waitUntil(lambda: wizard._precision_requirement.isVisible())
    wizard._precision_requirement.setFocus()
    qtbot.waitUntil(lambda: wizard._precision_requirement.hasFocus())

    assert wizard._scroll.horizontalScrollBar().value() == 0


def test_many_recordings_scroll_within_the_coverage_tab(wizard: SyncWizard, qtbot: QtBot) -> None:
    wizard.set_coverage(
        [SourceCoverage(label=f"camera_{index}", data=(0.0, 100.0)) for index in range(30)]
    )
    wizard.show()
    wizard.resize(760, 560)
    wizard._evidence._panels.setCurrentIndex(2)
    coverage = wizard._evidence._panels.currentWidget()
    assert isinstance(coverage, QScrollArea)
    qtbot.waitUntil(lambda: coverage.verticalScrollBar().maximum() > 0)
    assert wizard.rect().contains(wizard._buttons.geometry())
