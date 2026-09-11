"""An unsafe alignment must be refused, never guessed.

`core/sync.py` decides whether independently-clocked sources may be mapped
onto one master timeline. Its guards are the whole safety story: a mapping
that silently proceeds on bad evidence corrupts every downstream time in the
session. These cover the refusal paths (BLUEPRINT.md Phase 6: 100% on core).
"""

from __future__ import annotations

import numpy as np
import pytest

from avialsync.core.sync import (
    SyncEvidenceError,
    extract_ttl_edges,
    fit_exact_index_mapping,
    fit_sync_events,
)


def _pulses(count: int, period: float = 0.1, start: float = 0.0) -> np.ndarray:
    return start + np.arange(count, dtype=np.float64) * period


class TestEvidenceValidation:
    """Malformed timestamp arrays must be rejected before any fitting."""

    @pytest.mark.parametrize(
        ("times", "reason"),
        [
            (np.array([[0.0, 1.0], [2.0, 3.0]]), "two-dimensional"),
            (np.array([0.0, np.nan, 1.0]), "not finite"),
            (np.array([0.0, np.inf]), "infinite"),
        ],
    )
    def test_non_finite_or_multidimensional_events_are_refused(
        self, times: np.ndarray, reason: str
    ) -> None:
        with pytest.raises(SyncEvidenceError, match="one-dimensional"):
            fit_sync_events(times, _pulses(8), reference_id="a", target_id="b")

    def test_unsorted_events_are_refused_rather_than_sorted(self) -> None:
        """Reordering evidence would fabricate a pairing the source never had."""
        unsorted = np.array([0.0, 0.3, 0.1, 0.4])

        with pytest.raises(SyncEvidenceError, match="strictly increasing"):
            fit_sync_events(unsorted, _pulses(8), reference_id="a", target_id="b")

    def test_duplicate_timestamps_are_refused(self) -> None:
        """A repeated timestamp has no single position on the master clock."""
        duplicated = np.array([0.0, 0.1, 0.1, 0.2])

        with pytest.raises(SyncEvidenceError, match="strictly increasing"):
            fit_sync_events(duplicated, _pulses(8), reference_id="a", target_id="b")

    def test_target_is_validated_as_well_as_reference(self) -> None:
        with pytest.raises(SyncEvidenceError, match="Target"):
            fit_sync_events(_pulses(8), np.array([1.0, 0.0]), reference_id="a", target_id="b")


class TestFitPreconditions:
    """Refuse configurations that cannot produce a trustworthy fit."""

    def test_a_source_cannot_be_aligned_to_itself(self) -> None:
        with pytest.raises(SyncEvidenceError, match="must differ"):
            fit_sync_events(_pulses(8), _pulses(8), reference_id="same", target_id="same")

    def test_fewer_than_three_pairs_cannot_support_drift(self) -> None:
        """Two points fit any line exactly, so drift would be unfalsifiable."""
        with pytest.raises(SyncEvidenceError, match="three matched events"):
            fit_sync_events(_pulses(8), _pulses(8), reference_id="a", target_id="b", min_pairs=2)

    def test_too_few_events_for_the_requested_minimum(self) -> None:
        with pytest.raises(SyncEvidenceError, match="events are required in both"):
            fit_sync_events(_pulses(3), _pulses(8), reference_id="a", target_id="b", min_pairs=5)

    @pytest.mark.parametrize("tolerance", [0.0, -1.0, float("nan")])
    def test_tolerance_must_be_finite_and_positive(self, tolerance: float) -> None:
        with pytest.raises(SyncEvidenceError, match="finite and positive"):
            fit_sync_events(
                _pulses(8), _pulses(8), reference_id="a", target_id="b", max_residual=tolerance
            )

    def test_unmatchable_sources_are_refused_not_forced(self) -> None:
        """No alignment is a valid answer; a wrong one is not."""
        reference = _pulses(6, period=0.1)
        target = np.array([0.0, 0.31, 0.57, 0.92, 1.4, 2.3])

        with pytest.raises(SyncEvidenceError, match="satisfies the residual tolerance"):
            fit_sync_events(reference, target, reference_id="a", target_id="b", max_residual=1e-9)


class TestExactIndexMapping:
    """The 1:1 frame mapping has its own overlap requirement."""

    def test_identical_sources_are_refused(self) -> None:
        with pytest.raises(SyncEvidenceError, match="must differ"):
            fit_exact_index_mapping(_pulses(8), _pulses(8), reference_id="s", target_id="s")

    def test_an_offset_beyond_the_overlap_is_refused(self) -> None:
        """Shifting past the end leaves nothing to pair."""
        with pytest.raises(SyncEvidenceError, match="overlapping frames"):
            fit_exact_index_mapping(
                _pulses(4), _pulses(4), reference_id="a", target_id="b", index_offset=10
            )

    def test_a_negative_offset_beyond_the_overlap_is_refused(self) -> None:
        with pytest.raises(SyncEvidenceError, match="overlapping frames"):
            fit_exact_index_mapping(
                _pulses(4), _pulses(4), reference_id="a", target_id="b", index_offset=-10
            )

    def test_a_positive_offset_pairs_from_the_shifted_index(self) -> None:
        """Video frame 0 maps to reference index N, the documented behaviour."""
        proposal = fit_exact_index_mapping(
            _pulses(10), _pulses(10), reference_id="a", target_id="b", index_offset=2
        )

        assert proposal.fit.matched_count == 8
        assert proposal.matches[0].reference_time == pytest.approx(0.2)
        assert proposal.matches[0].target_time == pytest.approx(0.0)


