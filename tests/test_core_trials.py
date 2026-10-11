"""Parts of a recording on one timeline, and the gaps between them (D-217)."""

from __future__ import annotations

import numpy as np
import pytest

from avialsync.core.trials import (
    GAP_FACTOR,
    FrameGaps,
    Part,
    Placement,
    TimeWarp,
    common_gaps,
    holes_between,
    into_slot,
    place,
    stream_spans,
)

EPOCH = 1_700_000_000.0


def test_parts_sit_at_their_recorded_starts_and_the_time_between_stays() -> None:
    plan = place([Part("a", 2.0, EPOCH), Part("b", 1.0, EPOCH + 60.0)])
    assert plan.placement is Placement.CLOCK
    assert plan.epoch == EPOCH
    assert plan.starts == pytest.approx([0.0, 60.0])
    assert plan.lengths == pytest.approx([2.0, 1.0])
    assert plan.segments() == [(EPOCH, EPOCH + 2.0, "a"), (EPOCH + 60.0, EPOCH + 61.0, "b")]
    assert plan.warnings == []


def test_back_to_back_is_only_what_a_plugin_asks_for() -> None:
    parts = [Part("a", 2.0, EPOCH), Part("b", 1.0, EPOCH + 60.0)]
    plan = place(parts, Placement.BACK_TO_BACK)
    assert plan.starts == pytest.approx([0.0, 2.0])
    assert plan.segments()[1] == (EPOCH + 2.0, EPOCH + 3.0, "b")


def test_a_part_without_a_recorded_start_is_left_out_and_named() -> None:
    plan = place([Part("a", 2.0, EPOCH), Part("b", 1.0, None), Part("c", 1.0, EPOCH + 5.0)])
    assert plan.kept == [0, 2]
    assert plan.names == ["a", "c"]
    assert "b has no recorded start" in plan.warnings[0]


def test_a_part_starting_inside_the_one_before_is_left_out_not_moved() -> None:
    plan = place([Part("a", 2.0, EPOCH), Part("b", 1.0, EPOCH + 1.5), Part("c", 1.0, EPOCH + 3.0)])
    assert plan.names == ["a", "c"]
    assert plan.starts == pytest.approx([0.0, 3.0])
    assert "b starts 0.500 s before a ends" in plan.warnings[0]


def test_parts_that_touch_are_not_overlapping() -> None:
    plan = place([Part("a", 2.0, EPOCH), Part("b", 1.0, EPOCH + 2.0)])
    assert plan.names == ["a", "b"] and not plan.warnings


def test_the_first_part_without_a_clock_moves_the_epoch_to_the_next() -> None:
    plan = place([Part("a", 2.0, 0.0), Part("b", 1.0, EPOCH)])
    assert plan.epoch == EPOCH and plan.starts == [0.0]


def test_one_part_is_its_own_timeline() -> None:
    plan = place([Part("only", 3.0, None)])
    assert plan.kept == [0] and plan.starts == [0.0] and plan.epoch == 0.0
    assert plan.segments() == []  # no clock to name it on


def test_nothing_to_place_is_an_empty_plan() -> None:
    plan = place([])
    assert plan.kept == [] and plan.segments() == []


def test_a_parts_samples_land_in_its_slot_and_no_further() -> None:
    times = np.array([-0.1, 0.0, 0.5, 1.0, 1.5])
    placed = into_slot(times, times * 10, 100.0, 1.0)
    assert placed is not None
    np.testing.assert_allclose(placed[0], [100.0, 100.5])
    np.testing.assert_allclose(placed[1], [0.0, 5.0])
    assert into_slot(times, times, 0.0, -1.0) is None


def test_frames_across_a_gap_are_not_held_through_it() -> None:
    times = np.concatenate([np.arange(5) * 0.1, 60.0 + np.arange(5) * 0.1])
    gaps = FrameGaps(times)
    assert gaps.has_gaps
    assert not gaps.in_gap(0.2)  # between two frames of one trial
    assert not gaps.in_gap(0.45)  # the last frame of the trial lasts one period
    assert gaps.in_gap(0.55)
    assert gaps.in_gap(30.0)
    assert not gaps.in_gap(60.0)
    assert not gaps.in_gap(-1.0) and not gaps.in_gap(100.0)  # bounds are not gaps


def test_a_steady_table_has_no_gaps() -> None:
    times = np.arange(100) * 0.01
    times[50:] += 0.01 * (GAP_FACTOR - 2)  # a pause short of the gap rule
    gaps = FrameGaps(times)
    assert not gaps.has_gaps and not gaps.in_gap(0.55)
    assert not FrameGaps(np.array([1.0])).in_gap(1.0)


def test_a_stream_has_holes_only_between_parts_where_it_recorded_nothing() -> None:
    parts = [(0.0, 10.0), (60.0, 70.0), (100.0, 110.0)]
    samples = np.array([1.0, 5.0, 61.0, 80.0, 101.0])  # recorded once between parts 2 and 3

    def has_data(a: float, b: float) -> bool:
        return bool(np.any((samples > a) & (samples < b)))

    holes = holes_between((0.0, 110.0), parts, has_data)
    assert holes == [(10.0, 60.0)]
    assert stream_spans((0.0, 110.0), holes) == [(0.0, 10.0), (60.0, 110.0)]
    # A stream that starts later only has holes inside its own bounds.
    assert holes_between((61.0, 110.0), parts, lambda a, b: False) == [(70.0, 100.0)]


def test_only_time_no_stream_recorded_is_collapsible() -> None:
    video = [(0.0, 10.0), (60.0, 70.0)]
    markers = [(0.0, 10.0), (30.0, 40.0), (60.0, 70.0)]  # data the video lacks
    assert common_gaps([video, markers]) == [(10.0, 30.0), (40.0, 60.0)]
    assert common_gaps([[(0.0, 10.0), (10.5, 20.0)]]) == []  # under a second is kept


def test_a_warp_draws_gaps_as_breaks_and_leaves_master_time_alone() -> None:
    warp = TimeWarp([(10.0, 60.0), (70.0, 100.0)])
    assert [warp.to_view(t) for t in (0.0, 10.0, 30.0, 60.0, 65.0, 100.0, 110.0)] == [
        0.0,
        10.0,
        10.0,
        10.0,
        15.0,
        20.0,
        30.0,
    ]
    # A position on a break means the data after it.
    assert warp.to_master(10.0) == 60.0
    assert warp.to_master(9.0) == 9.0
    assert warp.to_master(15.0) == 65.0
    assert warp.to_master(20.0) == 100.0
    assert warp.gap_at(30.0) == (10.0, 60.0)
    assert warp.gap_at(60.0) is None and warp.gap_at(5.0) is None
    assert not TimeWarp() and TimeWarp().to_view(5.0) == 5.0
