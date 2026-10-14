"""Observed geometry rejects ambiguous crossings, missing views and nonrigid motion."""

import math
from dataclasses import replace

import numpy as np
import pytest

from avialsync.core import physical_props, prop_motion_calibration
from avialsync.core import visual_prop_tracking as visual
from avialsync.core.belt_rollers import BeltRollers, BeltSideView
from avialsync.core.errors import PropModelError, PropMotionCalibrationError
from avialsync.core.physical_props import (
    BallProp,
    BallSurface,
    BallVisualFrame,
    BeltBinding,
    BeltProp,
    BeltTrack,
    BeltVisualFrame,
    LadderPoint,
    MotionCheck,
    StepClick,
    UnitQuaternion,
)
from tests.test_physical_props import _clicked_point
from tests.wheel_fixture import CAMERAS


def _roller_belt() -> BeltProp:
    rollers = BeltRollers((0.0, 0.0, 70.0), (10.0, 0.0, 70.0), 1, 2, (0.0, 1.0, 0.0))
    track = BeltTrack(tuple(rollers.point_at(s) for s in rollers.sample_distances()), True)
    return BeltProp(
        "belt",
        track,
        travel_direction=(1.0, 0.0, 0.0),
        surface_width=2,
        surface_normal=rollers.top_normal,
        rollers=rollers,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"track": BeltTrack(((0.0, 0.0, 70.0), (10.0, 0.0, 70.0)))},
        {"surface_width": 3},
        {"surface_normal": (0.0, 0.0, 1.0)},
    ],
)
def test_roller_surface_and_display_path_cannot_disagree(changes) -> None:
    with pytest.raises(PropModelError):
        replace(_roller_belt(), **changes)


def test_roller_observations_locate_only_marks_on_the_declared_surface() -> None:
    belt = _roller_belt()
    for world, valid in [((3.0, 1.0, 70.0), True), ((3.0, 20.0, 70.0), False)]:
        frame = BeltVisualFrame(0, _clicked_point(world, ("Front", "Left")))
        observed = replace(belt, visual_reference_frame=0, visual_frames=(frame,))
        assert (visual.belt_visual_state(observed, 0, CAMERAS) is not None) is valid
        assert visual.belt_visual_problem(observed, 0, CAMERAS) == (
            None if valid else visual.OFF_PATH
        )
    assert visual.belt_visual_travel(belt, 0, CAMERAS) is None
    incomplete = replace(belt, visual_reference_frame=0, visual_frames=(BeltVisualFrame(0),))
    assert visual.belt_visual_travel(incomplete, 0, CAMERAS) is None


def test_crossing_belt_path_cannot_choose_between_two_material_locations() -> None:
    track = BeltTrack(((-2.0, -2.0, 70.0), (2.0, 2.0, 70.0), (-2.0, 2.0, 70.0), (2.0, -2.0, 70.0)))
    frame = BeltVisualFrame(0, _clicked_point((0.0, 0.0, 70.0), ("Front", "Left")))
    belt = BeltProp(
        "belt",
        track,
        travel_direction=(1.0, 1.0, 0.0),
        visual_reference_frame=0,
        visual_frames=(frame,),
    )
    assert visual.belt_visual_problem(belt, 0, CAMERAS) == visual.AMBIGUOUS_CROSSING


def _side_belt() -> BeltProp:
    rollers = BeltRollers((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), 1, 2, (0.0, 1.0, 0.0))

    def pixel(x, y):
        return x / (1 + x), y / (1 + x)

    view = BeltSideView(
        "side", 0, tuple(pixel(x, y) for x, y in ((0, 0), (10, 0), (0, 1), (10, 1)))
    )
    track = BeltTrack(tuple(rollers.point_at(s) for s in rollers.sample_distances()), True)
    return BeltProp(
        "belt",
        track,
        travel_direction=(1.0, 0.0, 0.0),
        surface_width=2,
        surface_normal=rollers.top_normal,
        rollers=rollers,
        side_view=view,
    )


@pytest.mark.parametrize(
    "point",
    [
        LadderPoint(),
        LadderPoint((StepClick("side", 0, 2.0, 0.0),)),
        LadderPoint((StepClick("side", 0, 0.0, 100.0),)),
    ],
)
def test_side_view_missing_horizon_and_off_path_marks_have_no_solution(point) -> None:
    belt = replace(
        _side_belt(), visual_reference_frame=0, visual_frames=(BeltVisualFrame(0, point),)
    )
    assert visual.belt_visual_state(belt, 0, {}) is None