class TestTtlExtraction:
    """Raw edges are evidence; unusable input must not become empty evidence."""

    def test_evidence_needs_a_source_identifier(self) -> None:
        """Anonymous evidence cannot be attributed in saved provenance."""
        with pytest.raises(SyncEvidenceError, match="source identifier"):
            extract_ttl_edges([(np.array([0.0, 1.0]), np.array([0.0, 1.0]))], source_id="")

    def test_rising_edges_are_found_at_the_threshold_crossing(self) -> None:
        times = np.linspace(0.0, 1.0, 11)
        values = np.array([0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0])

        events = extract_ttl_edges([(times, values)], source_id="ttl")

        assert [round(event.time, 3) for event in events] == [0.2, 0.6, 1.0]

    def test_bounce_within_the_minimum_interval_is_suppressed(self) -> None:
        """A contact bounce is one transition, not several."""
        times = np.array([0.0, 0.01, 0.02, 0.03, 0.5, 0.51])
        values = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 1.0])

        events = extract_ttl_edges([(times, values)], source_id="ttl", min_interval=0.1)

        assert [round(event.time, 3) for event in events] == [0.01, 0.51]


def _irregular_train(count: int, *, seed: int) -> np.ndarray:
    """Pulse times with jittered intervals, so exactly one lag can fit.

    A uniform train is ambiguous at every multiple of its period and is refused
    as such; these tests need evidence that reaches the gate being tested.
    """
    rng = np.random.default_rng(seed)
    intervals = rng.uniform(0.5, 1.5, size=count)
    return np.cumsum(intervals)


class TestResidualsCannotSeeTheirOwnMatching:
    """The failures a residual plot is structurally blind to.

    Residuals describe the pairs that were matched and say nothing about
    whether those are the right pairs, so a degenerate match reports a
    *smaller* residual than a correct one. Every guard here fails while the
    residual looks perfect.
    """

    def test_an_impossible_rate_names_the_diagnosis(self) -> None:
        """A 4x rate is not a clock; say what it actually is.

        Irregular on purpose: a uniform pair is refused for ambiguity first,
        and this gate has to be shown failing on its own.
        """
        reference = _irregular_train(400, seed=14)
        target = reference * 4.35

        with pytest.raises(SyncEvidenceError, match="unit or sample-index mismatch"):
            fit_sync_events(reference, target, reference_id="sensor", target_id="camera")

    def test_a_plausible_drift_is_still_allowed(self) -> None:
        """The bound is at the edge of physics, not at the edge of tidiness."""
        reference = np.arange(0.0, 600.0, 1.0)
        target = reference * (1.0 + 90e-6) + 2.0

        proposal = fit_sync_events(reference, target, reference_id="sensor", target_id="camera")

        assert proposal.fit.drift_ppm == pytest.approx(90.0, abs=0.1)
        assert proposal.acceptable

    def test_a_minority_match_is_refused_however_exact(self) -> None:
        """Most of the reference finding no partner is a different hypothesis.

        A non-uniform train on purpose: a uniform one is refused a step earlier
        for ambiguity, and this gate has to be shown failing on its own.
        """
        reference = _irregular_train(500, seed=11)
        # The camera only ran for the first fifth of the session, so four out of
        # five reference pulses have nothing to pair with. A contiguous slice
        # keeps the pulse *rate* the same on both sides -- `_initial_scale`
        # seeds itself from the median interval, and a decimated slice would be
        # testing that heuristic rather than this gate.
        target = reference[:100] + 1.0

        proposal = fit_sync_events(reference, target, reference_id="sensor", target_id="camera")

        assert proposal.fit.match_rate < 0.5
        assert not proposal.acceptable
        assert "found a partner" in proposal.refusal

    def test_a_tie_at_another_lag_scores_zero_margin(self) -> None:
        """A uniform train fits at every period, and no residual says so."""
        from avialsync.core.sync import SyncAmbiguityError

        with pytest.raises(SyncAmbiguityError, match="ambiguous"):
            fit_sync_events(
                np.array([0.0, 1.0, 2.0]),
                np.array([0.0, 1.0, 2.0, 3.0]),
                reference_id="camera",
                target_id="sensor",
            )

    def test_a_good_fit_reports_an_uncertainty_not_only_a_worst_case(self) -> None:
        """`offset_stderr` is the +/- ; `max_residual` is a bound on one pair."""
        reference = np.arange(0.0, 200.0, 1.0)
        rng = np.random.default_rng(20260911)
        target = reference + 1.25 + rng.normal(0.0, 0.002, size=len(reference))
        target = np.sort(target)

        proposal = fit_sync_events(reference, target, reference_id="sensor", target_id="camera")

        assert proposal.acceptable
        assert proposal.refusal == ""
        assert proposal.fit.offset_stderr > 0.0
        # The uncertainty on a mean of n is smaller than the worst single pair,
        # which is the whole reason printing the latter as "+/-" overstates it.
        assert proposal.fit.offset_stderr < proposal.fit.max_residual
        assert proposal.fit.ambiguity_margin == 1.0

    def test_counts_are_reported_per_side(self) -> None:
        """A match *rate* is not recoverable from `rejected_count` alone."""
        reference = _irregular_train(50, seed=12)
        target = reference[:40] + 0.5

        proposal = fit_sync_events(reference, target, reference_id="sensor", target_id="camera")

        assert proposal.fit.reference_count == 50
        assert proposal.fit.target_count == 40
        assert proposal.fit.match_rate == pytest.approx(40 / 50)
        assert proposal.acceptable

    def test_an_irregular_train_is_not_ambiguous(self) -> None:
        """The rig-side fix for ambiguity: make the pulses distinguishable."""
        reference = _irregular_train(60, seed=13)
        target = reference + 2.5

        proposal = fit_sync_events(reference, target, reference_id="sensor", target_id="camera")

        assert proposal.fit.ambiguity_margin == 1.0
        assert proposal.acceptable
