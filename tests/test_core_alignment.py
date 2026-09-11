"""The model is decided by the evidence and the span, never offered as a choice."""

from __future__ import annotations

import numpy as np
import pytest

from avialsync.core.alignment import (
    MIN_PIECEWISE_KNOTS,
    choose_method,
    demote_to_shift,
    drift_is_identifiable,
    fit_piecewise,
    residual_trend,
)
from avialsync.core.errors import SyncEvidenceError
from avialsync.core.sync import AlignmentMethod, SyncFit
from avialsync.core.triggers import Reconciliation, TriggerKind


def _irregular(count: int, *, seed: int, period: float = 1.0) -> np.ndarray:
    """Distinguishable pulses, so the ambiguity guard is not the thing under test."""
    rng = np.random.default_rng(seed)
    return np.cumsum(rng.uniform(period * 0.5, period * 1.5, count))


class TestARateNeedsASpanToBeMeasuredOver:
    def test_a_large_rate_over_a_short_span_is_not_identifiable(self) -> None:
        """7,200 ppm across one second is seven milliseconds."""
        assert not drift_is_identifiable(7200.0, span=1.0, tolerance=0.025)

    def test_the_same_rate_over_a_long_span_is(self) -> None:
        assert drift_is_identifiable(7200.0, span=400.0, tolerance=0.025)

    def test_a_real_crystal_error_needs_a_real_recording(self) -> None:
        """50 ppm is 50 us a second: minutes of recording before it shows."""
        assert not drift_is_identifiable(50.0, span=10.0, tolerance=0.005)
        assert drift_is_identifiable(50.0, span=1800.0, tolerance=0.005)

    def test_a_zero_span_can_identify_nothing(self) -> None:
        assert not drift_is_identifiable(1000.0, span=0.0, tolerance=0.01)


class TestReadingWhatTheModelDidNotAbsorb:
    def test_flat_residuals_have_no_trend(self) -> None:
        times = np.arange(0.0, 100.0, 1.0)
        rng = np.random.default_rng(1)
        assert residual_trend(times, rng.normal(0.0, 0.001, len(times))) < 0.005

    def test_a_ramp_is_reported_as_the_drift_across_the_recording(self) -> None:
        times = np.arange(0.0, 100.0, 1.0)
        residuals = 0.002 * times  # 2 ms per second
        assert residual_trend(times, residuals) == pytest.approx(0.198, abs=0.01)

    def test_too_few_points_to_read_a_shape(self) -> None:
        assert residual_trend(np.array([0.0, 1.0]), np.array([0.0, 1.0])) == 0.0


class TestTheLadder:
    def test_two_events_are_unvalidated_not_perfect(self) -> None:
        """They determine a line and leave nothing to check it with."""
        method = choose_method(
            TriggerKind.SPARSE_EVENTS,
            reconciliation=None,
            matched_count=2,
            span=100.0,
            drift_ppm=0.0,
            tolerance=0.01,
        )
        assert method is AlignmentMethod.UNVALIDATED

    def test_fewer_than_two_is_not_an_alignment(self) -> None:
        with pytest.raises(SyncEvidenceError, match="at least two"):
            choose_method(
                TriggerKind.SPARSE_EVENTS,
                reconciliation=None,
                matched_count=1,
                span=100.0,
                drift_ppm=0.0,
                tolerance=0.01,
            )

    def test_a_strobe_whose_counts_agree_is_exact(self) -> None:
        method = choose_method(
            TriggerKind.FRAME_STROBE,
            reconciliation=Reconciliation(500, 500, TriggerKind.FRAME_STROBE),
            matched_count=500,
            span=100.0,
            drift_ppm=30.0,
            tolerance=0.001,
        )
        assert method is AlignmentMethod.EXACT

    def test_a_trigger_whose_counts_agree_is_not(self) -> None:
        """Agreement on a requested exposure is the absence of evidence."""
        method = choose_method(
            TriggerKind.FRAME_TRIGGER,
            reconciliation=Reconciliation(500, 500, TriggerKind.FRAME_TRIGGER),
            matched_count=500,
            span=1000.0,
            drift_ppm=30.0,
            tolerance=0.001,
        )
        assert method is not AlignmentMethod.EXACT
        assert method is AlignmentMethod.AFFINE

    def test_a_shared_sync_train_goes_piecewise(self) -> None:
        """Unpredictable drift: no single rate has to hold for the recording."""
        method = choose_method(
            TriggerKind.SYNC_TRAIN,
            reconciliation=None,
            matched_count=3600,
            span=3600.0,
            drift_ppm=40.0,
            tolerance=0.01,
        )
        assert method is AlignmentMethod.PIECEWISE

    def test_a_sync_train_with_too_few_edges_does_not(self) -> None:
        method = choose_method(
            TriggerKind.SYNC_TRAIN,
            reconciliation=None,
            matched_count=MIN_PIECEWISE_KNOTS - 1,
            span=3600.0,
            drift_ppm=40.0,
            tolerance=0.01,
        )
        assert method is not AlignmentMethod.PIECEWISE

    def test_a_span_too_short_for_a_rate_settles_on_shift(self) -> None:
        method = choose_method(
            TriggerKind.SPARSE_EVENTS,
            reconciliation=None,
            matched_count=40,
            span=2.0,
            drift_ppm=500.0,
            tolerance=0.05,
        )
        assert method is AlignmentMethod.SHIFT