def test_side_view_motion_checks_use_the_profile_and_reject_its_horizon(monkeypatch) -> None:
    belt = _side_belt()
    check = MotionCheck(1, "side", 0.75, 0.25, 0, source_values=(1.0,))
    belt = replace(belt, binding=BeltBinding("sensor", "distance", 0, 0, 2, 1, (check,)))
    np.testing.assert_allclose(
        prop_motion_calibration._belt_residuals(np.array([2.0, 1.0]), belt, {}), [0, 0], atol=1e-6
    )
    from avialsync.core.plane_view import PlaneView

    monkeypatch.setattr(PlaneView, "pixel", lambda *args: None)
    with pytest.raises(PropMotionCalibrationError, match="side view"):
        prop_motion_calibration._belt_residuals(np.array([2.0, 1.0]), belt, {})


@pytest.mark.parametrize(
    "marks,problem",
    [
        (((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.999, 0.04, 0.0)), visual.MARKS_TOO_CLOSE),
        (((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0)), visual.NOT_RIGID),
    ],
)
def test_sphere_landmarks_must_identify_one_proper_rigid_rotation(marks, problem) -> None:
    centre = np.array([0.0, 0.0, 70.0])

    def observed(frame, vectors):
        return BallVisualFrame(
            frame, tuple(_clicked_point(tuple(centre + p), ("Front", "Left")) for p in vectors)
        )

    reference = observed(0, np.eye(3) if problem == visual.NOT_RIGID else marks)
    current = observed(1, marks)
    ball = BallProp(
        "ball",
        BallSurface(tuple(centre), 1),
        visual_reference_frame=0,
        visual_frames=(reference, current),
    )
    assert visual.ball_visual_problem(ball, 1, CAMERAS) == problem


def test_nonfinite_triangulation_remains_unresolved(monkeypatch) -> None:
    point = _clicked_point((0.0, 0.0, 70.0), ("Front", "Left"))
    monkeypatch.setattr(physical_props, "triangulate", lambda views: (np.full(3, np.nan), 0))
    assert point.resolved(CAMERAS).issue == "invalid_solution"
    for vertices in [(), ((np.nan, 0.0, 0.0), (1.0, 0.0, 0.0))]:
        with pytest.raises(PropModelError):
            BeltTrack(vertices)
    negative = UnitQuaternion.about_axis((0.0, 1.0, 0.0), math.pi * 1.5)
    vector = prop_motion_calibration._vector_from_quaternion(negative)
    assert np.linalg.norm(vector) == pytest.approx(math.pi / 2)


def test_side_view_checks_from_another_camera_cannot_fit_the_profile() -> None:
    belt = _side_belt()
    check = MotionCheck(1, "other", 0.75, 0.25, 0, source_values=(1.0,))
    belt = replace(belt, binding=BeltBinding("sensor", "distance", 0, 0, 2, 1, (check,)))
    with pytest.raises(PropMotionCalibrationError, match="placed camera"):
        prop_motion_calibration._belt_residuals(np.array([2.0, 1.0]), belt, {})


@pytest.mark.parametrize("failure", ["reprojection", "rank"])
def test_sphere_solver_quality_failures_preserve_every_raw_click(monkeypatch, failure) -> None:
    centre = np.array([0.0, 0.0, 70.0])
    marks = tuple(_clicked_point(tuple(centre + vector), ("Front", "Left")) for vector in np.eye(3))
    frame = BallVisualFrame(0, marks)
    ball = BallProp(
        "ball", BallSurface(tuple(centre), 1), visual_reference_frame=0, visual_frames=(frame,)
    )
    if failure == "reprojection":
        solve = visual._solved
        monkeypatch.setattr(
            visual, "_solved", lambda point, cameras: replace(solve(point, cameras), error_px=10)
        )
        expected = visual.INCONSISTENT_VIEWS
    else:
        monkeypatch.setattr(visual.np.linalg, "matrix_rank", lambda *args, **kwargs: 1)
        expected = visual.MARKS_TOO_CLOSE
    assert visual.ball_visual_problem(ball, 0, CAMERAS) == expected
    assert ball.visual_frames == (frame,) and frame.marks == marks
