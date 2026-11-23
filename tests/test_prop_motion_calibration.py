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


def test_open_belt_boundary_penalty_never_cancels_negative_pixel_error() -> None:
    """Out-of-bounds penalties are independent residuals and cannot cancel signed X error."""
    from avialsync.core.prop_motion_calibration import _belt_residuals

    track = BeltTrack(((0.0, 0.0, 70.0), (20.0, 0.0, 70.0)), closed=False)
    truth_binding = BeltBinding("encoder", "travel", 0, 0.0, 2.0, 1.0)
    truth = BeltProp("belt", track, travel_direction=(1.0, 0.0, 70.0 - 70.0), binding=truth_binding)
    checks = tuple(
        _check(10 + idx, truth.material_point(r), (r,)) for idx, r in enumerate((1.0, 6.0, 12.0))
    )
    # Shift one check's X rightward so projected[0] - check.x is negative when clamped at 0.
    shifted_check = dataclasses.replace(checks[0], x=checks[0].x + 200.0)
    belt = dataclasses.replace(
        truth,
        binding=BeltBinding("encoder", "travel", 0, 0.0, 2.0, 1.0, (shifted_check, *checks[1:])),
    )
    # Parameter (-2.0, 1.0) places reading=1.0 at distance -1.0 (1.0 unit out of bounds).
    res = _belt_residuals(np.asarray((-2.0, 1.0)), belt, CAMERAS, 0.0)
    assert len(res) == 9  # 6 pixel components + 3 independent boundary penalties
    assert res[0] < -100.0  # signed X pixel error preserved uncancelled
    assert res[6] == pytest.approx(1_000.0)  # 1000 * |-1.0| independent penalty


def test_closed_roller_belt_crosses_seam_and_honours_realigned_reference() -> None:
    """Closed roller belts optimize smoothly across 0 == length and accept a live reference."""
    from avialsync.core.belt_rollers import BeltRollers

    rollers = BeltRollers((0.0, 0.0, 70.0), (20.0, 0.0, 70.0), 3.0, 4.0, (0.0, 1.0, 0.0))
    vertices = tuple(rollers.point_at(s) for s in rollers.sample_distances())
    live_ref = 50.0
    truth_binding = BeltBinding("encoder", "travel", 0, live_ref, 0.4, 1.08)
    truth = BeltProp(
        "roller_belt",
        BeltTrack(vertices, closed=True),
        travel_direction=(1.0, 0.0, 0.0),
        surface_width=4.0,
        surface_normal=(0.0, 1.0, 0.0),
        rollers=rollers,
        binding=truth_binding,
    )
    readings = (51.0, 58.0, 67.0, 79.0)
    checks = tuple(
        _check(frame, truth.material_point(r, live_ref), (r,))
        for frame, r in enumerate(readings, start=10)
    )
    # Start on the opposite side of the 0 == length seam with a stale pre-alignment reference 0.0.
    stale_binding = BeltBinding("encoder", "travel", 0, 0.0, rollers.length - 0.9, 1.0, checks)
    belt = dataclasses.replace(truth, binding=stale_binding)

    proposal = fit_belt_motion(belt, CAMERAS, reference_reading=live_ref)

    assert proposal.reference_distance == pytest.approx(0.4, abs=1e-4)
    assert proposal.units_per_reading == pytest.approx(1.08, abs=1e-4)
    assert proposal.reference_reading == pytest.approx(live_ref)
    assert proposal.rms_px == pytest.approx(0.0, abs=1e-4)


def test_ball_fit_recovers_sideways_and_inverted_sensor_mountings() -> None:
    """Octahedral SO(3) multi-start recovers > 90/180 deg axis swaps from identity."""
    from scipy.spatial.transform import Rotation

    rotvec = Rotation.from_euler("xyz", [95.0, -165.0, 42.0], degrees=True).as_rotvec()
    angle = float(np.linalg.norm(rotvec))
    correction = UnitQuaternion.about_axis(
        (float(rotvec[0] / angle), float(rotvec[1] / angle), float(rotvec[2] / angle)), angle
    )
    live_ref = UnitQuaternion.about_axis((0.0, 1.0, 0.0), 0.3)
    orientations = (
        UnitQuaternion.about_axis((1.0, 0.0, 0.0), 0.65),
        UnitQuaternion.about_axis((0.0, 1.0, 0.0), -0.85),
        UnitQuaternion.about_axis((0.0, 0.0, 1.0), 1.15),
        UnitQuaternion.about_axis((1.0, -1.0, 0.5), 0.95),
    )
    truth_binding = BallBinding(
        "imu",
        ("w", "x", "y", "z"),
        0,
        live_ref,
        orientation_correction=(correction.w, correction.x, correction.y, correction.z),
    )
    truth = BallProp(
        "ball",
        BallSurface((0.0, 0.0, 70.0), 5.0),
        surface_marks=((0.6, 0.8, 0.0),),
        binding=truth_binding,
    )
    checks = tuple(
        _check(
            frame,
            truth.material_point(q, live_ref),
            (q.w, q.x, q.y, q.z),
        )
        for frame, q in enumerate(orientations, start=10)
    )
    # Binding carries stale identity reference and identity correction; live_ref passed explicitly.
    ball = dataclasses.replace(
        truth,
        binding=BallBinding(
            "imu",
            ("w", "x", "y", "z"),
            0,
            UnitQuaternion.identity(),
            checks=checks,
            orientation_correction=(1.0, 0.0, 0.0, 0.0),
        ),
    )

    proposal = fit_ball_motion(ball, CAMERAS, reference_orientation=live_ref)

    assert proposal.rms_px == pytest.approx(0.0, abs=1e-4)
    assert proposal.reference_orientation == live_ref
    probe = UnitQuaternion.about_axis((-0.4, 0.7, 0.5), 1.1)
    fitted_ball = dataclasses.replace(
        truth,
        binding=dataclasses.replace(
            truth_binding,
            orientation_correction=(
                proposal.orientation_correction.w,
                proposal.orientation_correction.x,
                proposal.orientation_correction.y,
                proposal.orientation_correction.z,
            ),
        ),
    )
    assert fitted_ball.material_point(probe, live_ref) == pytest.approx(
        truth.material_point(probe, live_ref), abs=1e-4
    )
