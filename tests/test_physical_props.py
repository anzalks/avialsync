"""Synthetic ground truth for apparatus geometry and material motion (D-149)."""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from avialsync.core.errors import PropModelError
from avialsync.core.physical_props import (
    BallBinding,
    BallProp,
    BallSurface,
    BallVisualFrame,
    BeltBinding,
    BeltProp,
    BeltTrack,
    BeltVisualFrame,
    Ladder,
    LadderPoint,
    LadderStep,
    MotionCheck,
    PropStore,
    StepClick,
    UnitQuaternion,
    WheelMaterialMap,
)
from avialsync.core.visual_prop_tracking import (
    ball_visual_state,
    belt_visual_state,
    belt_visual_travel,
)
from tests.wheel_fixture import CAMERAS, TRUTH


def _clicked_point(world: tuple[float, float, float], cameras: tuple[str, ...]) -> LadderPoint:
    point = LadderPoint()
    for index, name in enumerate(cameras):
        x, y = CAMERAS[name].project(np.asarray(world))[0]
        point = point.with_click(StepClick(name, 12 + index, float(x), float(y)))
    return point


def test_visual_belt_marks_follow_only_stereo_observed_frames() -> None:
    with pytest.raises(PropModelError, match="travel direction"):
        BeltProp(
            "underdetermined",
            BeltTrack(((0.0, 0.0, 70.0), (10.0, 0.0, 70.0))),
            visual_reference_frame=12,
            visual_frames=(BeltVisualFrame(12),),
        )
    belt = BeltProp(
        "belt",
        BeltTrack(((0.0, 0.0, 70.0), (10.0, 0.0, 70.0))),
        travel_direction=(1.0, 0.0, 0.0),
        visual_reference_frame=12,
        visual_frames=(
            BeltVisualFrame(12, _clicked_point((2.0, 0.0, 70.0), ("Front", "Left"))),
            BeltVisualFrame(13, _clicked_point((5.0, 0.0, 70.0), ("Front",))),
            BeltVisualFrame(14, _clicked_point((7.0, 0.0, 70.0), ("Front", "Left"))),
        ),
    )
    first = belt_visual_state(belt, 12, CAMERAS)
    last = belt_visual_state(belt, 14, CAMERAS)
    assert first is not None and last is not None
    assert first.path_distance == pytest.approx(2.0, abs=1e-7)
    assert last.path_distance - first.path_distance == pytest.approx(5.0, abs=1e-7)
    assert belt_visual_travel(belt, 14, CAMERAS) == pytest.approx(5.0, abs=1e-7)
    reverse = dataclasses.replace(belt, travel_direction=(-1.0, 0.0, 0.0))
    assert belt_visual_travel(reverse, 14, CAMERAS) == pytest.approx(-5.0, abs=1e-7)
    assert last.point == pytest.approx((7.0, 0.0, 70.0), abs=1e-7)
    assert belt_visual_state(belt, 13, CAMERAS) is None
    assert belt_visual_state(belt, 15, CAMERAS) is None
    assert belt_visual_state(belt, 14, {"Front": CAMERAS["Front"]}) is None


def test_closed_visual_belt_needs_explicit_laps_for_signed_travel(tmp_path: Path) -> None:
    belt = BeltProp(
        "loop",
        BeltTrack(
            ((0.0, 0.0, 70.0), (10.0, 0.0, 70.0), (10.0, 10.0, 70.0), (0.0, 10.0, 70.0)),
            closed=True,
        ),
        travel_direction=(1.0, 0.0, 0.0),
        visual_reference_frame=12,
        visual_frames=(
            BeltVisualFrame(12, _clicked_point((2.0, 0.0, 70.0), ("Front", "Left"))),
            BeltVisualFrame(14, _clicked_point((7.0, 0.0, 70.0), ("Front", "Left"))),
        ),
    )
    assert belt_visual_state(belt, 14, CAMERAS) is not None
    assert belt_visual_travel(belt, 14, CAMERAS) is None
    frames = (
        dataclasses.replace(belt.visual_frames[0], lap=0),
        dataclasses.replace(belt.visual_frames[1], lap=2),
    )
    measured = belt_visual_travel(dataclasses.replace(belt, visual_frames=frames), 14, CAMERAS)
    assert measured == pytest.approx(85.0)
    from avialsync.core.prop_file import read_props, write_prop

    write_prop(tmp_path, dataclasses.replace(belt, visual_frames=frames))
    restored = read_props(tmp_path)[0][0]
    assert isinstance(restored, BeltProp)
    assert belt_visual_travel(restored, 14, CAMERAS) == pytest.approx(85.0)


