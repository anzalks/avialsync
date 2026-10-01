"""Evidence-preserving geometry and material motion for physical props (D-149).

The fixed apparatus and its moving material are different things. A belt's
support stays put while a mark on its surface travels; a ball's centre stays
put while a local surface direction rotates. A ladder records each clicked
step independently, without a generated pitch or level. The existing wheel
owns its fit and file; :class:`WheelMaterialMap` only adapts its proven bar
geometry to the same material-point vocabulary.

No state here is inferred from a source channel. A caller must supply measured
travel, orientation, or turn at the displayed frame's presentation time; when
it cannot, it leaves motion unknown instead of calling a map with zero.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from avialsync.core.calibration import CameraModel, triangulate
from avialsync.core.errors import PropModelError
from avialsync.core.wheel import WheelGeometry

__all__ = [
    "Point3",
    "StepClick",
    "LadderPointIssue",
    "LadderPoint",
    "LadderStep",
    "Ladder",
    "PropStore",
    "BeltTrack",
    "UnitQuaternion",
    "BallSurface",
    "WheelMaterialMap",
]

Point3 = tuple[float, float, float]
LadderPointIssue = Literal["need_two_calibrated_views", "rays_parallel", "invalid_solution"]
_MIN_RAY_ANGLE_DEG = 1.0


def _finite_point(point: Point3) -> bool:
    return len(point) == 3 and all(math.isfinite(value) for value in point)


def _distance(a: Point3, b: Point3) -> float:
    return math.dist(a, b)


def _interpolate(a: Point3, b: Point3, fraction: float) -> Point3:
    return (
        a[0] + (b[0] - a[0]) * fraction,
        a[1] + (b[1] - a[1]) * fraction,
        a[2] + (b[2] - a[2]) * fraction,
    )


@dataclass(frozen=True)
class StepClick:
    """One camera's actual pixel observation of a static ladder point."""

    camera: str
    frame: int
    x: float
    y: float

    def __post_init__(self) -> None:
        if not self.camera or self.frame < 0 or not all(map(math.isfinite, (self.x, self.y))):
            raise PropModelError("A step click needs a camera, frame, and finite pixels.")


def _rays_have_depth(views: Sequence[tuple[CameraModel, tuple[float, float]]]) -> bool:
    """Whether two camera rays cross at a useful angle, independent of their names."""
    directions: list[np.ndarray] = []
    for camera, pixel in views:
        x, y = camera.normalise(np.asarray([pixel], dtype=np.float64))[0]
        direction = camera.rotation_matrix().T @ np.asarray((x, y, 1.0))
        directions.append(direction / np.linalg.norm(direction))
    threshold = math.sin(math.radians(_MIN_RAY_ANGLE_DEG))
    return any(
        float(np.linalg.norm(np.cross(a, b))) >= threshold
        for index, a in enumerate(directions)
        for b in directions[index + 1 :]
    )


