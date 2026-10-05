"""Evidence-preserving geometry and material motion for physical props (D-149).

The fixed apparatus and its moving material are different things. A belt's
support stays put while a mark on its surface travels; a ball's centre stays
put while a local surface direction rotates. A ladder records each clicked
step independently, without a generated pitch or level. The wheel owns its fit;
the shared prop store owns every accepted apparatus. :class:`WheelMaterialMap`
adapts its proven bar geometry to the same material-point vocabulary.

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

from avialsync.core.belt_rollers import BeltRollers, BeltSideView
from avialsync.core.calibration import CameraModel, triangulate
from avialsync.core.errors import PropModelError
from avialsync.core.wheel import Wheel, WheelGeometry

__all__ = [
    "Point3",
    "StepClick",
    "LadderPointIssue",
    "LadderSupport",
    "StepIrregularity",
    "LADDER_SUPPORTS",
    "STEP_IRREGULARITIES",
    "LadderPoint",
    "LadderStep",
    "Ladder",
    "BeltProp",
    "BallProp",
    "BeltVisualFrame",
    "BallVisualFrame",
    "BeltSideView",
    "RungPattern",
    "LadderLayout",
    "BeltBinding",
    "BallBinding",
    "MotionCheck",
    "PhysicalProp",
    "PropStore",
    "WheelView",
    "BeltTrack",
    "BeltRollers",
    "UnitQuaternion",
    "BallSurface",
    "WheelMaterialMap",
]

Point3 = tuple[float, float, float]
LadderPointIssue = Literal["need_two_calibrated_views", "rays_parallel", "invalid_solution"]
LadderSupport = Literal["none", "side_rails", "centre_beam"]
"""How the rungs are held: no drawn support, a rail through each rung end, or one central beam."""
StepIrregularity = Literal["", "missing", "raised", "lowered", "shifted", "other"]
"""A user's tag for a place where the walkway departs from its regular pattern."""
LADDER_SUPPORTS: tuple[LadderSupport, ...] = ("none", "side_rails", "centre_beam")
STEP_IRREGULARITIES: tuple[StepIrregularity, ...] = (
    "",
    "missing",
    "raised",
    "lowered",
    "shifted",
    "other",
)
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
    """Whether two distinct camera centres provide a useful stereo angle."""
    directions: list[np.ndarray] = []
    centres: list[np.ndarray] = []
    for camera, pixel in views:
        x, y = camera.normalise(np.asarray([pixel], dtype=np.float64))[0]
        inverse_rotation = camera.rotation_matrix().T
        direction = inverse_rotation @ np.asarray((x, y, 1.0))
        directions.append(direction / np.linalg.norm(direction))
        centres.append(-inverse_rotation @ camera.translation)
    threshold = math.sin(math.radians(_MIN_RAY_ANGLE_DEG))
    return any(
        float(np.linalg.norm(np.cross(a, b))) >= threshold
        and float(np.linalg.norm(centres[index] - centres[other]))
        > 1e-9
        * max(
            1.0,
            float(np.linalg.norm(centres[index])),
            float(np.linalg.norm(centres[other])),
        )
        for index, a in enumerate(directions)
        for other, b in enumerate(directions[index + 1 :], start=index + 1)
    )


def _in_front_of_views(
    xyz: np.ndarray, views: Sequence[tuple[CameraModel, tuple[float, float]]]
) -> bool:
    """A 3D fit behind a contributing lens is algebra, not visible geometry."""
    for camera, _pixel in views:
        depth = float((camera.rotation_matrix() @ xyz + camera.translation)[2])
        if not math.isfinite(depth) or depth <= 0.0:
            return False
    return True


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
        if not _in_front_of_views(xyz, views):
            return dataclasses.replace(self, xyz=None, error_px=None, issue="invalid_solution")
        return dataclasses.replace(self, xyz=result, error_px=error, issue=None)