def test_visual_ball_solves_three_named_marks_and_rejects_missing_evidence() -> None:
    centre = np.asarray((0.0, 0.0, 70.0))
    marks = np.eye(3) * 5.0
    rotation = UnitQuaternion.about_axis((0.0, 0.0, 1.0), math.pi / 2)
    reference = BallVisualFrame(
        12,
        tuple(_clicked_point(tuple(centre + mark), ("Front", "Left")) for mark in marks),
    )
    later = BallVisualFrame(
        14,
        tuple(
            _clicked_point(tuple(centre + rotation.rotate(tuple(mark))), ("Front", "Left"))
            for mark in marks
        ),
    )
    ball = BallProp(
        "ball",
        BallSurface(tuple(centre), 5.0),
        visual_reference_frame=12,
        visual_frames=(reference, later),
    )
    state = ball_visual_state(ball, 14, CAMERAS)
    assert state is not None
    assert state.marks[0] == pytest.approx((0.0, 5.0, 70.0), abs=1e-6)
    assert state.residual == pytest.approx(0.0, abs=1e-6)
    assert ball_visual_state(ball, 13, CAMERAS) is None
    incomplete = dataclasses.replace(later, marks=(later.marks[0], later.marks[1], LadderPoint()))
    missing = dataclasses.replace(ball, visual_frames=(reference, incomplete))
    assert ball_visual_state(missing, 14, CAMERAS) is None
    duplicated = dataclasses.replace(later, marks=(later.marks[0], later.marks[0], later.marks[2]))
    repeated = dataclasses.replace(ball, visual_frames=(reference, duplicated))
    assert ball_visual_state(repeated, 14, CAMERAS) is None


def test_visual_tracks_round_trip_raw_clicks_without_storing_old_fits(tmp_path: Path) -> None:
    from avialsync.core.prop_file import read_props, write_prop

    belt = BeltProp(
        "belt",
        BeltTrack(((0.0, 0.0, 70.0), (10.0, 0.0, 70.0))),
        travel_direction=(1.0, 0.0, 0.0),
        visual_reference_frame=12,
        visual_frames=(
            BeltVisualFrame(
                12, _clicked_point((2.0, 0.0, 70.0), ("Front", "Left")).resolved(CAMERAS)
            ),
        ),
    )
    ball = BallProp(
        "ball",
        BallSurface((0.0, 0.0, 70.0), 5.0),
        visual_reference_frame=12,
        visual_frames=(
            BallVisualFrame(
                12,
                tuple(
                    _clicked_point(world, ("Front", "Left"))
                    for world in ((5.0, 0.0, 70.0), (0.0, 5.0, 70.0), (0.0, 0.0, 75.0))
                ),
            ),
        ),
    )
    write_prop(tmp_path, belt)
    write_prop(tmp_path, ball)
    props, issues = read_props(tmp_path)
    assert not issues
    by_name = {prop.name: prop for prop in props}
    restored_belt = by_name["belt"]
    assert isinstance(restored_belt, BeltProp)
    assert restored_belt.visual_frames[0].point.clicks == belt.visual_frames[0].point.clicks
    assert restored_belt.visual_frames[0].point.xyz is None
    assert belt_visual_state(restored_belt, 12, CAMERAS) is not None
    restored_ball = by_name["ball"]
    assert isinstance(restored_ball, BallProp)
    assert tuple(mark.clicks for mark in restored_ball.visual_frames[0].marks) == tuple(
        mark.clicks for mark in ball.visual_frames[0].marks
    )
    assert ball_visual_state(restored_ball, 12, CAMERAS) is not None


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


def test_two_rays_from_one_optical_centre_cannot_establish_depth() -> None:
    """Different pixels do not create a stereo baseline between cloned cameras."""
    clone = dataclasses.replace(CAMERAS["Front"], name="Clone")
    original = _clicked_point((20.0, 0.0, 75.0), ("Front",))
    first = original.clicks[0]
    contradictory = original.with_click(StepClick("Clone", first.frame, first.x + 100.0, first.y))
    result = contradictory.resolved({"Front": CAMERAS["Front"], "Clone": clone})
    assert result.xyz is None
    assert result.clicks == contradictory.clicks


def test_triangulation_behind_a_camera_is_not_accepted_as_visible_geometry() -> None:
    """Finite algebraic coordinates behind a lens are not a photographed rung."""
    point = _clicked_point((0.0, 0.0, 1000.0), ("Front", "Left"))
    result = point.resolved(CAMERAS)
    assert result.xyz is None
    assert result.issue == "invalid_solution"


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


def test_named_belt_and_ball_declarations_validate_their_kind_specific_geometry() -> None:
    belt = BeltProp(
        "treadmill", BeltTrack(((0.0, 0.0, 0.0), (4.0, 0.0, 0.0))), "mm", (0.0, 3.0, 0.0)
    )
    ball = BallProp("sphere", BallSurface((1.0, 2.0, 3.0), 5.0), "cm", ((1.0, 0.0, 0.0),))
    assert belt.travel_direction == pytest.approx((0.0, 1.0, 0.0))
    assert ball.surface_marks == ((1.0, 0.0, 0.0),)
    with pytest.raises(PropModelError, match="nonzero"):
        BeltProp("treadmill", belt.track, travel_direction=(0.0, 0.0, 0.0))
    with pytest.raises(PropModelError, match="unit directions"):
        BallProp("sphere", ball.surface, surface_marks=((2.0, 0.0, 0.0),))


