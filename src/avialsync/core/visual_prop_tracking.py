"""Solve visual-only prop motion from named, calibrated camera observations.

Each result belongs to an actually observed reference-camera frame. Raw clicks
remain in the prop; changing calibration recomputes the fit on demand.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from avialsync.core.calibration import CameraModel
from avialsync.core.physical_props import BallProp, BeltProp, LadderPoint, Point3


@dataclass(frozen=True)
class BeltVisualState:
    """A mark's measured path position and fit quality on one frame."""

    point: Point3
    path_distance: float
    offset: float
    error_px: float
    lap: int | None


@dataclass(frozen=True)
class BallVisualState:
    """Three rotated marks and residual of a measured rigid sphere orientation."""

    marks: tuple[Point3, Point3, Point3]
    residual: float
    error_px: float


def _solved(point: LadderPoint, cameras: Mapping[str, CameraModel]) -> LadderPoint:
    return point.resolved(cameras)


#: Why an observed frame has no visual solution, when it is not simply missing
#: clicks: the typed geometry and the clicks disagree, or the clicks cannot be
#: told apart. Each needs the user to change something other than click more.
OFF_PATH = "off_path"
INCONSISTENT_VIEWS = "inconsistent_views"
AMBIGUOUS_CROSSING = "ambiguous_crossing"
OFF_SPHERE = "off_sphere"
MARKS_TOO_CLOSE = "marks_too_close"
NOT_RIGID = "not_rigid"


def belt_visual_state(
    belt: BeltProp, frame: int, cameras: Mapping[str, CameraModel]
) -> BeltVisualState | None:
    """Project a stereo-observed material mark onto the declared support path.

    A crossing or two equally plausible path segments is ambiguous. A closed
    path's lap count stays unknown until a user explicitly supplies it.
    """
    return _belt_visual(belt, frame, cameras)[0]


def belt_visual_problem(
    belt: BeltProp, frame: int, cameras: Mapping[str, CameraModel]
) -> str | None:
    """Why a fully clicked belt frame has no solution, or None."""
    return _belt_visual(belt, frame, cameras)[1]


def _belt_visual(
    belt: BeltProp, frame: int, cameras: Mapping[str, CameraModel]
) -> tuple[BeltVisualState | None, str | None]:
    observation = next((item for item in belt.visual_frames if item.frame == frame), None)
    if observation is None:
        return None, None
    solved = _solved(observation.point, cameras)
    if solved.xyz is None or solved.error_px is None:
        return None, None
    if solved.error_px > 5.0:
        return None, INCONSISTENT_VIEWS
    xyz = np.asarray(solved.xyz, dtype=np.float64)
    vertices = belt.track.vertices
    segments = zip(
        vertices if belt.track.closed else vertices[:-1],
        (*vertices[1:], vertices[0]) if belt.track.closed else vertices[1:],
        strict=True,
    )
    candidates: list[tuple[float, float, Point3]] = []
    distance = 0.0
    for start, end in segments:
        a, b = np.asarray(start), np.asarray(end)
        vector = b - a
        length = float(np.linalg.norm(vector))
        fraction = float(np.clip(np.dot(xyz - a, vector) / (length * length), 0.0, 1.0))
        projected = a + fraction * vector
        candidates.append(
            (
                float(np.linalg.norm(xyz - projected)),
                distance + fraction * length,
                (float(projected[0]), float(projected[1]), float(projected[2])),
            )
        )
        distance += length
    candidates.sort(key=lambda item: item[0])
    best = candidates[0]
    tolerance = max(1e-6, belt.track.length * 0.05)
    if best[0] > tolerance:
        # A mark clicked well in two cameras that lies off the typed path means
        # the path, or its units, disagree with the calibration.
        return None, OFF_PATH
    # Adjacent segments sharing a vertex agree on its path distance. A crossing
    # at different distances has no uniquely identifiable surface location.
    if any(
        abs(other[0] - best[0]) < tolerance * 0.05
        and abs(other[1] - best[1]) > tolerance * 0.05
        and abs(other[1] - best[1]) < belt.track.length - tolerance * 0.05
        for other in candidates[1:]
    ):
        return None, AMBIGUOUS_CROSSING
    return BeltVisualState(best[2], best[1], best[0], solved.error_px, observation.lap), None


