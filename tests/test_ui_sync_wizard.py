"""Qt regression coverage for the explicit sync-acceptance workflow."""

import numpy as np
import pytest
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
    # Ten pulses across nine seconds cannot support a rate -- 1 ppm over that
    # span is nine microseconds -- so the automatic ladder reports the offset it
    # measured and declines to quote a drift it cannot resolve.
    summary = wizard._summary.text()
    assert "10 of 10 events" in summary
    assert "no rate fitted" in summary
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


def test_the_tolerance_that_judged_the_fit_is_visible(qtbot) -> None:
    """It was nowhere on the dialog, and it decides which events counted.

    Derived from the pulse rate it is a quarter of the median interval -- at
    1 Hz, 250 ms, which accepts a 100 ms misalignment without complaint. A user
    who needs better cannot know to ask while the figure is invisible.
    """
    # Irregular, so the ambiguity guard is not what is under test here.
    rng = np.random.default_rng(71)
    reference = np.cumsum(rng.uniform(0.5, 1.5, 40))
    wizard = SyncWizard(
        [EventEvidenceSpec("sensor:ttl", reference)],
        [EventEvidenceSpec("cam.mp4", reference + 1.25)],
    )
    qtbot.addWidget(wizard)

    wizard._preview()
    qtbot.waitUntil(lambda: wizard._thread is None, timeout=5000)

    assert wizard.proposal is not None
    # A quarter of the smaller median interval, which for this train is ~1 s.
    assert wizard.proposal.tolerance == pytest.approx(0.25, rel=0.25)
    assert f"{wizard.proposal.tolerance:.6f}" in wizard._tolerance.toolTip()


def test_a_typed_tolerance_is_what_the_fit_is_judged_by(qtbot) -> None:
    """The point of showing it: a user can demand the precision they need."""
    rng = np.random.default_rng(72)
    reference = np.cumsum(rng.uniform(0.5, 1.5, 60))
    # Scatter, not a shift. A constant 40 ms offset is absorbed into the offset
    # term -- which is exactly what the fit is for -- and leaves no residual for
    # any tolerance to judge. Jitter is what a tolerance actually decides about.
    jittered = reference + 1.25 + rng.normal(0.0, 0.04, len(reference))
    wizard = SyncWizard(
        [EventEvidenceSpec("sensor:ttl", reference)],
        [EventEvidenceSpec("cam.mp4", np.sort(jittered))],
    )
    qtbot.addWidget(wizard)

    loose = SyncWizard(
        [EventEvidenceSpec("sensor:ttl", reference)],
        [EventEvidenceSpec("cam.mp4", np.sort(jittered))],
    )
    qtbot.addWidget(loose)
    loose._preview()
    qtbot.waitUntil(lambda: loose._thread is None, timeout=5000)
    assert loose.proposal is not None and loose.proposal.acceptable

    wizard._tolerance.setValue(0.005)
    wizard._preview()
    qtbot.waitUntil(lambda: wizard._thread is None, timeout=5000)

    # The same evidence, judged by the precision the work needs instead of by
    # the pulse rate, no longer passes.
    assert wizard.proposal is None or not wizard.proposal.acceptable


def test_leaving_it_at_zero_means_derive_it(qtbot) -> None:
    from avialsync.engine.sync_worker import SyncWorker

    worker = SyncWorker(
        EventEvidenceSpec("a", np.arange(0.0, 10.0, 1.0)),
        EventEvidenceSpec("b", np.arange(0.0, 10.0, 1.0) + 0.5),
    )
    assert worker._tolerance is None


class TestRestrictingTheFit:
    """ "The first thirty seconds are garbage" is a routine scientific control.

    And it changes what the result claims, so the window goes into the record
    rather than staying a detail of how the number was produced.
    """

    def _wizard(self, qtbot):
        rng = np.random.default_rng(81)
        reference = np.cumsum(rng.uniform(0.5, 1.5, 120))
        wizard = SyncWizard(
            [EventEvidenceSpec("sensor:ttl", reference)],
            [EventEvidenceSpec("cam.mp4", reference + 1.25)],
        )
        qtbot.addWidget(wizard)
        wizard._preview()
        qtbot.waitUntil(lambda: wizard._thread is None, timeout=5000)
        return wizard, reference

    def test_no_window_by_default(self, qtbot) -> None:
        wizard, _ = self._wizard(qtbot)
        assert wizard._evidence.restriction() is None
        assert wizard.proposal is not None
        assert wizard.proposal.fit.restricted_to is None

    def test_enabling_it_covers_the_middle_not_everything(self, qtbot) -> None:
        """A window covering all of it would record a restriction restricting nothing."""
        wizard, reference = self._wizard(qtbot)

        wizard._restrict.setChecked(True)

        window = wizard._evidence.restriction()
        assert window is not None
        assert window[0] > reference[0]
        assert window[1] < reference[-1]

    def test_the_fit_uses_only_events_inside_it(self, qtbot) -> None:
        wizard, reference = self._wizard(qtbot)
        everything = wizard.proposal.fit.matched_count

        wizard._restrict.setChecked(True)
        wizard._preview()
        qtbot.waitUntil(lambda: wizard._thread is None, timeout=5000)

        assert wizard.proposal.fit.matched_count < everything

    def test_the_window_is_part_of_the_record(self, qtbot) -> None:
        wizard, _ = self._wizard(qtbot)

        wizard._restrict.setChecked(True)
        window = wizard._evidence.restriction()
        wizard._preview()
        qtbot.waitUntil(lambda: wizard._thread is None, timeout=5000)

        assert wizard.proposal.fit.restricted_to == pytest.approx(window)
        assert "claiming nothing outside that window" in wizard.proposal.fit.describe()

    def test_clearing_it_returns_to_the_whole_recording(self, qtbot) -> None:
        wizard, _ = self._wizard(qtbot)
        wizard._restrict.setChecked(True)

        wizard._restrict.setChecked(False)
        wizard._preview()
        qtbot.waitUntil(lambda: wizard._thread is None, timeout=5000)

        assert wizard.proposal.fit.restricted_to is None

    def test_a_window_with_nothing_in_it_says_so(self, qtbot) -> None:
        from avialsync.engine.sync_worker import SyncWorker

        reference = np.arange(0.0, 50.0, 1.0)
        worker = SyncWorker(
            EventEvidenceSpec("a", reference),
            EventEvidenceSpec("b", reference + 1.0),
            restrict_to=(1000.0, 1001.0),
        )
        errors: list[str] = []
        worker.error.connect(errors.append)

        worker.run()

        assert errors and "Widen the window" in errors[0]

    def test_restricting_before_a_preview_asks_for_one(self, qtbot) -> None:
        """There is no evidence to choose a window from yet."""
        wizard = SyncWizard(
            [EventEvidenceSpec("sensor:ttl", np.arange(0.0, 10.0, 1.0))],
            [EventEvidenceSpec("cam.mp4", np.arange(0.0, 10.0, 1.0) + 1.0)],
        )
        qtbot.addWidget(wizard)

        wizard._restrict.setChecked(True)

        assert not wizard._restrict.isChecked()
        assert "Preview a fit first" in wizard._summary.text()