@dataclass(frozen=True)
class LadderPoint:
    """Clicked views are authoritative; a 3D point is derived only when observable.

    ``issue`` is a stable code for the UI to translate. A projected position in
    an unclicked view is never inserted into ``clicks``.
    """

    clicks: tuple[StepClick, ...] = ()
    xyz: Point3 | None = None
    error_px: float | None = None
    issue: LadderPointIssue | None = None

    def __post_init__(self) -> None:
        names = [click.camera for click in self.clicks]
        if len(names) != len(set(names)):
            raise PropModelError("A ladder point has at most one click per camera.")
        object.__setattr__(
            self, "clicks", tuple(sorted(self.clicks, key=lambda click: click.camera))
        )
        if self.xyz is not None and not _finite_point(self.xyz):
            raise PropModelError("A ladder point needs finite 3D coordinates.")
        if self.error_px is not None and (not math.isfinite(self.error_px) or self.error_px < 0):
            raise PropModelError("A ladder point needs a finite reprojection error.")
        if self.xyz is None and self.error_px is not None:
            raise PropModelError("A reprojection error needs a solved 3D point.")
        if self.xyz is not None and (len(self.clicks) < 2 or self.error_px is None):
            raise PropModelError("A 3D ladder point needs two real clicks and a fit error.")
        if self.xyz is not None and self.issue is not None:
            raise PropModelError("A solved ladder point cannot have an unresolved issue.")

    def with_click(self, click: StepClick) -> LadderPoint:
        """Replace this camera's observation and invalidate the derived 3D point."""
        clicks = {item.camera: item for item in self.clicks}
        if clicks.get(click.camera) == click:
            return self
        clicks[click.camera] = click
        return dataclasses.replace(
            self,
            clicks=tuple(clicks[name] for name in sorted(clicks)),
            xyz=None,
            error_px=None,
            issue="need_two_calibrated_views",
        )

    def without_click(self, camera: str) -> LadderPoint:
        """Remove one actual observation and invalidate the derived 3D point."""
        if all(click.camera != camera for click in self.clicks):
            return self
        return dataclasses.replace(
            self,
            clicks=tuple(click for click in self.clicks if click.camera != camera),
            xyz=None,
            error_px=None,
            issue="need_two_calibrated_views",
        )

    def resolved(self, cameras: Mapping[str, CameraModel]) -> LadderPoint:
        """Triangulate available clicks, preserving every unavailable raw click."""
        views = [
            (cameras[click.camera], (click.x, click.y))
            for click in self.clicks
            if click.camera in cameras
        ]
        if len(views) < 2:
            return dataclasses.replace(
                self, xyz=None, error_px=None, issue="need_two_calibrated_views"
            )
        if not _rays_have_depth(views):
            return dataclasses.replace(self, xyz=None, error_px=None, issue="rays_parallel")
        xyz, error = triangulate(views)
        result: Point3 = (float(xyz[0]), float(xyz[1]), float(xyz[2]))
        if not _finite_point(result) or not math.isfinite(error):
            return dataclasses.replace(self, xyz=None, error_px=None, issue="invalid_solution")
        return dataclasses.replace(self, xyz=result, error_px=error, issue=None)


@dataclass(frozen=True)
class LadderStep:
    """One user-defined foothold, rung, or outline, in the user's order.

    One point draws a foothold; two draw a rung/edge; more draw only the
    segments between explicitly clicked points. ``closed`` joins the last to
    the first for an outline the user declared, never for an inferred step.
    """

    step_id: str
    label: str
    points: tuple[LadderPoint, ...]
    closed: bool = False

    def __post_init__(self) -> None:
        if not self.step_id or not self.label or not self.points:
            raise PropModelError("A ladder step needs an id, label, and clicked point.")
        if self.closed and len(self.points) < 3:
            raise PropModelError("A closed step outline needs at least three points.")

    def resolved(self, cameras: Mapping[str, CameraModel]) -> LadderStep:
        """Resolve each point independently; no neighbouring step moves."""
        return dataclasses.replace(
            self, points=tuple(point.resolved(cameras) for point in self.points)
        )


@dataclass(frozen=True)
class Ladder:
    """A static ordered collection of exactly the steps the user placed."""

    name: str
    steps: tuple[LadderStep, ...] = ()
    calibration: str = ""
    units: str = ""

    def __post_init__(self) -> None:
        ids = [step.step_id for step in self.steps]
        if not self.name or len(ids) != len(set(ids)):
            raise PropModelError("A ladder needs a name and unique step ids.")

    def with_step(self, step: LadderStep, position: int | None = None) -> Ladder:
        """Replace a step in place, or insert a newly clicked step."""
        if any(item.step_id == step.step_id for item in self.steps):
            steps = tuple(step if item.step_id == step.step_id else item for item in self.steps)
        else:
            at = len(self.steps) if position is None else position
            if not 0 <= at <= len(self.steps):
                raise PropModelError("A step position must be within the ladder's order.")
            steps = (*self.steps[:at], step, *self.steps[at:])
        return dataclasses.replace(self, steps=steps)

    def without_step(self, step_id: str) -> Ladder:
        """Remove one step without regenerating any others."""
        return dataclasses.replace(
            self, steps=tuple(step for step in self.steps if step.step_id != step_id)
        )

    def reordered(self, step_ids: Sequence[str]) -> Ladder:
        """Change presentation order without altering a click or 3D point."""
        ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(ids) or set(step_ids) != set(ids):
            raise PropModelError("Step order must contain each existing step exactly once.")
        by_id = {step.step_id: step for step in self.steps}
        return dataclasses.replace(self, steps=tuple(by_id[key] for key in step_ids))


