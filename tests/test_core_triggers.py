"""Which way the wire ran decides what a pulse train can prove."""

from __future__ import annotations

import numpy as np
import pytest

from avialsync.core.errors import SyncEvidenceError
from avialsync.core.triggers import (
    TriggerKind,
    extract_pulses,
    locate_drops,
    reconcile_with_frames,
)

#: The wave is held low for a quarter of a period before the first pulse. A
#: train that is already high at its first sample has no low-to-high transition
#: there, so the extractor cannot see that pulse and should not pretend to --
#: the same is true of real evidence that began mid-pulse.
_LEAD_FRACTION = 0.25


def _square(period: float, width: float, count: int, *, start: float = 0.0, rate: float = 10_000.0):
    """A sampled square wave: *count* pulses of *width*, every *period*.

    Returns the chunks and the rise times, so a test asserts against where the
    pulses actually are rather than against arithmetic repeated in both places.
    """
    lead = period * _LEAD_FRACTION
    end = start + lead + period * count
    times = np.arange(start, end, 1.0 / rate)
    values = np.zeros_like(times)
    rises = [start + lead + index * period for index in range(count)]
    for rise in rises:
        values[(times >= rise) & (times < rise + width)] = 1.0
    return [(times, values)], np.asarray(rises)


class TestBothEdges:
    """Rising is exposure start, falling is exposure end. One edge loses half."""

    def test_a_strobe_is_timestamped_at_its_exposure_midpoint(self) -> None:
        """A subject moving through a 5 ms exposure is at the midpoint."""
        chunks, rises = _square(period=0.1, width=0.005, count=10)
        train = extract_pulses(chunks, source_id="cam:strobe", kind=TriggerKind.FRAME_STROBE)

        assert train.count == 10
        # Half an exposure past the rise, not at it.
        assert train.times[0] == pytest.approx(rises[0] + 0.0025, abs=2e-4)
        assert train.mean_exposure == pytest.approx(0.005, abs=1e-4)

    def test_a_trigger_keeps_its_rising_edge(self) -> None:
        """A request has no midpoint: it is an instant, not an interval."""
        chunks, rises = _square(period=0.1, width=0.005, count=10)
        train = extract_pulses(chunks, source_id="daq:trigger", kind=TriggerKind.FRAME_TRIGGER)

        assert train.times[0] == pytest.approx(rises[0], abs=2e-4)

    def test_exposure_duration_comes_free_with_the_second_edge(self) -> None:
        train = extract_pulses(
            _square(period=0.05, width=0.012, count=8)[0],
            source_id="cam:strobe",
            kind=TriggerKind.FRAME_STROBE,
        )

        assert train.durations is not None
        assert train.mean_exposure == pytest.approx(0.012, abs=1e-3)

    def test_a_pulse_still_high_at_the_end_keeps_its_start(self) -> None:
        """Losing the last frame to a missing edge is worse than an unknown length."""
        times = np.arange(0.0, 0.05, 1e-4)
        values = np.zeros_like(times)
        values[times >= 0.04] = 1.0  # rises and never falls

        train = extract_pulses(
            [(times, values)], source_id="cam:strobe", kind=TriggerKind.FRAME_STROBE
        )

        assert train.count == 1
        assert train.times[0] == pytest.approx(0.04, abs=1e-3)


