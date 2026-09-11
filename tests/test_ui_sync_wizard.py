"""Qt regression coverage for the explicit sync-acceptance workflow."""

import numpy as np
from PySide6.QtWidgets import QDialogButtonBox

from avialsync.engine.sync_worker import EventEvidenceSpec
from avialsync.ui.sync_wizard import SyncWizard


def test_sync_wizard_requires_preview_before_acceptance(qtbot) -> None:
    """The dialog cannot apply an uninspected alignment proposal."""
    reference = EventEvidenceSpec("sensor:ttl", np.arange(0.0, 10.0, 1.0))
    target = EventEvidenceSpec("video:camera", np.arange(0.0, 10.0, 1.0) + 1.25)
    wizard = SyncWizard([reference], [target])
    qtbot.addWidget(wizard)
    wizard.show()

    accept = wizard._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not accept.isEnabled()

    wizard._preview()
    qtbot.waitUntil(lambda: wizard.proposal is not None, timeout=3000)

    assert wizard.proposal is not None
    assert accept.isEnabled()
    assert "fitted from 10 of 10 events" in wizard._summary.text()
    qtbot.waitUntil(lambda: wizard._thread is None, timeout=3000)


def test_sync_wizard_allows_explicit_manual_fallback(qtbot) -> None:
    """Ambiguous field recordings can be persisted only through an explicit manual choice."""
    evidence = EventEvidenceSpec("sensor:ttl", np.arange(0.0, 3.0, 1.0))
    wizard = SyncWizard([evidence], [EventEvidenceSpec("video:camera", np.arange(3.0))])
    qtbot.addWidget(wizard)
    wizard._manual_offset.setValue(1.25)
    wizard._manual_drift.setValue(4.0)

    wizard._use_manual_mapping()

    assert wizard.proposal is not None
    assert wizard.proposal.fit.offset == 1.25
    assert wizard.proposal.fit.drift_ppm == 4.0


def test_a_manual_mapping_counts_nothing_and_claims_nothing(qtbot) -> None:
    """It is applicable because the user chose it, never acceptable on evidence.

    The fallback used to declare three matched events and a zero maximum
    residual so that `acceptable` -- which needs three matches -- would let it
    through, and those numbers were then persisted as if measured.
    """
    from avialsync.core.sync import AlignmentMethod

    reference = EventEvidenceSpec("sensor:ttl", np.arange(0.0, 10.0, 1.0))
    target = EventEvidenceSpec("video:camera", np.arange(0.0, 10.0, 1.0) + 1.25)
    wizard = SyncWizard([reference], [target])
    qtbot.addWidget(wizard)

    wizard._manual_offset.setValue(1.25)
    wizard._use_manual_mapping()

    proposal = wizard.proposal
    assert proposal is not None
    assert proposal.fit.method is AlignmentMethod.MANUAL
    assert proposal.fit.matched_count == 0
    assert not proposal.acceptable, "a typed number has no evidence to be acceptable on"
    assert proposal.applicable, "but the user explicitly chose it"
    assert wizard._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert "set by hand" in wizard._summary.text() or "no evidence" in wizard._summary.text()


def test_a_refused_fit_says_which_evidence_to_change(qtbot) -> None:
    """A disabled Accept with no reason beside it is the shape to avoid."""
    # A uniform train against a target with slack: many lags fit equally well.
    reference = EventEvidenceSpec("sensor:ttl", np.arange(0.0, 12.0, 1.0))
    target = EventEvidenceSpec("video:camera", np.arange(0.0, 30.0, 1.0))
    wizard = SyncWizard([reference], [target])
    qtbot.addWidget(wizard)

    wizard._preview()
    qtbot.waitUntil(lambda: wizard._thread is None, timeout=3000)

    assert not wizard._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    text = wizard._summary.text()
    assert "No mapping proposed" in text or "Cannot accept" in text


def test_the_wizard_does_not_block_the_window_it_asks_about(qtbot) -> None:
    """Rule 11 permits a modal for a dialog the user asked for. This declines it.

    The natural question at a forty-millisecond outlier is what the footage
    looks like there, and under `exec()` it could not be asked at all.
    """
    reference = EventEvidenceSpec("sensor:ttl", np.arange(0.0, 10.0, 1.0))
    target = EventEvidenceSpec("video:camera", np.arange(0.0, 10.0, 1.0) + 1.25)
    wizard = SyncWizard([reference], [target])
    qtbot.addWidget(wizard)

    wizard.show()
    qtbot.waitExposed(wizard)

    assert not wizard.isModal()


def test_a_clicked_point_is_forwarded_for_seeking(qtbot) -> None:
    reference = EventEvidenceSpec("sensor:ttl", np.arange(0.0, 10.0, 1.0))
    target = EventEvidenceSpec("video:camera", np.arange(0.0, 10.0, 1.0) + 1.25)
    wizard = SyncWizard([reference], [target])
    qtbot.addWidget(wizard)

    seen: list[float] = []
    wizard.seek_requested.connect(seen.append)
    wizard._evidence.point_selected.emit(42.5)

    assert seen == [42.5]
