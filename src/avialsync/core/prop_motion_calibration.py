"""Fit explicit video-alignment proposals for moving physical props.

The fitters consume only durable video checks and frozen prop geometry. They
return proposals; callers retain the evidence and explicitly decide whether to
apply a correction. This parallels rotary calibration without pretending that
every moving apparatus shares a rotary transfer.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from avialsync.core.calibration import CameraModel
from avialsync.core.errors import PropMotionCalibrationError
from avialsync.core.physical_props import BallProp, BeltProp, Point3, UnitQuaternion

__all__ = [
    "BallMotionCalibrationProposal",
    "BeltMotionCalibrationProposal",
    "fit_ball_motion",
    "fit_belt_motion",
]


@dataclass(frozen=True)
class BeltMotionCalibrationProposal:
    """A reviewable displacement phase-and-scale correction from video checks."""

    reference_distance: float
    units_per_reading: float
    residuals_px: tuple[float, ...]

    @property
    def observation_count(self) -> int:
        """Number of camera checks represented by this proposal."""
        return len(self.residuals_px)

    @property
    def rms_px(self) -> float | None:
        """Root-mean-square image residual, or None without checks."""
        if not self.residuals_px:
            return None
        return math.sqrt(sum(value * value for value in self.residuals_px) / len(self.residuals_px))


@dataclass(frozen=True)
class BallMotionCalibrationProposal:
    """A reviewable fixed sensor-axis correction from video checks."""

    orientation_correction: UnitQuaternion
    residuals_px: tuple[float, ...]

    @property
    def observation_count(self) -> int:
        """Number of camera checks represented by this proposal."""
        return len(self.residuals_px)

    @property
    def rms_px(self) -> float | None:
        """Root-mean-square image residual, or None without checks."""
        if not self.residuals_px:
            return None
        return math.sqrt(sum(value * value for value in self.residuals_px) / len(self.residuals_px))


def _camera_pixel(cameras: Mapping[str, CameraModel], camera: str, point: Point3) -> np.ndarray:
    """Project a finite, camera-facing 3D point or explain why that is impossible."""
    model = cameras.get(camera)
    if model is None:
        raise PropMotionCalibrationError(
            f"Video check camera {camera!r} is not available in the current calibration."
        )
    xyz = np.asarray(point, dtype=np.float64)
    depth = float(model.rotation_matrix()[2] @ xyz + model.translation[2])
    if not math.isfinite(depth) or depth <= 0.0:
        raise PropMotionCalibrationError("A checked moving mark is behind its calibrated camera.")
    pixel = np.asarray(model.project(xyz)[0], dtype=np.float64)
    if pixel.shape != (2,) or not np.all(np.isfinite(pixel)):
        raise PropMotionCalibrationError(
            "A checked moving mark cannot be projected into its camera."
        )
    return pixel


def _belt_point(
    belt: BeltProp, reference_distance: float, scale: float, reading: float
) -> Point3 | None:
    """Locate a belt mark under candidate video-calibrated binding parameters."""
    binding = belt.binding
    assert binding is not None
    tangent = tuple(
        end - start
        for start, end in zip(belt.track.vertices[0], belt.track.vertices[1], strict=True)
    )
    direction = belt.travel_direction
    assert direction is not None
    alignment = sum(a * b for a, b in zip(tangent, direction, strict=True))
    # BeltProp validates nonzero alignment when a binding is constructed.
    travel = math.copysign(scale, alignment) * (reading - binding.reference_reading)
    if belt.rollers is not None:
        return belt.rollers.point_at(reference_distance + travel)
    return belt.track.material_point(reference_distance, travel)


def _belt_distance(
    belt: BeltProp, reference_distance: float, scale: float, reading: float
) -> float:
    """Return the unwrapped material distance for an open-path boundary penalty."""
    binding = belt.binding
    assert binding is not None
    tangent = tuple(
        end - start
        for start, end in zip(belt.track.vertices[0], belt.track.vertices[1], strict=True)
    )
    assert belt.travel_direction is not None
    alignment = sum(a * b for a, b in zip(tangent, belt.travel_direction, strict=True))
    return reference_distance + math.copysign(scale, alignment) * (
        reading - binding.reference_reading
    )


def _belt_residuals(
    parameters: np.ndarray,
    belt: BeltProp,
    cameras: Mapping[str, CameraModel],
) -> np.ndarray:
    """Return stacked image residuals for one belt phase-and-scale candidate."""
    binding = belt.binding
    assert binding is not None
    reference_distance, scale = (float(parameters[0]), float(parameters[1]))
    residuals: list[float] = []
    for check in binding.checks:
        if not check.source_values:
            raise PropMotionCalibrationError(
                "A saved belt check is missing its displacement reading."
            )
        reading = check.source_values[0]
        point = _belt_point(belt, reference_distance, scale, reading)
        boundary_penalty = 0.0
        if point is None:
            # ``least_squares`` samples outside the valid span while looking
            # for a solution.  Keep that trial finite and steer it back to the
            # endpoint instead of throwing out the entire optimisation.
            distance = _belt_distance(belt, reference_distance, scale, reading)
            boundary_penalty = 1_000.0 * max(0.0, -distance, distance - belt.path_length)
            clamped = float(np.clip(distance, 0.0, belt.path_length))
            point = belt.track.material_point(0.0, clamped)
            assert point is not None
        if belt.side_view is not None and belt.rollers is not None:
            if check.camera != belt.side_view.camera:
                raise PropMotionCalibrationError(
                    "A one-camera belt can only use checks from its placed camera."
                )
            pixel = belt.side_view.plane_view(belt.rollers).pixel(point[0], point[1])
            if pixel is None:
                raise PropMotionCalibrationError(
                    "A saved belt check cannot be mapped into its side view."
                )
            projected = np.asarray(pixel, dtype=np.float64)
        else:
            projected = _camera_pixel(cameras, check.camera, point)
        residuals.extend((projected[0] - check.x + boundary_penalty, projected[1] - check.y))
    return np.asarray(residuals, dtype=np.float64)


def _require_belt_evidence(belt: BeltProp) -> None:
    """Reject evidence that cannot identify both displacement parameters."""
    binding = belt.binding
    if binding is None:
        raise PropMotionCalibrationError("Bind belt displacement before fitting it to video.")
    if len(binding.checks) < 3:
        raise PropMotionCalibrationError("Save video checks on at least three belt frames first.")
    readings = np.asarray(
        [check.source_values[0] for check in binding.checks if check.source_values],
        dtype=np.float64,
    )
    if len(readings) != len(binding.checks) or float(np.ptp(readings)) <= np.finfo(float).eps:
        raise PropMotionCalibrationError(
            "The saved belt checks do not span any displacement-channel movement."
        )


def fit_belt_motion(
    belt: BeltProp, cameras: Mapping[str, CameraModel], *, scale_tolerance: float = 0.25
) -> BeltMotionCalibrationProposal:
    """Propose belt reference distance and scale from saved video checks.

    The scale stays near the user-declared value. A grossly different
    conversion is a physical-units correction the user must declare, not an
    alias chosen by a least-squares solver.
    """
    _require_belt_evidence(belt)
    binding = belt.binding
    assert binding is not None
    if not math.isfinite(scale_tolerance) or not 0.0 < scale_tolerance < 1.0:
        raise PropMotionCalibrationError("Belt scale tolerance must lie between zero and one.")
    lower_scale = binding.units_per_reading * (1.0 - scale_tolerance)
    upper_scale = binding.units_per_reading * (1.0 + scale_tolerance)
    result = least_squares(
        lambda values: _belt_residuals(values, belt, cameras),
        np.asarray((binding.reference_distance, binding.units_per_reading), dtype=np.float64),
        bounds=((0.0, lower_scale), (belt.path_length, upper_scale)),
        loss="soft_l1",
        f_scale=2.0,
        x_scale="jac",
    )
    if not result.success or not np.all(np.isfinite(result.x)):
        raise PropMotionCalibrationError("Video checks did not produce a belt-motion proposal.")
    if np.linalg.matrix_rank(result.jac) < 2:
        raise PropMotionCalibrationError(
            "The saved belt checks do not independently identify phase and distance scale."
        )
    residuals = _belt_residuals(result.x, belt, cameras).reshape(-1, 2)
    return BeltMotionCalibrationProposal(
        float(result.x[0]),
        float(result.x[1]),
        tuple(float(np.linalg.norm(row)) for row in residuals),
    )


def _quaternion_from_vector(vector: np.ndarray) -> UnitQuaternion:
    """Turn a three-component axis-angle vector into a unit quaternion."""
    angle = float(np.linalg.norm(vector))
    if angle < 1e-12:
        return UnitQuaternion.identity()
    return UnitQuaternion.about_axis(
        (float(vector[0] / angle), float(vector[1] / angle), float(vector[2] / angle)), angle
    )


def _vector_from_quaternion(quaternion: UnitQuaternion) -> np.ndarray:
    """Return the shortest axis-angle vector for a unit quaternion."""
    sign = 1.0 if quaternion.w >= 0.0 else -1.0
    vector = sign * np.asarray((quaternion.x, quaternion.y, quaternion.z), dtype=np.float64)
    sine = float(np.linalg.norm(vector))
    if sine < 1e-12:
        return np.zeros(3, dtype=np.float64)
    angle = 2.0 * math.atan2(sine, sign * quaternion.w)
    return vector * (angle / sine)


def _ball_residuals(
    parameters: np.ndarray,
    ball: BallProp,
    cameras: Mapping[str, CameraModel],
) -> np.ndarray:
    """Return image residuals after conjugating sensor rotation into visual axes."""
    binding = ball.binding
    assert binding is not None
    correction = _quaternion_from_vector(parameters)
    residuals: list[float] = []
    for check in binding.checks:
        if len(check.source_values) != 4:
            raise PropMotionCalibrationError(
                "A saved ball check is missing its four orientation readings."
            )
        relative = UnitQuaternion(*check.source_values).composed(
            binding.reference_orientation.inverse()
        )
        visual_relative = correction.composed(relative).composed(correction.inverse())
        point = ball.surface.material_point(ball.surface_marks[0], visual_relative)
        projected = _camera_pixel(cameras, check.camera, point)
        residuals.extend((projected[0] - check.x, projected[1] - check.y))
    return np.asarray(residuals, dtype=np.float64)


def _require_ball_evidence(ball: BallProp) -> None:
    """Reject video checks that cannot identify three orientation axes."""
    binding = ball.binding
    if binding is None:
        raise PropMotionCalibrationError("Bind ball orientation before fitting it to video.")
    if len(binding.checks) < 3:
        raise PropMotionCalibrationError("Save video checks on at least three ball frames first.")
    # BallProp requires an identified surface mark whenever a binding exists.
    if any(len(check.source_values) != 4 for check in binding.checks):
        raise PropMotionCalibrationError("Saved ball checks must retain four orientation readings.")


def fit_ball_motion(
    ball: BallProp, cameras: Mapping[str, CameraModel]
) -> BallMotionCalibrationProposal:
    """Propose a fixed sensor-to-video orientation-axis correction from checks."""
    _require_ball_evidence(ball)
    binding = ball.binding
    assert binding is not None
    initial = UnitQuaternion(*binding.orientation_correction)
    result = least_squares(
        lambda values: _ball_residuals(values, ball, cameras),
        _vector_from_quaternion(initial),
        loss="soft_l1",
        f_scale=2.0,
        x_scale="jac",
    )
    if not result.success or not np.all(np.isfinite(result.x)):
        raise PropMotionCalibrationError("Video checks did not produce a ball-motion proposal.")
    if np.linalg.matrix_rank(result.jac) < 3:
        raise PropMotionCalibrationError(
            "The saved ball checks do not independently identify its three orientation axes."
        )
    residuals = _ball_residuals(result.x, ball, cameras).reshape(-1, 2)
    return BallMotionCalibrationProposal(
        _quaternion_from_vector(result.x),
        tuple(float(np.linalg.norm(row)) for row in residuals),
    )