class TestWhatTheTopologyLicenses:
    """The distinction the whole module exists for."""

    def test_only_a_strobe_confirms_a_frame_happened(self) -> None:
        assert TriggerKind.FRAME_STROBE.confirms_frames
        assert not TriggerKind.FRAME_TRIGGER.confirms_frames

    def test_both_identify_frames_even_so(self) -> None:
        assert TriggerKind.FRAME_TRIGGER.identifies_frames
        assert not TriggerKind.SYNC_TRAIN.identifies_frames

    def test_agreeing_counts_on_a_strobe_license_an_exact_mapping(self) -> None:
        train = extract_pulses(
            _square(period=0.05, width=0.01, count=20)[0],
            source_id="cam:strobe",
            kind=TriggerKind.FRAME_STROBE,
        )

        result = reconcile_with_frames(train, 20)

        assert result.agrees
        assert result.exact_mapping_is_safe
        assert "its own exposure was measured at" in result.explain()

    def test_agreeing_counts_on_a_trigger_do_not(self) -> None:
        """A drop and a duplicate agree too. Agreement is absence of evidence."""
        train = extract_pulses(
            _square(period=0.05, width=0.01, count=20)[0],
            source_id="daq:trigger",
            kind=TriggerKind.FRAME_TRIGGER,
        )

        result = reconcile_with_frames(train, 20)

        assert result.agrees
        assert not result.exact_mapping_is_safe
        assert "not the same as evidence" in result.explain()

    def test_missing_frames_are_named_as_a_shift_hazard(self) -> None:
        train = extract_pulses(
            _square(period=0.05, width=0.01, count=20)[0],
            source_id="daq:trigger",
            kind=TriggerKind.FRAME_TRIGGER,
        )

        result = reconcile_with_frames(train, 17)

        assert not result.agrees
        assert "3 exposures did not reach the file" in result.explain()
        assert "shift every frame" in result.explain()


class TestFindingWhereATrainSkipped:
    def test_a_missing_pulse_is_an_interval_outlier(self) -> None:
        times = np.arange(0.0, 2.0, 0.1)
        times = np.delete(times, 7)

        assert locate_drops(times) == (6,)

    def test_two_missing_in_a_row_are_still_one_gap(self) -> None:
        times = np.arange(0.0, 2.0, 0.1)
        times = np.delete(times, [7, 8])

        assert locate_drops(times) == (6,)

    def test_a_regular_train_has_none(self) -> None:
        assert locate_drops(np.arange(0.0, 2.0, 0.1)) == ()

    def test_an_irregular_train_reports_nothing_rather_than_guessing(self) -> None:
        """Every interval is its own length; nothing can be inferred."""
        rng = np.random.default_rng(5)
        times = np.cumsum(rng.uniform(0.5, 1.5, 40))

        assert locate_drops(times) == ()

    def test_too_few_pulses_to_have_a_modal_interval(self) -> None:
        assert locate_drops(np.array([0.0, 1.0])) == ()

    def test_a_strobe_carries_its_drops_with_it(self) -> None:
        chunks, rises = _square(period=0.1, width=0.01, count=12)
        times, values = chunks[0]
        # Suppress the eighth exposure entirely.
        dropped = rises[7]
        values[(times >= dropped) & (times < dropped + 0.01)] = 0.0

        train = extract_pulses(
            [(times, values)], source_id="cam:strobe", kind=TriggerKind.FRAME_STROBE
        )

        assert train.count == 11
        assert train.drops == (6,)


class TestRefusals:
    def test_evidence_without_a_source_is_refused(self) -> None:
        with pytest.raises(SyncEvidenceError, match="source identifier"):
            extract_pulses([], source_id="", kind=TriggerKind.SYNC_TRAIN)

    def test_out_of_order_timestamps_are_refused(self) -> None:
        with pytest.raises(SyncEvidenceError, match="strictly increasing"):
            extract_pulses(
                [(np.array([0.0, 0.2, 0.1]), np.array([0.0, 1.0, 0.0]))],
                source_id="ttl",
                kind=TriggerKind.SYNC_TRAIN,
            )

    def test_a_negative_frame_count_is_refused(self) -> None:
        train = extract_pulses(
            _square(period=0.1, width=0.01, count=4)[0],
            source_id="cam",
            kind=TriggerKind.FRAME_STROBE,
        )
        with pytest.raises(SyncEvidenceError, match="cannot be negative"):
            reconcile_with_frames(train, -1)