class PropStore:
    """Accepted new props in one session; currently the user-clicked ladders.

    Observers hear a name, or None for a bulk load. Mutations are in memory;
    persistence belongs to the document's mutation target, never an observer.
    """

    def __init__(self) -> None:
        self._props: dict[str, Ladder] = {}
        self._observers: list[Callable[[str | None], None]] = []

    def __len__(self) -> int:
        return len(self._props)

    def __iter__(self) -> Iterator[Ladder]:
        return iter(list(self._props.values()))

    def get(self, name: str) -> Ladder | None:
        """The accepted ladder called *name*, if any."""
        return self._props.get(name)

    def set(self, name: str, ladder: Ladder | None) -> bool:
        """Set or remove one prop; report whether its stored value changed."""
        if ladder is not None and ladder.name != name:
            raise PropModelError("A prop's stored key must match its name.")
        if self._props.get(name) == ladder:
            return False
        if ladder is None:
            self._props.pop(name, None)
        else:
            self._props[name] = ladder
        self._notify(name)
        return True

    def set_step(
        self, name: str, step_id: str, step: LadderStep | None, position: int | None = None
    ) -> bool:
        """Edit one step, retaining every other step by identity and value."""
        ladder = self.get(name)
        if ladder is None:
            raise PropModelError("A step needs an existing ladder.")
        if step is not None and step.step_id != step_id:
            raise PropModelError("A step's stored key must match its id.")
        changed = ladder.without_step(step_id) if step is None else ladder.with_step(step, position)
        return self.set(name, changed)

    def move_step(self, name: str, step_id: str, position: int) -> bool:
        """Move one step without reconstructing or editing its observations."""
        ladder = self.get(name)
        if ladder is None:
            raise PropModelError("A step needs an existing ladder.")
        order = [step.step_id for step in ladder.steps]
        if step_id not in order or not 0 <= position < len(order):
            raise PropModelError("A step move needs an existing step and position.")
        order.insert(position, order.pop(order.index(step_id)))
        return self.set(name, ladder.reordered(order))

    def load(self, props: Iterable[Ladder]) -> None:
        """Replace session props with records read from disk."""
        self._props = {prop.name: prop for prop in props}
        self._notify(None)

    def clear(self) -> None:
        """Forget every prop for a new session."""
        if self._props:
            self._props.clear()
            self._notify(None)

    def observe(self, callback: Callable[[str | None], None]) -> Callable[[], None]:
        """Register a change listener and return its disposer."""
        self._observers.append(callback)

        def dispose() -> None:
            if callback in self._observers:
                self._observers.remove(callback)

        return dispose

    def _notify(self, name: str | None) -> None:
        for callback in list(self._observers):
            callback(name)


@dataclass(frozen=True)
class BeltTrack:
    """Fixed path followed by a moving material mark, in world-length units.

    An open path loses a mark when it leaves the observed span. Only an
    explicitly closed path wraps; no unmeasured return route is invented.
    """

    vertices: tuple[Point3, ...]
    closed: bool = False

    def __post_init__(self) -> None:
        if len(self.vertices) < (3 if self.closed else 2):
            raise PropModelError("A belt path needs at least two, or three closed, points.")
        if any(not _finite_point(point) for point in self.vertices):
            raise PropModelError("A belt path needs finite 3D points.")
        if any(
            not math.isfinite(_distance(a, b)) or _distance(a, b) <= 0 for a, b in self._segments()
        ):
            raise PropModelError("A belt path cannot contain a zero-length segment.")

    def _segments(self) -> tuple[tuple[Point3, Point3], ...]:
        vertices = (*self.vertices, self.vertices[0]) if self.closed else self.vertices
        return tuple(zip(vertices, vertices[1:], strict=False))

    @property
    def length(self) -> float:
        """Measured length of the declared path, including its return if closed."""
        return sum(_distance(a, b) for a, b in self._segments())

    def material_point(self, reference_distance: float, travel: float) -> Point3 | None:
        """World location of a surface mark after signed material travel.

        ``None`` means it left an open path. The fixed vertices never move.
        """
        if not all(map(math.isfinite, (reference_distance, travel))):
            raise PropModelError("Belt position and travel must be finite distances.")
        distance = reference_distance + travel
        length = self.length
        if self.closed:
            distance %= length
        elif distance < 0 or distance > length:
            return None
        for start, end in self._segments():
            span = _distance(start, end)
            if distance <= span:
                fraction = distance / span
                return _interpolate(start, end, fraction)
            distance -= span
        return self.vertices[0] if self.closed else self.vertices[-1]


