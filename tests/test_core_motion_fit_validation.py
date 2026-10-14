"""Motion-fit proposals require identifiable evidence and successful finite solver results."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import numpy as np
import pytest

from avialsync.core import prop_motion_calibration as fitting
from avialsync.core.errors import PropMotionCalibrationError
from avialsync.core.physical_props import (
    BallBinding,
    BallProp,
    BallSurface,
    BeltBinding,
    BeltProp,
    BeltTrack,
    UnitQuaternion,
)
from tests.test_prop_motion_calibration import _check
from tests.wheel_fixture import CAMERAS


def _belt() -> BeltProp:
    checks = tuple(_check(i, (float(i + 2), 0.0, 70.0), (float(i),)) for i in range(3))
    return BeltProp(
        "belt",
        BeltTrack(((0.0, 0.0, 70.0), (20.0, 0.0, 70.0))),
        travel_direction=(1.0, 0.0, 0.0),
        binding=BeltBinding("encoder", "distance", 0, 0.0, 2.0, 1.0, checks),
    )


def _ball() -> BallProp:
    checks = tuple(_check(i, (1.0, 0.0, 70.0), (1.0, 0.0, 0.0, 0.0)) for i in range(3))
    return BallProp(
        "ball",
        BallSurface((0.0, 0.0, 70.0), 1.0),
        surface_marks=((1.0, 0.0, 0.0),),
        binding=BallBinding("imu", ("w", "x", "y", "z"), 0, UnitQuaternion.identity(), checks),
    )


@pytest.mark.parametrize("tolerance", [0.0, 1.0, np.nan, np.inf])
def test_belt_fit_rejects_invalid_scale_search_neighbourhood(tolerance: float) -> None:
    with pytest.raises(PropMotionCalibrationError, match="between zero and one"):
        fitting.fit_belt_motion(_belt(), CAMERAS, scale_tolerance=tolerance)


@pytest.mark.parametrize("kind", ["belt", "ball"])
def test_unbound_props_cannot_propose_a_channel_calibration(kind: str) -> None:
    prop = dataclasses.replace(_belt() if kind == "belt" else _ball(), binding=None)
    fitter = fitting.fit_belt_motion if kind == "belt" else fitting.fit_ball_motion
    with pytest.raises(PropMotionCalibrationError, match="Bind"):
        fitter(prop, CAMERAS)


def test_belt_fit_rejects_missing_or_constant_displacement_evidence() -> None:
    belt = _belt()
    for values in ((), (1.0,)):
        checks = tuple(dataclasses.replace(c, source_values=values) for c in belt.binding.checks)
        changed = dataclasses.replace(
            belt, binding=dataclasses.replace(belt.binding, checks=checks)
        )
        with pytest.raises(PropMotionCalibrationError, match="do not span"):
            fitting.fit_belt_motion(changed, CAMERAS)


def test_ball_fit_rejects_incomplete_orientation_evidence() -> None:
    ball = _ball()
    few = dataclasses.replace(ball, binding=dataclasses.replace(ball.binding, checks=()))
    with pytest.raises(PropMotionCalibrationError, match="at least three"):
        fitting.fit_ball_motion(few, CAMERAS)
    checks = tuple(dataclasses.replace(c, source_values=(1.0,)) for c in ball.binding.checks)
    changed = dataclasses.replace(ball, binding=dataclasses.replace(ball.binding, checks=checks))
    with pytest.raises(PropMotionCalibrationError, match="four orientation"):
        fitting.fit_ball_motion(changed, CAMERAS)


@pytest.mark.parametrize(
    ("kind", "success", "finite", "rank"),
    [
        ("belt", False, True, 2),
        ("belt", True, False, 2),
        ("belt", True, True, 1),
        ("ball", False, True, 3),
        ("ball", True, False, 3),
        ("ball", True, True, 2),
    ],
)
def test_solver_failure_nonfinite_result_or_rank_deficiency_never_becomes_a_proposal(
    monkeypatch, kind: str, success: bool, finite: bool, rank: int
) -> None:
    size = 2 if kind == "belt" else 3
    result = SimpleNamespace(
        success=success,
        x=np.zeros(size) if finite else np.full(size, np.nan),
        jac=np.eye(size)[:rank],
    )
    monkeypatch.setattr(fitting, "least_squares", lambda *args, **kwargs: result)
    fitter = fitting.fit_belt_motion if kind == "belt" else fitting.fit_ball_motion
    with pytest.raises(PropMotionCalibrationError):
        fitter(_belt() if kind == "belt" else _ball(), CAMERAS)


def test_camera_projection_requires_an_available_camera_and_visible_finite_point(
    monkeypatch,
) -> None:
    with pytest.raises(PropMotionCalibrationError, match="not available"):
        fitting._camera_pixel({}, "missing", (0.0, 0.0, 70.0))
    camera = CAMERAS["Front"]
    behind = camera.rotation_matrix().T @ (np.array([0.0, 0.0, -1.0]) - camera.translation)
    with pytest.raises(PropMotionCalibrationError, match="behind"):
        fitting._camera_pixel(CAMERAS, "Front", tuple(float(v) for v in behind))
    with monkeypatch.context() as patch:
        patch.setattr(
            type(CAMERAS["Front"]), "project", lambda *args: (np.array([np.nan, 0]), None)
        )
        with pytest.raises(PropMotionCalibrationError, match="cannot be projected"):
            fitting._camera_pixel(CAMERAS, "Front", (0.0, 0.0, 70.0))


def test_open_path_candidate_outside_span_has_finite_boundary_penalty() -> None:
    residuals = fitting._belt_residuals(np.array([0.0, 100.0]), _belt(), CAMERAS)
    assert np.isfinite(residuals).all() and np.max(np.abs(residuals)) > 1000.0


def test_residual_adapters_reject_missing_saved_readings() -> None:
    belt = _belt()
    checks = tuple(dataclasses.replace(c, source_values=()) for c in belt.binding.checks)
    belt = dataclasses.replace(belt, binding=dataclasses.replace(belt.binding, checks=checks))
    with pytest.raises(PropMotionCalibrationError, match="missing its displacement"):
        fitting._belt_residuals(np.array([2.0, 1.0]), belt, CAMERAS)
    ball = _ball()
    checks = tuple(dataclasses.replace(c, source_values=()) for c in ball.binding.checks)
    ball = dataclasses.replace(ball, binding=dataclasses.replace(ball.binding, checks=checks))
    with pytest.raises(PropMotionCalibrationError, match="missing its four"):
        fitting._ball_residuals(np.zeros(3), ball, CAMERAS)


def test_empty_proposals_report_no_invented_error_statistics() -> None:
    for proposal in (
        fitting.BeltMotionCalibrationProposal(0.0, 1.0, ()),
        fitting.BallMotionCalibrationProposal(UnitQuaternion.identity(), ()),
    ):
        assert proposal.observation_count == 0 and proposal.rms_px is None
    assert fitting.BeltMotionCalibrationProposal(0.0, 1.0, (3.0, 4.0)).observation_count == 2
    assert fitting.BallMotionCalibrationProposal(UnitQuaternion.identity(), (3.0, 4.0)).rms_px
    np.testing.assert_array_equal(
        fitting._vector_from_quaternion(UnitQuaternion.identity()), np.zeros(3)
    )
