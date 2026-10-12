"""Ground-truth video fitting for moving physical-prop channel bindings."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from avialsync.core.physical_props import (
    BallBinding,
    BallProp,
    BallSurface,
    BeltBinding,
    BeltProp,
    BeltTrack,
    MotionCheck,
    UnitQuaternion,
)
from avialsync.core.prop_motion_calibration import fit_ball_motion, fit_belt_motion
from tests.wheel_fixture import CAMERAS


def _check(frame: int, point: tuple[float, float, float], values: tuple[float, ...]) -> MotionCheck:
    """Create an exact Front-camera observation of a material point."""
    x, y = CAMERAS["Front"].project(np.asarray(point))[0]
    return MotionCheck(frame, "Front", float(x), float(y), 0.0, values)


def test_belt_video_checks_propose_and_persist_phase_and_scale(tmp_path: Path) -> None:
    """Three separated video checks recover a bounded displacement correction."""
    track = BeltTrack(((0.0, 0.0, 70.0), (20.0, 0.0, 70.0)))
    truth_binding = BeltBinding("encoder", "travel", 0, 0.0, 3.0, 1.1)
    truth = BeltProp("belt", track, travel_direction=(1.0, 0.0, 0.0), binding=truth_binding)
    readings = (1.0, 5.0, 9.0)
    checks = tuple(
        _check(frame, truth.material_point(reading), (reading,))
        for frame, reading in enumerate(readings, start=10)
    )
    belt = dataclasses.replace(
        truth,
        binding=BeltBinding("encoder", "travel", 0, 0.0, 1.0, 1.0, checks),
    )

    proposal = fit_belt_motion(belt, CAMERAS)

    assert proposal.reference_distance == pytest.approx(3.0, abs=1e-5)
    assert proposal.units_per_reading == pytest.approx(1.1, abs=1e-5)
    assert proposal.rms_px == pytest.approx(0.0, abs=1e-5)

    corrected = dataclasses.replace(
        belt,
        binding=dataclasses.replace(
            belt.binding,
            reference_distance=proposal.reference_distance,
            units_per_reading=proposal.units_per_reading,
        ),
    )
    from avialsync.core.prop_file import read_props, write_prop

    write_prop(tmp_path, corrected)
    restored, issues = read_props(tmp_path)
    assert not issues and restored == [corrected]


def test_ball_video_checks_propose_and_persist_sensor_axis_correction(tmp_path: Path) -> None:
    """Video evidence calibrates quaternion axes without moving the fixed sphere."""
    correction = UnitQuaternion.about_axis((0.0, 0.0, 1.0), 0.35)
    orientations = (
        UnitQuaternion.about_axis((1.0, 0.0, 0.0), 0.5),
        UnitQuaternion.about_axis((0.0, 1.0, 0.0), -0.7),
        UnitQuaternion.about_axis((1.0, 1.0, 1.0), 0.9),
    )
    truth_binding = BallBinding(
        "imu",
        ("w", "x", "y", "z"),
        0,
        UnitQuaternion.identity(),
        orientation_correction=(correction.w, correction.x, correction.y, correction.z),
    )
    truth = BallProp(
        "ball",
        BallSurface((0.0, 0.0, 70.0), 5.0),
        surface_marks=((1.0, 0.0, 0.0),),
        binding=truth_binding,
    )
    checks = tuple(
        _check(
            frame,
            truth.material_point(orientation),
            (orientation.w, orientation.x, orientation.y, orientation.z),
        )
        for frame, orientation in enumerate(orientations, start=10)
    )
    ball = dataclasses.replace(
        truth,
        binding=dataclasses.replace(
            truth_binding,
            checks=checks,
            orientation_correction=(1.0, 0.0, 0.0, 0.0),
        ),
    )

    proposal = fit_ball_motion(ball, CAMERAS)

    assert proposal.rms_px == pytest.approx(0.0, abs=1e-4)
    assert proposal.orientation_correction.rotate((1.0, 0.0, 0.0)) == pytest.approx(
        correction.rotate((1.0, 0.0, 0.0)), abs=1e-5
    )
    corrected = dataclasses.replace(
        ball,
        binding=dataclasses.replace(
            ball.binding,
            orientation_correction=(
                proposal.orientation_correction.w,
                proposal.orientation_correction.x,
                proposal.orientation_correction.y,
                proposal.orientation_correction.z,
            ),
        ),
    )
    for orientation in orientations:
        assert corrected.material_point(orientation) == pytest.approx(
            truth.material_point(orientation), abs=1e-5
        )

    from avialsync.core.prop_file import read_props, write_prop

    write_prop(tmp_path, corrected)
    restored, issues = read_props(tmp_path)
    assert not issues and restored == [corrected]


def test_motion_calibration_never_turns_too_little_video_evidence_into_a_fit() -> None:
    """The proposal path refuses a correction before it has enough checks."""
    belt = BeltProp(
        "belt",
        BeltTrack(((0.0, 0.0, 70.0), (20.0, 0.0, 70.0))),
        travel_direction=(1.0, 0.0, 0.0),
        binding=BeltBinding("encoder", "travel", 0, 0.0, 1.0, 1.0),
    )
    from avialsync.core.errors import PropMotionCalibrationError

    with pytest.raises(PropMotionCalibrationError, match="at least three"):
        fit_belt_motion(belt, CAMERAS)