@dataclass(frozen=True)
class LadderStep:
    """One user-defined foothold, rung, or outline, in the user's order.

    One point draws a foothold; two draw a rung/edge; more draw only the
    segments between explicitly clicked points. ``closed`` joins the last to
    the first for an outline the user declared, never for an inferred step.
    ``irregular`` is the user's tag for a missing, raised, lowered, or shifted
    place; the clicks remain the geometry either way.
    """

    step_id: str
    label: str
    points: tuple[LadderPoint, ...]
    closed: bool = False
    irregular: StepIrregularity = ""

    def __post_init__(self) -> None:
        if not self.step_id or not self.label or not self.points:
            raise PropModelError("A ladder step needs an id, label, and clicked point.")
        if self.irregular not in STEP_IRREGULARITIES:
            raise PropModelError("A ladder step has an unknown irregularity tag.")
        if self.closed and len(self.points) < 3:
            raise PropModelError("A closed step outline needs at least three points.")

    def resolved(self, cameras: Mapping[str, CameraModel]) -> LadderStep:
        """Resolve each point independently; no neighbouring step moves."""
        return dataclasses.replace(
            self, points=tuple(point.resolved(cameras) for point in self.points)
        )


@dataclass(frozen=True)
class RungPattern:
    """A regular run of rungs extrapolated from two clicked neighbours (D-165).

    ``first`` and ``second`` are the ids of two adjacent clicked rungs; their
    four ends fix the spacing. ``count`` is the number of rungs in the run,
    those two included. Extrapolated rungs are estimates: a clicked rung at the
    same place replaces one, and nothing extrapolated becomes a click.
    """

    first: str
    second: str
    count: int

    def __post_init__(self) -> None:
        if not self.first or not self.second or self.first == self.second:
            raise PropModelError("A rung pattern needs two different clicked rungs.")
        if type(self.count) is not int or not 2 <= self.count <= 10_000:
            raise PropModelError("A rung pattern needs between 2 and 10000 rungs.")


@dataclass(frozen=True)
class LadderLayout:
    """How a ladder's rungs are held and whether a regular run is extrapolated."""

    support: LadderSupport = "none"
    pattern: RungPattern | None = None


@dataclass(frozen=True)
class Ladder:
    """A static ordered collection of exactly the steps the user placed.

    ``support`` declares how the rungs are held. Its bars are drawn through the
    clicked rungs in the user's order; they never add, move, or space a rung.
    """

    name: str
    steps: tuple[LadderStep, ...] = ()
    calibration: str = ""
    units: str = ""
    support: LadderSupport = "none"
    pattern: RungPattern | None = None

    @property
    def layout(self) -> LadderLayout:
        """The support and rung pattern, as one undoable value."""
        return LadderLayout(self.support, self.pattern)

    def __post_init__(self) -> None:
        ids = [step.step_id for step in self.steps]
        if not self.name or len(ids) != len(set(ids)):
            raise PropModelError("A ladder needs a name and unique step ids.")
        if self.support not in LADDER_SUPPORTS:
            raise PropModelError("A ladder has an unknown support layout.")

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


@dataclass(frozen=True)
class BeltVisualFrame:
    """One identified belt mark observed on a reference camera frame."""

    frame: int
    point: LadderPoint = LadderPoint()
    lap: int | None = None

    def __post_init__(self) -> None:
        if self.frame < 0 or (self.lap is not None and type(self.lap) is not int):
            raise PropModelError("A belt visual frame needs a valid frame and lap count.")


@dataclass(frozen=True)
class BallVisualFrame:
    """Three identified surface landmarks observed on one reference camera frame."""

    frame: int
    marks: tuple[LadderPoint, LadderPoint, LadderPoint] = (
        LadderPoint(),
        LadderPoint(),
        LadderPoint(),
    )

    def __post_init__(self) -> None:
        if self.frame < 0 or len(self.marks) != 3:
            raise PropModelError("A ball visual frame needs three named landmarks.")