def belt_visual_travel(
    belt: BeltProp, frame: int, cameras: Mapping[str, CameraModel]
) -> float | None:
    """Signed travel from the observed reference, requiring laps on closed paths."""
    if belt.visual_reference_frame is None:
        return None
    reference = belt_visual_state(belt, belt.visual_reference_frame, cameras)
    current = belt_visual_state(belt, frame, cameras)
    if reference is None or current is None:
        return None
    direction = belt.travel_direction
    if direction is None:
        return None
    tangent = np.asarray(belt.track.vertices[1]) - np.asarray(belt.track.vertices[0])
    sign = math.copysign(1.0, float(np.dot(tangent, direction)))
    if belt.track.closed:
        if reference.lap is None or current.lap is None:
            return None
        return sign * (
            current.path_distance
            - reference.path_distance
            + (current.lap - reference.lap) * belt.track.length
        )
    return sign * (current.path_distance - reference.path_distance)


def ball_visual_state(
    ball: BallProp, frame: int, cameras: Mapping[str, CameraModel]
) -> BallVisualState | None:
    """Fit proper SO(3) rotation to three corresponding surface landmarks."""
    return _ball_visual(ball, frame, cameras)[0]


def ball_visual_problem(
    ball: BallProp, frame: int, cameras: Mapping[str, CameraModel]
) -> str | None:
    """Why a fully clicked ball frame has no orientation, or None."""
    return _ball_visual(ball, frame, cameras)[1]


def _ball_visual(
    ball: BallProp, frame: int, cameras: Mapping[str, CameraModel]
) -> tuple[BallVisualState | None, str | None]:
    reference = next(
        (item for item in ball.visual_frames if item.frame == ball.visual_reference_frame), None
    )
    current = next((item for item in ball.visual_frames if item.frame == frame), None)
    if reference is None or current is None:
        return None, None
    reference_points = tuple(_solved(point, cameras) for point in reference.marks)
    current_points = tuple(_solved(point, cameras) for point in current.marks)
    all_points = (*reference_points, *current_points)
    if any(point.xyz is None or point.error_px is None for point in all_points):
        return None, None
    if any((point.error_px or 0.0) > 5.0 for point in all_points):
        return None, INCONSISTENT_VIEWS
    refs = list(reference_points)
    now = list(current_points)
    centre = np.asarray(ball.surface.centre, dtype=np.float64)
    origin = np.stack([np.asarray(point.xyz) - centre for point in refs])
    target = np.stack([np.asarray(point.xyz) - centre for point in now])
    radius = ball.surface.radius
    if np.any(abs(np.linalg.norm(origin, axis=1) - radius) > radius * 0.1) or np.any(
        abs(np.linalg.norm(target, axis=1) - radius) > radius * 0.1
    ):
        # Marks located in 3D but off the typed sphere: its centre, radius or
        # units disagree with the calibration.
        return None, OFF_SPHERE
    origin /= np.linalg.norm(origin, axis=1)[:, None]
    target /= np.linalg.norm(target, axis=1)[:, None]
    if any(
        float(np.linalg.norm(points[a] - points[b])) < 0.1
        for points in (origin, target)
        for a, b in ((0, 1), (0, 2), (1, 2))
    ):
        return None, MARKS_TOO_CLOSE
    if np.linalg.matrix_rank(origin, tol=0.05) < 2 or np.linalg.matrix_rank(target, tol=0.05) < 2:
        return None, MARKS_TOO_CLOSE
    left, _singular, right = np.linalg.svd(target.T @ origin)
    correction = np.diag((1.0, 1.0, float(np.linalg.det(left @ right))))
    rotation = left @ correction @ right
    residual = float(np.sqrt(np.mean(np.sum(((rotation @ origin.T).T - target) ** 2, axis=1))))
    if not math.isfinite(residual) or residual > 0.1:
        return None, NOT_RIGID
    marks = tuple(
        (
            float((centre + radius * rotated)[0]),
            float((centre + radius * rotated)[1]),
            float((centre + radius * rotated)[2]),
        )
        for rotated in (rotation @ origin.T).T
    )
    return (
        BallVisualState(
            (marks[0], marks[1], marks[2]),
            residual * radius,
            max(point.error_px or 0.0 for point in (*refs, *now)),
        ),
        None,
    )
