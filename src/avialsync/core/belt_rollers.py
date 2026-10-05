"""Exact centreline and measured surface of a level two roller treadmill belt.

A belt is placed either in the calibration's 3D frame, from four clicked top
corners seen by two cameras, or in one camera's view of its side plane
(D-163, D-165). Either way the measured centre distance and radius size it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from avialsync.core.errors import PropModelError
from avialsync.core.plane_view import PlaneView

Point3 = tuple[float, float, float]
Pixel = tuple[float, float]


def _point(values: np.ndarray) -> Point3:
    return (float(values[0]), float(values[1]), float(values[2]))


@dataclass(frozen=True)
class BeltRollers:
    """Equal-radius rollers with parallel axles and a measured belt width.

    ``top_normal`` points from the roller centres towards the animal-facing
    run. The first centre to the second defines positive centreline travel.
    """

    first: Point3
    second: Point3
    radius: float
    width: float
    top_normal: Point3

    def __post_init__(self) -> None:
        values = (*self.first, *self.second, self.radius, self.width, *self.top_normal)
        if not all(math.isfinite(value) for value in values):
            raise PropModelError("Belt roller dimensions must be finite.")
        if self.radius <= 0 or self.width <= 0:
            raise PropModelError("Belt roller radius and width must be positive.")
        run = np.asarray(self.second) - np.asarray(self.first)
        normal = np.asarray(self.top_normal)
        if np.linalg.norm(run) < 1e-9 or np.linalg.norm(normal) < 1e-9:
            raise PropModelError("Belt rollers need distinct centres and a top direction.")
        run /= np.linalg.norm(run)
        normal /= np.linalg.norm(normal)
        if abs(float(np.dot(run, normal))) > 1e-6:
            raise PropModelError("Belt top direction must be perpendicular to roller travel.")
        object.__setattr__(self, "top_normal", _point(normal))

    @property
    def run_length(self) -> float:
        """Centre separation and length of either straight belt run."""
        return math.dist(self.first, self.second)

    @property
    def length(self) -> float:
        """Exact material loop length: two straight runs and two semicircles."""
        return 2.0 * self.run_length + 2.0 * math.pi * self.radius

    def axes(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Unit travel, top and roller-axis vectors in world coordinates."""
        run = (np.asarray(self.second) - np.asarray(self.first)) / self.run_length
        top = np.asarray(self.top_normal)
        axle = np.cross(top, run)
        return run, top, axle

    def point_at(self, distance: float) -> Point3:
        """Locate material distance along top, far wrap, return, near wrap."""
        if not math.isfinite(distance):
            raise PropModelError("Belt travel must be finite.")
        s = distance % self.length
        run, top, _ = self.axes()
        first, second = np.asarray(self.first), np.asarray(self.second)
        if s < self.run_length:
            xyz = first + self.radius * top + s * run
        elif s < self.run_length + math.pi * self.radius:
            angle = (s - self.run_length) / self.radius
            xyz = second + self.radius * (math.cos(angle) * top + math.sin(angle) * run)
        elif s < 2.0 * self.run_length + math.pi * self.radius:
            back = s - self.run_length - math.pi * self.radius
            xyz = second - self.radius * top - back * run
        else:
            angle = (s - 2.0 * self.run_length - math.pi * self.radius) / self.radius
            xyz = first + self.radius * (-math.cos(angle) * top - math.sin(angle) * run)
        return _point(xyz)

    def closest(self, point: Point3) -> tuple[float, float, Point3]:
        """Exact nearest centreline distance, path coordinate and location."""
        xyz = np.asarray(point)
        run, top, _ = self.axes()
        first, second = np.asarray(self.first), np.asarray(self.second)
        candidates: list[float] = []
        along = float(np.clip(np.dot(xyz - first, run), 0.0, self.run_length))
        candidates.append(along)
        candidates.append(self.run_length + math.pi * self.radius + self.run_length - along)
        far = xyz - second
        far_angle = math.atan2(float(np.dot(far, run)), float(np.dot(far, top)))
        candidates.append(self.run_length + self.radius * float(np.clip(far_angle, 0.0, math.pi)))
        near = xyz - first
        near_angle = math.atan2(float(-np.dot(near, run)), float(-np.dot(near, top)))
        candidates.append(
            2.0 * self.run_length
            + math.pi * self.radius
            + self.radius * float(np.clip(near_angle, 0.0, math.pi))
        )
        best = min(candidates, key=lambda distance: math.dist(point, self.point_at(distance)))
        closest = self.point_at(best)
        return math.dist(point, closest), best % self.length, closest

    def sample_distances(self, arc_steps: int = 16) -> tuple[float, ...]:
        """Display tessellation; motion calculations retain the analytic path."""
        if arc_steps < 2:
            raise ValueError("A roller arc needs at least two display segments.")
        arc = math.pi * self.radius
        far = tuple(self.run_length + arc * i / arc_steps for i in range(arc_steps + 1))
        near_start = 2.0 * self.run_length + arc
        near = tuple(near_start + arc * i / arc_steps for i in range(arc_steps))
        return (0.0, *far, *near)

    def surface_quads(self) -> tuple[tuple[Point3, Point3, Point3, Point3], ...]:
        """Tessellated surface with the same width across both runs and wraps."""
        _, _, axle = self.axes()
        half = axle * (self.width / 2.0)
        distances = (*self.sample_distances(), self.length)
        quads: list[tuple[Point3, Point3, Point3, Point3]] = []
        for start, end in zip(distances, distances[1:], strict=False):
            a, b = np.asarray(self.point_at(start)), np.asarray(self.point_at(end))
            quads.append((_point(a - half), _point(a + half), _point(b + half), _point(b - half)))
        return tuple(quads)


