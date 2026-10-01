"""Synthetic ground truth for apparatus geometry and material motion (D-149)."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from avialsync.core.errors import PropModelError
from avialsync.core.physical_props import (
    BallSurface,
    BeltTrack,
    Ladder,
    LadderPoint,
    LadderStep,
    StepClick,
    UnitQuaternion,
    WheelMaterialMap,
)
from tests.wheel_fixture import CAMERAS, TRUTH


def _clicked_point(world: tuple[float, float, float], cameras: tuple[str, ...]) -> LadderPoint:
    point = LadderPoint()
    for index, name in enumerate(cameras):
        x, y = CAMERAS[name].project(np.asarray(world))[0]
        point = point.with_click(StepClick(name, 12 + index, float(x), float(y)))
    return point


def test_irregular_ladder_keeps_each_clicked_step_without_generating_neighbours() -> None:
    """Unequal spacing and height are real geometry, not fit residuals."""
    truth = ((-70.0, 0.0, 65.0), (-18.0, 5.0, 74.0), (93.0, -12.0, 58.0))
    steps = tuple(
        LadderStep(str(index), f"Step {index}", (_clicked_point(world, ("Front", "Left")),))
        for index, world in enumerate(truth)
    )
    ladder = Ladder("horizontal ladder", steps)
    solved = tuple(step.resolved(CAMERAS) for step in ladder.steps)
    assert len(solved) == 3
    for step, expected in zip(solved, truth, strict=True):
        point = step.points[0]
        assert point.xyz == pytest.approx(expected, abs=1e-7)
        assert point.error_px == pytest.approx(0.0, abs=1e-7)
        assert point.issue is None
        assert len(point.clicks) == 2
    assert solved[1].points[0].xyz is not None
    assert solved[1].points[0].xyz[2] != (truth[0][2] + truth[2][2]) / 2


def test_ladder_keeps_single_view_click_and_never_invents_depth() -> None:
    point = _clicked_point((25.0, -7.0, 70.0), ("Front",))
    result = point.resolved(CAMERAS)
    assert result.xyz is None and result.error_px is None
    assert result.issue == "need_two_calibrated_views"
    assert result.clicks == point.clicks


def test_ladder_ignores_missing_calibration_without_discarding_clicks() -> None:
    point = _clicked_point((25.0, -7.0, 70.0), ("Front", "Left"))
    result = point.resolved({"Front": CAMERAS["Front"]})
    assert result.xyz is None
    assert result.clicks == point.clicks


def test_near_parallel_ladder_views_do_not_claim_a_3d_point() -> None:
    same_camera = dataclasses.replace(CAMERAS["Front"], name="Clone")
    point = _clicked_point((25.0, -7.0, 70.0), ("Front",))
    first = point.clicks[0]
    point = point.with_click(StepClick("Clone", first.frame, first.x, first.y))
    result = point.resolved({"Front": CAMERAS["Front"], "Clone": same_camera})
    assert result.xyz is None and result.issue == "rays_parallel"
    assert len(result.clicks) == 2


def test_reclicking_a_ladder_point_invalidates_only_its_derived_position() -> None:
    first = _clicked_point((20.0, 0.0, 75.0), ("Front", "Left")).resolved(CAMERAS)
    second = _clicked_point((60.0, 0.0, 85.0), ("Front", "Left")).resolved(CAMERAS)
    ladder = Ladder(
        "steps",
        (
            LadderStep("a", "First", (first,)),
            LadderStep("b", "Second", (second,)),
        ),
    )
    moved = first.with_click(StepClick("Front", 44, 123.0, 456.0))
    changed = ladder.with_step(LadderStep("a", "First", (moved,)))
    assert changed.steps[0].points[0].xyz is None
    assert changed.steps[1] == ladder.steps[1]
    assert changed.without_step("a").steps == (ladder.steps[1],)
    assert ladder.reordered(("b", "a")).steps == (ladder.steps[1], ladder.steps[0])


def test_a_ladder_rung_or_outline_contains_only_its_clicked_points() -> None:
    a = _clicked_point((-25.0, 0.0, 80.0), ("Front",))
    b = _clicked_point((25.0, 0.0, 81.0), ("Front",))
    rung = LadderStep("r", "Uneven rung", (a, b))
    assert len(rung.points) == 2
    assert not rung.closed
    with pytest.raises(PropModelError):
        LadderStep("r", "Not an outline", (a, b), closed=True)


def test_open_belt_moves_a_mark_but_not_its_support_path() -> None:
    track = BeltTrack(((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)))
    fixed = track.vertices
    assert track.material_point(2.0, 3.0) == pytest.approx((5.0, 0.0, 0.0))
    assert track.material_point(7.0, -3.0) == pytest.approx((4.0, 0.0, 0.0))
    assert track.material_point(8.0, 3.0) is None
    assert track.vertices == fixed


def test_closed_belt_wraps_only_on_the_declared_loop() -> None:
    track = BeltTrack(
        ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)),
        closed=True,
    )
    assert track.length == pytest.approx(40.0)
    assert track.material_point(39.0, 3.0) == pytest.approx((2.0, 0.0, 0.0))
    assert track.material_point(1.0, -3.0) == pytest.approx((0.0, 2.0, 0.0))


def test_ball_orientation_has_two_independent_axes() -> None:
    ball = BallSurface((10.0, 20.0, 30.0), 5.0)
    around_z = UnitQuaternion.about_axis((0.0, 0.0, 1.0), math.pi / 2)
    around_x = UnitQuaternion.about_axis((1.0, 0.0, 0.0), math.pi / 2)
    local = (1.0, 0.0, 0.0)
    assert ball.material_point(local, around_z) == pytest.approx((10.0, 25.0, 30.0))
    assert ball.material_point(local, around_x.composed(around_z)) == pytest.approx(
        (10.0, 20.0, 35.0)
    )
    assert ball.material_point(local, around_z.composed(around_x)) == pytest.approx(
        (10.0, 25.0, 30.0)
    )


def test_quaternion_normalization_and_sign_do_not_change_ball_position() -> None:
    ball = BallSurface((0.0, 0.0, 0.0), 2.0)
    q = UnitQuaternion(2.0, 0.0, 0.0, 2.0)
    opposite = UnitQuaternion(-2.0, 0.0, 0.0, -2.0)
    assert math.hypot(q.w, q.x, q.y, q.z) == pytest.approx(1.0)
    assert ball.material_point((0.0, 1.0, 0.0), q) == pytest.approx(
        ball.material_point((0.0, 1.0, 0.0), opposite)
    )


def test_wheel_adapter_preserves_the_existing_bar_generator() -> None:
    adapter = WheelMaterialMap(TRUTH)
    assert np.allclose(adapter.bar_ends(37.0), TRUTH.bar_ends(37.0))
    assert np.allclose(adapter.bar_ends(37.0), adapter.bar_ends(397.0))


@pytest.mark.parametrize(
    "make_invalid",
    [
        lambda: StepClick("", 0, 1.0, 2.0),
        lambda: StepClick("Front", -1, 1.0, 2.0),
        lambda: BeltTrack(((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))),
        lambda: UnitQuaternion(0.0, 0.0, 0.0, 0.0),
        lambda: BallSurface((0.0, 0.0, 0.0), -1.0),
        lambda: LadderPoint(xyz=(1.0, 2.0, 3.0), error_px=0.0),
        lambda: WheelMaterialMap(TRUTH).bar_ends(float("nan")),
    ],
)
def test_invalid_prop_geometry_or_motion_is_rejected(make_invalid) -> None:
    with pytest.raises(PropModelError):
        make_invalid()