@dataclass(frozen=True)
class BeltProp:
    """A fixed belt support and optional measured surface displacement."""

    name: str
    track: BeltTrack
    units: str = ""
    travel_direction: Point3 | None = None
    binding: BeltBinding | None = None
    visual_reference_frame: int | None = None
    visual_frames: tuple[BeltVisualFrame, ...] = ()
    surface_width: float | None = None
    surface_normal: Point3 | None = None
    rollers: BeltRollers | None = None
    corners: tuple[LadderPoint, LadderPoint, LadderPoint, LadderPoint] | None = None
    """Raw clicks on the top run's four corners that placed the rollers in 3D."""
    side_view: BeltSideView | None = None
    """One camera's clicks that place the belt in that view's side plane instead."""

    def __post_init__(self) -> None:
        if not self.name:
            raise PropModelError("A belt needs a name.")
        if self.corners is not None and len(self.corners) != 4:
            raise PropModelError("A belt placement needs exactly four clicked corners.")
        if self.side_view is not None and (
            self.rollers is None or not BeltSideView.is_side_frame(self.rollers)
        ):
            raise PropModelError("A one-camera belt needs rollers in its side plane.")
        if self.units not in ("", "mm", "cm", "m"):
            raise PropModelError("A belt needs supported calibration units.")
        if (self.surface_width is None) != (self.surface_normal is None):
            raise PropModelError("A belt surface needs both a width and a normal.")
        if self.rollers is not None:
            if not self.track.closed:
                raise PropModelError("A two-roller belt needs a closed display path.")
            if self.surface_width != self.rollers.width or self.surface_normal is None:
                raise PropModelError("Belt roller width and top direction must match its surface.")
            normal = np.asarray(self.surface_normal, dtype=np.float64)
            normal /= np.linalg.norm(normal)
            if not np.allclose(normal, self.rollers.top_normal, atol=1e-6):
                raise PropModelError("Belt roller top direction must match its surface normal.")
        if self.surface_width is not None:
            if not math.isfinite(self.surface_width) or self.surface_width <= 0:
                raise PropModelError("A belt surface width must be positive and finite.")
            assert self.surface_normal is not None
            if not _finite_point(self.surface_normal):
                raise PropModelError("A belt surface normal must be finite.")
            normal = np.asarray(self.surface_normal, dtype=np.float64)
            norm = float(np.linalg.norm(normal))
            if norm < 1e-12:
                raise PropModelError("A belt surface normal must be nonzero.")
            normal /= norm
            object.__setattr__(self, "surface_normal", tuple(float(value) for value in normal))
            vertices = self.track.vertices
            pairs = zip(
                vertices if self.track.closed else vertices[:-1],
                (*vertices[1:], vertices[0]) if self.track.closed else vertices[1:],
                strict=True,
            )
            if self.rollers is None and any(
                np.linalg.norm(np.cross(normal, np.asarray(end) - np.asarray(start))) < 1e-9
                for start, end in pairs
            ):
                raise PropModelError("A belt surface normal cannot follow a path segment.")
        if self.travel_direction is not None:
            if not _finite_point(self.travel_direction):
                raise PropModelError("A belt travel direction must be finite.")
            norm = math.hypot(*self.travel_direction)
            if norm < 1e-12:
                raise PropModelError("A belt travel direction must be nonzero.")
            object.__setattr__(
                self, "travel_direction", tuple(value / norm for value in self.travel_direction)
            )
        if (self.binding is not None or self.visual_frames) and self.travel_direction is None:
            raise PropModelError("A moving belt needs a declared travel direction.")
        if self.binding is not None and self.visual_frames:
            raise PropModelError("A belt has one motion source at a time.")
        frames = [item.frame for item in self.visual_frames]
        if len(frames) != len(set(frames)) or (
            frames and self.visual_reference_frame not in frames
        ):
            raise PropModelError("Belt visual frames need a unique observed reference.")
        if self.visual_reference_frame is not None and self.visual_reference_frame < 0:
            raise PropModelError("A belt reference frame cannot be negative.")
        if self.binding is not None or self.visual_frames:
            tangent = tuple(
                b - a for a, b in zip(self.track.vertices[0], self.track.vertices[1], strict=True)
            )
            assert self.travel_direction is not None
            alignment = sum(a * b for a, b in zip(tangent, self.travel_direction, strict=True))
            if abs(alignment) < 1e-9 * math.hypot(*tangent):
                raise PropModelError("Belt direction must follow the first path segment.")
            if self.binding is not None and not (
                0 <= self.binding.reference_distance <= self.path_length
            ):
                raise PropModelError("Belt mark must begin on the declared path.")

    def material_point(
        self, reading: float, reference_reading: float | None = None
    ) -> Point3 | None:
        """Locate the mark, optionally rereading the reference through today's TimeMap."""
        if self.binding is None:
            return None
        tangent = tuple(
            b - a for a, b in zip(self.track.vertices[0], self.track.vertices[1], strict=True)
        )
        assert self.travel_direction is not None
        alignment = sum(a * b for a, b in zip(tangent, self.travel_direction, strict=True))
        if abs(alignment) < 1e-9 * math.hypot(*tangent):
            raise PropModelError("Belt direction must follow the first path segment.")
        signed = math.copysign(1.0, alignment) * self.binding.units_per_reading
        origin = self.binding.reference_reading if reference_reading is None else reference_reading
        travel = signed * (reading - origin)
        if self.rollers is not None:
            return self.rollers.point_at(self.binding.reference_distance + travel)
        return self.track.material_point(self.binding.reference_distance, travel)

    @property
    def path_length(self) -> float:
        """Exact roller loop length, or the length of a legacy declared path."""
        return self.rollers.length if self.rollers is not None else self.track.length

    def surface_quads(self) -> tuple[tuple[Point3, Point3, Point3, Point3], ...]:
        """Measured ribbon faces around the path; empty without width or a 3D placement."""
        if self.surface_width is None or self.surface_normal is None or self.side_view:
            return ()
        if self.rollers is not None:
            return self.rollers.surface_quads()
        normal = np.asarray(self.surface_normal, dtype=np.float64)
        vertices = self.track.vertices
        pairs = zip(
            vertices if self.track.closed else vertices[:-1],
            (*vertices[1:], vertices[0]) if self.track.closed else vertices[1:],
            strict=True,
        )

        def point(values: np.ndarray) -> Point3:
            return (float(values[0]), float(values[1]), float(values[2]))

        quads: list[tuple[Point3, Point3, Point3, Point3]] = []
        for start, end in pairs:
            a, b = np.asarray(start), np.asarray(end)
            lateral = np.cross(normal, b - a)
            lateral *= self.surface_width / (2.0 * np.linalg.norm(lateral))
            quads.append(
                (
                    point(a - lateral),
                    point(a + lateral),
                    point(b + lateral),
                    point(b - lateral),
                )
            )
        return tuple(quads)