def test_belt_binding_uses_signed_displacement_and_requires_direction() -> None:
    track = BeltTrack(((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)))
    binding = BeltBinding("sensor", "distance", 4, 100.0, 5.0, 0.5)
    with pytest.raises(PropModelError, match="direction"):
        BeltProp("belt", track, binding=binding)
    belt = BeltProp("belt", track, travel_direction=(1.0, 0.0, 0.0), binding=binding)
    assert belt.material_point(104.0) == pytest.approx((7.0, 0.0, 0.0))
    assert belt.material_point(104.0, reference_reading=102.0) == pytest.approx((6.0, 0.0, 0.0))
    reverse = dataclasses.replace(belt, travel_direction=(-1.0, 0.0, 0.0))
    assert reverse.material_point(104.0) == pytest.approx((3.0, 0.0, 0.0))
    assert belt.material_point(112.0) is None
    assert track.vertices == ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))


def test_ball_binding_requires_four_channels_and_real_surface_mark() -> None:
    binding = BallBinding("imu", ("qw", "qx", "qy", "qz"), 2, UnitQuaternion.identity())
    with pytest.raises(PropModelError, match="surface mark"):
        BallProp("ball", BallSurface((0.0, 0.0, 0.0), 2.0), binding=binding)
    ball = BallProp(
        "ball", BallSurface((0.0, 0.0, 0.0), 2.0), surface_marks=((1.0, 0.0, 0.0),), binding=binding
    )
    assert ball.material_point(
        UnitQuaternion.about_axis((0.0, 0.0, 1.0), math.pi / 2)
    ) == pytest.approx((0.0, 2.0, 0.0))
    with pytest.raises(PropModelError, match="four distinct"):
        BallBinding("imu", ("angle", "angle", "angle", "angle"), 2, UnitQuaternion.identity())
    with pytest.raises(PropModelError, match="residual"):
        MotionCheck(8, "Front", 1.0, 2.0, float("nan"))


def test_ball_reference_orientation_keeps_the_identified_mark_at_reference() -> None:
    reference = UnitQuaternion.about_axis((0.0, 1.0, 0.0), math.pi / 3)
    later = UnitQuaternion.about_axis((0.0, 0.0, 1.0), math.pi / 2).composed(reference)
    ball = BallProp(
        "ball",
        BallSurface((0.0, 0.0, 0.0), 2.0),
        surface_marks=((1.0, 0.0, 0.0),),
        binding=BallBinding("imu", ("w", "x", "y", "z"), 7, reference),
    )
    assert ball.material_point(reference) == pytest.approx((2.0, 0.0, 0.0))
    assert ball.material_point(later) == pytest.approx((0.0, 2.0, 0.0))
    assert ball.material_point(later, reference_orientation=later) == pytest.approx((2.0, 0.0, 0.0))


def test_prop_store_accepts_multiple_static_prop_kinds_without_losing_ladder_edits() -> None:
    store = PropStore()
    ladder = Ladder("steps")
    belt = BeltProp("belt", BeltTrack(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))))
    ball = BallProp("ball", BallSurface((0.0, 0.0, 0.0), 1.0))
    assert store.set(ladder.name, ladder)
    assert store.set(belt.name, belt)
    assert store.set(ball.name, ball)
    assert list(store) == [ladder, belt, ball]
    with pytest.raises(PropModelError, match="existing ladder"):
        store.set_step("ball", "step", None)


def test_closed_belt_wraps_only_on_the_declared_loop() -> None:
    track = BeltTrack(
        ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)),
        closed=True,
    )
    assert track.length == pytest.approx(40.0)
    assert track.material_point(39.0, 3.0) == pytest.approx((2.0, 0.0, 0.0))
    assert track.material_point(1.0, -3.0) == pytest.approx((0.0, 2.0, 0.0))


@settings(max_examples=50)
@given(
    reference=st.floats(min_value=-100, max_value=100, allow_nan=False),
    travel=st.floats(min_value=-100, max_value=100, allow_nan=False),
    turns=st.integers(min_value=-10, max_value=10),
)
def test_closed_belt_position_is_periodic_without_moving_its_frame(
    reference: float, travel: float, turns: int
) -> None:
    track = BeltTrack(
        ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)),
        closed=True,
    )
    vertices = track.vertices
    assert track.material_point(reference, travel + turns * track.length) == pytest.approx(
        track.material_point(reference, travel), abs=1e-8
    )
    assert track.vertices == vertices


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


@settings(max_examples=50)
@given(
    pitch=st.floats(min_value=-math.pi, max_value=math.pi, allow_nan=False),
    yaw=st.floats(min_value=-math.pi, max_value=math.pi, allow_nan=False),
)
def test_ball_orientation_keeps_a_mark_on_the_declared_sphere(pitch: float, yaw: float) -> None:
    ball = BallSurface((3.0, -4.0, 7.0), 12.0)
    q = UnitQuaternion.about_axis((1.0, 0.0, 0.0), pitch).composed(
        UnitQuaternion.about_axis((0.0, 0.0, 1.0), yaw)
    )
    mark = ball.material_point((1.0, 0.0, 0.0), q)
    assert math.dist(mark, ball.centre) == pytest.approx(ball.radius, abs=1e-10)


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
