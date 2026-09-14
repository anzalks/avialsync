"""One declared zero, so a wall clock and a container can share a timeline."""

from __future__ import annotations

import pytest

from avialsync.core.session_time import (
    ABSOLUTE_EPOCH_FLOOR,
    is_absolute,
    placement_offset,
    rebase_offset,
    reference_epoch,
    source_epoch_for,
    unix_start,
)


class TestTellingTheTwoTimeBasesApart:
    """Four decades separate epoch timestamps from elapsed ones."""

    def test_an_epoch_timestamp_is_absolute(self) -> None:
        assert is_absolute(1_768_000_000.0)

    def test_a_container_relative_timestamp_is_not(self) -> None:
        assert not is_absolute(0.0)
        assert not is_absolute(3600.0)

    def test_seconds_since_midnight_is_not_treated_as_absolute(self) -> None:
        """34540 is 09:35:40, and also a plausible elapsed time.

        The threshold only separates populations that are decades apart. A
        time-of-day base has to be promoted to a real epoch by the import
        wizard's anchor date; guessing here would be guessing.
        """
        assert not is_absolute(34_540.0)

    def test_the_floor_is_where_it_claims_to_be(self) -> None:
        assert is_absolute(ABSOLUTE_EPOCH_FLOOR)
        assert not is_absolute(ABSOLUTE_EPOCH_FLOOR - 1.0)


class TestDeclaringTheZeroOnce:
    """A reference that moves renumbers everything already written down."""

    def test_the_first_absolute_source_sets_it(self) -> None:
        assert reference_epoch(0.0, 1_768_000_000.0) == pytest.approx(1_768_000_000.0)

    def test_an_established_reference_is_never_moved(self) -> None:
        """Even by a source that starts earlier -- it goes before zero instead."""
        assert reference_epoch(1_768_000_000.0, 1_767_000_000.0) == pytest.approx(1_768_000_000.0)

    def test_container_relative_sources_leave_it_unset(self) -> None:
        """Their zero is a recording start nobody wrote down."""
        assert reference_epoch(0.0, 0.0) == 0.0


class TestPlacingASourceAgainstIt:
    """Nothing is rewritten: the mapping moves, as it does for every alignment."""

    def test_an_absolute_source_is_offset_by_the_reference(self) -> None:
        offset = rebase_offset(1_768_000_000.0, 1_768_000_000.0)
        assert offset == pytest.approx(1_768_000_000.0)

    def test_a_source_starting_later_still_takes_the_same_offset(self) -> None:
        """It lands 300 s along the master clock, which is where it truly is."""
        reference = 1_768_000_000.0
        offset = rebase_offset(reference + 300.0, reference)
        assert offset == pytest.approx(reference)

    def test_a_container_relative_source_is_left_alone(self) -> None:
        assert rebase_offset(0.0, 1_768_000_000.0) == 0.0

    def test_without_a_reference_nothing_moves(self) -> None:
        assert rebase_offset(1_768_000_000.0, 0.0) == 0.0

    def test_an_epoch_csv_and_a_video_end_up_on_one_timeline(self) -> None:
        """The fifty-four-year timeline, in the form it actually took."""
        reference = reference_epoch(0.0, 1_768_000_000.0)
        sensor_offset = rebase_offset(1_768_000_000.0, reference)
        video_offset = rebase_offset(0.0, reference)

        # Master time of each source's first sample: t_source = t_master + offset
        sensor_master_start = 1_768_000_000.0 - sensor_offset
        video_master_start = 0.0 - video_offset

        assert sensor_master_start == pytest.approx(0.0)
        assert video_master_start == pytest.approx(0.0)
        # Which is the whole point: a span of minutes, not of decades.
        assert abs(sensor_master_start - video_master_start) < 1.0


class TestEveryTimeBaseThroughOneFormula:
    """A source declares what its zero is; placement is arithmetic after that.

    The four bases this application meets, and the one expression that places
    all of them: ``offset = session_zero - source_epoch``.
    """

    #: 2026-05-08 00:00 UTC, the anchor date of the reference AOL session.
    MIDNIGHT = 1_778_198_400.0
    #: 09:35:26.312 on that date, when its cameras started.
    CAMERA_START = MIDNIGHT + 34_526.312

    def test_a_container_relative_source_declares_nothing(self) -> None:
        assert source_epoch_for(0.0) is None
        assert placement_offset(source_epoch_for(0.0), self.CAMERA_START) == 0.0

    def test_unix_timestamps_are_recognised_without_a_declaration(self) -> None:
        """The magnitude guess, which is all a loader that says nothing gets."""
        assert source_epoch_for(1_768_000_000.0) == 0.0

    def test_a_declaration_beats_the_guess(self) -> None:
        """34526 is a time of day *and* a plausible elapsed time; only the file knows."""
        assert source_epoch_for(34_526.312) is None, "no threshold can tell these apart"
        assert source_epoch_for(34_526.312, declared=self.MIDNIGHT) == self.MIDNIGHT

    def test_a_camera_counting_from_its_first_frame_lands_at_zero(self) -> None:
        epoch = source_epoch_for(0.0, declared=self.CAMERA_START)
        offset = placement_offset(epoch, self.CAMERA_START)

        assert offset == pytest.approx(0.0)

    def test_a_log_counting_from_midnight_lands_beside_it(self) -> None:
        """The encoder starts 0.23 s before the cameras, and must say so."""
        epoch = source_epoch_for(34_526.082, declared=self.MIDNIGHT)
        offset = placement_offset(epoch, self.CAMERA_START)

        # t_master = t_source - offset
        assert 34_526.082 - offset == pytest.approx(-0.23, abs=1e-3)

    def test_an_epoch_csv_still_lands_at_zero(self) -> None:
        """The case that worked before must go on working through the new path."""
        reference = 1_768_000_000.0
        epoch = source_epoch_for(reference)
        offset = placement_offset(epoch, reference)

        assert reference - offset == pytest.approx(0.0)

    def test_a_session_with_no_declared_zero_places_nothing(self) -> None:
        assert placement_offset(self.MIDNIGHT, 0.0) == 0.0

    def test_unix_start_answers_only_when_the_source_knows(self) -> None:
        assert unix_start(34_526.082, self.MIDNIGHT) == pytest.approx(self.CAMERA_START - 0.23)
        assert unix_start(12.0, None) is None