@dataclass(frozen=True)
class BallProp:
    """A fixed sphere and marks identified in the reference frame's world axes."""

    name: str
    surface: BallSurface
    units: str = ""
    surface_marks: tuple[Point3, ...] = ()
    binding: BallBinding | None = None
    visual_reference_frame: int | None = None
    visual_frames: tuple[BallVisualFrame, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise PropModelError("A ball needs a name.")
        if self.units not in ("", "mm", "cm", "m"):
            raise PropModelError("A ball needs supported calibration units.")
        if any(
            not _finite_point(mark) or not math.isclose(math.hypot(*mark), 1.0, abs_tol=1e-6)
            for mark in self.surface_marks
        ):
            raise PropModelError("Ball surface marks must be finite unit directions.")
        if self.binding is not None and not self.surface_marks:
            raise PropModelError("A rotating ball needs an identified surface mark.")
        if self.binding is not None and self.visual_frames:
            raise PropModelError("A ball has one motion source at a time.")
        frames = [item.frame for item in self.visual_frames]
        if len(frames) != len(set(frames)) or (
            frames and self.visual_reference_frame not in frames
        ):
            raise PropModelError("Ball visual frames need a unique observed reference.")
        if self.visual_reference_frame is not None and self.visual_reference_frame < 0:
            raise PropModelError("A ball reference frame cannot be negative.")

    def material_point(
        self, orientation: UnitQuaternion, reference_orientation: UnitQuaternion | None = None
    ) -> Point3 | None:
        """Rotate the reference mark by live relative orientation."""
        if self.binding is None or not self.surface_marks:
            return None
        reference = (
            self.binding.reference_orientation
            if reference_orientation is None
            else reference_orientation
        )
        relative = orientation.composed(reference.inverse())
        return self.surface.material_point(self.surface_marks[0], relative)


@dataclass(frozen=True)
class MotionCheck:
    """One actual later-frame click and its residual from a predicted mark."""

    frame: int
    camera: str
    x: float
    y: float
    residual_px: float
    source_values: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.frame < 0
            or not self.camera
            or not all(math.isfinite(value) for value in (self.x, self.y, self.residual_px))
            or self.residual_px < 0
        ):
            raise PropModelError("A motion check needs a frame, camera, pixels, and residual.")
        if not all(math.isfinite(value) for value in self.source_values):
            raise PropModelError("A motion check needs finite source readings.")


