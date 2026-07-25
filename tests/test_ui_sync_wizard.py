"""Qt regression coverage for the explicit sync-acceptance workflow."""

import numpy as np
from PySide6.QtWidgets import QDialogButtonBox

from avialview.engine.sync_worker import EventEvidenceSpec
from avialview.ui.sync_wizard import SyncWizard


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
    assert "matched events" in wizard._summary.text()
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