class TestDemotion:
    def test_an_unsupportable_rate_is_dropped_not_quoted(self) -> None:
        fit = SyncFit(
            offset=1.25,
            drift_ppm=7201.0,
            rms_residual=0.001,
            max_residual=0.003,
            matched_count=11,
            rejected_count=0,
            reference_count=11,
        )

        demoted = demote_to_shift(fit)

        assert demoted.method is AlignmentMethod.SHIFT
        assert demoted.drift_ppm == 0.0
        assert demoted.offset == pytest.approx(1.25), "the offset was measured; it stays"
        assert "no rate fitted" in demoted.describe()


class TestPiecewise:
    def test_it_follows_drift_no_line_could(self) -> None:
        """Two oscillators in a warming room wander; the wander is not a line."""
        reference = _irregular(200, seed=21)
        # A rate that changes sign halfway: no single affine fit describes it.
        wobble = 0.02 * np.sin(reference / reference[-1] * 2 * np.pi)
        target = reference + 1.5 + wobble

        proposal = fit_piecewise(reference, target, reference_id="sensor:sync", target_id="cam.mp4")

        assert proposal.fit.method is AlignmentMethod.PIECEWISE
        mapping = proposal.fit.to_time_map()
        assert mapping.has_exact_mapping
        # At every knot the mapping is exact, including where a line would be
        # furthest out.
        for index in (0, 50, 100, 150, len(reference) - 1):
            assert mapping.to_source(reference[index]) == pytest.approx(target[index], abs=1e-9)

    def test_it_reports_no_residual_because_it_has_none(self) -> None:
        reference = _irregular(60, seed=22)
        proposal = fit_piecewise(
            reference, reference + 0.75, reference_id="sensor:sync", target_id="cam.mp4"
        )

        assert proposal.fit.rms_residual == 0.0
        assert proposal.fit.max_residual == 0.0
        assert "no single rate assumed" in proposal.fit.describe()

    def test_too_few_knots_is_refused_with_the_reason(self) -> None:
        reference = np.array([0.0, 1.7, 4.1])
        with pytest.raises(SyncEvidenceError, match="straight line with extra steps"):
            fit_piecewise(
                reference, reference + 0.5, reference_id="sensor:sync", target_id="cam.mp4"
            )

    def test_the_affine_guards_still_apply_first(self) -> None:
        """Matching is delegated, so match rate and ambiguity are checked before
        anything is interpolated."""
        reference = _irregular(400, seed=23)
        with pytest.raises(SyncEvidenceError, match="unit or sample-index mismatch"):
            fit_piecewise(
                reference, reference * 4.35, reference_id="sensor:sync", target_id="cam.mp4"
            )