def rollers_from_corners(
    corners: tuple[Point3, Point3, Point3, Point3],
    radius: float,
    centre_distance: float | None,
    viewpoint: Point3,
) -> tuple[BeltRollers, float, float]:
    """Place measured rollers under four clicked corners of the top run (D-165).

    The corners are the two side edges near the first roller, then the two
    near the second. They fix where the belt is: its top plane, its run, its
    width and its middle. The measured ``centre_distance`` and ``radius`` fix
    its size; without a centre distance, the clicked span stands in for it.
    The top faces the cameras, so the plane normal points to ``viewpoint``.
    Returns the rollers, the clicked span, and the largest distance of a
    corner from the fitted plane, so a caller can say how flat the clicks are.
    """
    points = np.asarray(corners, dtype=np.float64)
    if points.shape != (4, 3) or not np.isfinite(points).all():
        raise PropModelError("A belt needs four finite clicked corners.")
    middle = points.mean(axis=0)
    _, _, vh = np.linalg.svd(points - middle)
    normal = vh[-1]
    if float(normal @ (np.asarray(viewpoint, dtype=np.float64) - middle)) < 0:
        normal = -normal
    flatness = float(np.max(np.abs((points - middle) @ normal)))
    run = (points[2] + points[3] - points[0] - points[1]) / 2.0
    span = float(np.linalg.norm(run))
    run -= float(run @ normal) * normal
    if span < 1e-9 or float(np.linalg.norm(run)) < 1e-9:
        raise PropModelError("The corners near each roller must be apart along the belt.")
    run /= np.linalg.norm(run)
    axle = np.cross(normal, run)
    width = (
        abs(float((points[1] - points[0]) @ axle)) + abs(float((points[3] - points[2]) @ axle))
    ) / 2
    length = span if centre_distance is None else centre_distance
    centre = middle - radius * normal
    rollers = BeltRollers(
        _point(centre - run * length / 2.0),
        _point(centre + run * length / 2.0),
        radius,
        width,
        _point(normal),
    )
    return rollers, span, flatness


def side_rollers(centre_distance: float, radius: float, width: float) -> BeltRollers:
    """Rollers in a one-camera belt's own side plane: x from hub 1 to hub 2, y up."""
    return BeltRollers((0.0, 0.0, 0.0), (centre_distance, 0.0, 0.0), radius, width, (0.0, 1.0, 0.0))


@dataclass(frozen=True)
class BeltSideView:
    """Four clicks that place a measured belt's side profile in one camera (D-165).

    The clicks are the first and second roller hubs, then the belt's top
    directly above each. With the measured centre distance and radius these
    are four known points of the side plane, so the profile is drawn with
    correct perspective without any calibration. The model is not placed in
    3D; its coordinates are that plane's, in the measurement units.
    """

    camera: str
    frame: int
    pixels: tuple[
        tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]
    ]

    def __post_init__(self) -> None:
        values = [value for pixel in self.pixels for value in pixel]
        if not self.camera or self.frame < 0 or len(self.pixels) != 4:
            raise PropModelError("A one-camera belt needs a camera, a frame and four clicks.")
        if len(values) != 8 or not all(math.isfinite(value) for value in values):
            raise PropModelError("A one-camera belt needs four finite clicks.")

    def plane_view(self, rollers: BeltRollers) -> PlaneView:
        """The map from the side plane to this camera's pixels."""
        length, radius = rollers.run_length, rollers.radius
        plane = ((0.0, 0.0), (length, 0.0), (0.0, radius), (length, radius))
        return PlaneView(plane, self.pixels)

    @staticmethod
    def is_side_frame(rollers: BeltRollers) -> bool:
        """Whether rollers are expressed in the side plane this view maps."""
        return (
            rollers.first == (0.0, 0.0, 0.0)
            and rollers.second[1:] == (0.0, 0.0)
            and rollers.second[0] > 0
            and rollers.top_normal == (0.0, 1.0, 0.0)
        )