@dataclass(frozen=True)
class BeltBinding:
    """Signed displacement evidence for one identified belt surface mark."""

    source_id: str
    channel: str
    reference_frame: int
    reference_reading: float
    reference_distance: float
    units_per_reading: float
    checks: tuple[MotionCheck, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_id or not self.channel or self.reference_frame < 0:
            raise PropModelError("A belt binding needs a channel and reference frame.")
        if (
            not all(
                math.isfinite(value)
                for value in (
                    self.reference_reading,
                    self.reference_distance,
                    self.units_per_reading,
                )
            )
            or self.units_per_reading <= 0
        ):
            raise PropModelError("A belt binding needs finite reference and positive scale.")


@dataclass(frozen=True)
class BallBinding:
    """Four synchronized orientation channels and a measured reference sample."""

    source_id: str
    channels: tuple[str, str, str, str]
    reference_frame: int
    reference_orientation: UnitQuaternion
    checks: tuple[MotionCheck, ...] = ()
    reference_values: tuple[float, float, float, float] | None = None

    def __post_init__(self) -> None:
        if (
            not self.source_id
            or self.reference_frame < 0
            or len(self.channels) != 4
            or (len(set(self.channels)) != 4 or not all(self.channels))
        ):
            raise PropModelError("Ball orientation needs four distinct channels from one source.")
        if self.reference_values is not None and not all(
            math.isfinite(value) for value in self.reference_values
        ):
            raise PropModelError("Ball reference readings must be finite.")


PhysicalProp = Ladder | BeltProp | BallProp | Wheel


class PropStore:
    """Accepted props of every kind in one session, keyed by distinct names.

    Observers hear a name, or None for a bulk load. Mutations are in memory;
    persistence belongs to the document's mutation target, never an observer.
    """

    def __init__(self) -> None:
        self._props: dict[str, PhysicalProp] = {}
        self._observers: list[Callable[[str | None], None]] = []

    def __len__(self) -> int:
        return len(self._props)

    def __iter__(self) -> Iterator[PhysicalProp]:
        return iter(list(self._props.values()))

    def get(self, name: str) -> PhysicalProp | None:
        """The accepted prop called *name*, if any."""
        return self._props.get(name)

    def names(self) -> set[str]:
        """Return the names reserved by every accepted prop kind."""
        return set(self._props)

    def set(self, name: str, prop: PhysicalProp | None) -> bool:
        """Set or remove one prop; report whether its stored value changed."""
        if prop is not None and prop.name != name:
            raise PropModelError("A prop's stored key must match its name.")
        if prop is not None and any(
            used != name and used.casefold() == name.casefold() for used in self._props
        ):
            raise PropModelError("A prop name already belongs to another record.")
        previous = self._props.get(name)
        if previous is not None and prop is not None and type(previous) is not type(prop):
            raise PropModelError("A prop name already belongs to a different kind.")
        if self._props.get(name) == prop:
            return False
        if prop is None:
            self._props.pop(name, None)
        else:
            self._props[name] = prop
        self._notify(name)
        return True

    def set_layout(self, name: str, layout: LadderLayout) -> bool:
        """Change a ladder's support and rung pattern; every click is kept."""
        prop = self.get(name)
        if not isinstance(prop, Ladder):
            raise PropModelError("A ladder layout needs an existing ladder.")
        return self.set(
            name, dataclasses.replace(prop, support=layout.support, pattern=layout.pattern)
        )

    def set_step(
        self, name: str, step_id: str, step: LadderStep | None, position: int | None = None
    ) -> bool:
        """Edit one step, retaining every other step by identity and value."""
        prop = self.get(name)
        if not isinstance(prop, Ladder):
            raise PropModelError("A step needs an existing ladder.")
        if step is not None and step.step_id != step_id:
            raise PropModelError("A step's stored key must match its id.")
        changed = prop.without_step(step_id) if step is None else prop.with_step(step, position)
        return self.set(name, changed)

    def move_step(self, name: str, step_id: str, position: int) -> bool:
        """Move one step without reconstructing or editing its observations."""
        prop = self.get(name)
        if not isinstance(prop, Ladder):
            raise PropModelError("A step needs an existing ladder.")
        order = [step.step_id for step in prop.steps]
        if step_id not in order or not 0 <= position < len(order):
            raise PropModelError("A step move needs an existing step and position.")
        order.insert(position, order.pop(order.index(step_id)))
        return self.set(name, prop.reordered(order))

    def load(self, props: Iterable[PhysicalProp]) -> None:
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


class WheelView:
    """Wheel-specific view of the shared prop store for fitting and drawing."""

    def __init__(self, store: PropStore) -> None:
        self._store = store
        self._observers: list[Callable[[str | None], None]] = []
        self._names: set[str] = set()
        store.observe(self._changed)

    def __len__(self) -> int:
        return len(self.names())

    def __iter__(self) -> Iterator[Wheel]:
        return (prop for prop in self._store if isinstance(prop, Wheel))

    def get(self, name: str) -> Wheel | None:
        """Return a wheel by name, if the shared record is a wheel."""
        prop = self._store.get(name)
        return prop if isinstance(prop, Wheel) else None

    def names(self) -> set[str]:
        """Return the names of accepted wheels."""
        return {wheel.name for wheel in self}

    def set(self, name: str, wheel: Wheel | None) -> bool:
        """Change a wheel through the shared store."""
        if wheel is None and self.get(name) is None:
            return False
        return self._store.set(name, wheel)

    def load(self, wheels: Iterable[Wheel]) -> None:
        """Replace wheels while preserving other kinds in the shared store."""
        others = (prop for prop in self._store if not isinstance(prop, Wheel))
        self._store.load((*others, *wheels))

    def clear(self) -> None:
        """Forget wheels while preserving the other props."""
        if self._names:
            self.load(())

    def observe(self, callback: Callable[[str | None], None]) -> Callable[[], None]:
        """Observe wheel changes through the shared store."""
        self._observers.append(callback)

        def dispose() -> None:
            if callback in self._observers:
                self._observers.remove(callback)

        return dispose

    def _changed(self, name: str | None) -> None:
        old_names = self._names
        self._names = self.names()
        if name is None or name in old_names or name in self._names:
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

    def inverse(self) -> UnitQuaternion:
        """Inverse rotation of a unit quaternion."""
        return UnitQuaternion(self.w, -self.x, -self.y, -self.z)

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