@dataclass(frozen=True)
class UnitQuaternion:
    """A unit quaternion rotating a ball's local surface directions in 3D."""

    w: float
    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        values = (self.w, self.x, self.y, self.z)
        if not all(map(math.isfinite, values)):
            raise PropModelError("Ball orientation needs finite quaternion components.")
        norm = math.hypot(*values)
        if norm < 1e-12:
            raise PropModelError("Ball orientation cannot be a zero quaternion.")
        for name, value in zip(("w", "x", "y", "z"), values, strict=True):
            object.__setattr__(self, name, value / norm)

    @classmethod
    def identity(cls) -> UnitQuaternion:
        """Orientation of the reference frame."""
        return cls(1.0, 0.0, 0.0, 0.0)

    @classmethod
    def about_axis(cls, axis: Point3, radians: float) -> UnitQuaternion:
        """Right-handed rotation about a 3D axis by *radians*."""
        if not _finite_point(axis) or not math.isfinite(radians):
            raise PropModelError("Ball rotation needs a finite axis and angle.")
        norm = math.hypot(*axis)
        if norm < 1e-12:
            raise PropModelError("Ball rotation needs a nonzero axis.")
        scale = math.sin(radians / 2) / norm
        return cls(math.cos(radians / 2), *(value * scale for value in axis))

    def composed(self, other: UnitQuaternion) -> UnitQuaternion:
        """Apply *other* first, then this orientation (Hamilton product)."""
        a, b, c, d = self.w, self.x, self.y, self.z
        e, f, g, h = other.w, other.x, other.y, other.z
        return UnitQuaternion(
            a * e - b * f - c * g - d * h,
            a * f + b * e + c * h - d * g,
            a * g - b * h + c * e + d * f,
            a * h + b * g - c * f + d * e,
        )

    def rotate(self, point: Point3) -> Point3:
        """Rotate a vector without changing its length."""
        if not _finite_point(point):
            raise PropModelError("A ball surface direction must be finite.")
        vector = np.asarray(point, dtype=np.float64)
        axis = np.asarray((self.x, self.y, self.z), dtype=np.float64)
        cross = np.cross(axis, vector)
        rotated = vector + 2.0 * (self.w * cross + np.cross(axis, cross))
        return (float(rotated[0]), float(rotated[1]), float(rotated[2]))


@dataclass(frozen=True)
class BallSurface:
    """A fixed sphere whose explicitly identified material directions rotate."""

    centre: Point3
    radius: float

    def __post_init__(self) -> None:
        if not _finite_point(self.centre) or not math.isfinite(self.radius) or self.radius <= 0:
            raise PropModelError("A ball needs a finite centre and positive radius.")

    def material_point(self, local_direction: Point3, orientation: UnitQuaternion) -> Point3:
        """Locate a marked surface direction under measured orientation."""
        if not _finite_point(local_direction) or not math.isclose(
            math.hypot(*local_direction), 1.0, abs_tol=1e-6
        ):
            raise PropModelError("A ball surface direction must have unit length.")
        direction = orientation.rotate(local_direction)
        return (
            self.centre[0] + self.radius * direction[0],
            self.centre[1] + self.radius * direction[1],
            self.centre[2] + self.radius * direction[2],
        )


@dataclass(frozen=True)
class WheelMaterialMap:
    """Use the existing wheel geometry as the wheel's material-point map."""

    geometry: WheelGeometry

    def bar_ends(self, turn_degrees: float) -> np.ndarray:
        """All bar endpoints under an observed axial turn, in display order."""
        if not math.isfinite(turn_degrees):
            raise PropModelError("Wheel turn must be finite degrees.")
        return self.geometry.bar_ends(turn_degrees)
