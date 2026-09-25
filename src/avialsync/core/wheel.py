"""A running wheel, generated from a few clicked bars and turned by an encoder.

A wheel's bars are too many to click and mostly out of shot, but they are
identical and evenly spaced, so a few of them fix the rest. The user clicks both
ends of two or three **neighbouring** bars on one frame, in every camera that
sees them; each end is triangulated through the rig's calibration
(:mod:`avialsync.core.calibration`), and the wheel is fitted to those clicks
(D-113).

**What the clicks determine, and what they cannot.** Every bar is parallel to
the axle, so the bars' own directions give the axle directly, and their lengths
give the distance between the side plates. The radius is the weak part: two or
three neighbouring bars span a short arc, and its curvature -- a millimetre or
two of bow over a 10 cm wheel -- is about the size of the click error. So the
**bar count is an input**: with it, the gap between two neighbouring bars gives
the radius as ``gap / (2 sin(pi / N))``, which the same click error moves by a
few percent rather than tens. A radius the user measured on the rig makes the
fit over-determined, and the radius the clicks imply is reported beside it so a
units slip or a miscounted wheel shows up as a number rather than as a wheel
drawn at the wrong size.

**Two wheels fit two bars.** The centre may sit on either side of the chord
between them. The fit refines both, keeps the one that reprojects better, and
when the two are too close to call prefers the one farther from the cameras --
the bars a camera sees face it. :attr:`WheelFit.can_flip` says whether the
other exists, so the user can choose it from the preview.

**The fit is in pixels.** The starting geometry comes from the triangulated
ends; the refinement then moves the whole wheel so every generated bar end lands
on its click in every camera, the error anipose users already read.

Headless (architecture rule 2). The model is here; fitting it is
:mod:`avialsync.core.wheel_fit`, checking the encoder that turns it is
:mod:`avialsync.core.wheel_check`, and its file is :mod:`avialsync.core.wheel_file`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

import numpy as np

from avialsync.core.calibration import CameraModel

__all__ = [
    "LEFT",
    "RIGHT",
    "SIDES",
    "UNITS",
    "MIN_BAR_COUNT",
    "WheelSpec",
    "EndClick",
    "WheelGeometry",
    "ClickResidual",
    "WheelFit",
    "WheelCheck",
    "EncoderBinding",
    "Wheel",
    "WheelStore",
    "camera_centre",
    "facing",
    "project_bars",
]

LEFT = "left"
RIGHT = "right"
#: A bar's two ends, in the order the user is asked to click them.
SIDES = (LEFT, RIGHT)
#: Units a calibration's 3D coordinates may be declared in; "" is "not known".
UNITS = ("mm", "cm", "m")
#: Fewer bars than this is not a wheel.
MIN_BAR_COUNT = 3

#: A bar whose outward direction points further than this away from a camera is
#: behind the side plate or under a nearer bar, as that camera sees it.
_FACING_LIMIT = -0.2


@dataclass(frozen=True)
class WheelSpec:
    """What the user declares about a wheel before clicking it.

    ``radius`` is to the bars' centre lines, in ``units`` -- the units the
    calibration's 3D coordinates are in. It is used only when both are known:
    a radius in centimetres against a calibration in millimetres is a wheel a
    tenth the size, drawn without complaint.
    """

    name: str
    bar_count: int
    radius: float | None = None
    units: str = ""

    @property
    def pitch(self) -> float:
        """Degrees between neighbouring bars."""
        return 360.0 / self.bar_count

    @property
    def known_radius(self) -> float | None:
        """The radius to fit with, or None when it cannot be trusted."""
        if self.radius is None or self.radius <= 0 or self.units not in UNITS:
            return None
        return float(self.radius)


@dataclass(frozen=True)
class EndClick:
    """One end of one clicked bar, as clicked in each camera.

    ``bar`` is the click order (0, 1, 2 ...) of neighbouring bars, not their
    place round the wheel, which the fit works out.
    """

    bar: int
    side: str
    views: tuple[tuple[str, float, float], ...] = ()

    def with_view(self, camera: str, x: float, y: float) -> EndClick:
        """A copy clicked at *(x, y)* in *camera*, replacing any earlier click there."""
        views = {name: (vx, vy) for name, vx, vy in self.views}
        views[camera] = (float(x), float(y))
        return dataclasses.replace(
            self, views=tuple((name, *views[name]) for name in sorted(views))
        )

    def without_view(self, camera: str) -> EndClick:
        """A copy with *camera*'s click removed."""
        return dataclasses.replace(
            self, views=tuple(view for view in self.views if view[0] != camera)
        )


@dataclass(frozen=True)
class WheelGeometry:
    """Where the wheel is, in the calibration's world frame.

    ``axle`` points from the left plate to the right one; ``zero`` is the
    direction from the axle to bar 0 -- the first bar clicked -- on the frame it
    was clicked on. A turn is right-handed about ``axle``.
    """

    centre: tuple[float, float, float]
    axle: tuple[float, float, float]
    zero: tuple[float, float, float]
    radius: float
    half_width: float
    bar_count: int

    def basis(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(x, y, z)``: bar 0's direction, a quarter turn on, and the axle."""
        z = np.asarray(self.axle, dtype=np.float64)
        x = np.asarray(self.zero, dtype=np.float64)
        return x, np.cross(z, x), z

    def bar_ends(self, turn: float = 0.0) -> np.ndarray:
        """``(N, 2, 3)``: both ends of every bar, the wheel turned by *turn* degrees."""
        x, y, z = self.basis()
        angles = np.radians(turn + np.arange(self.bar_count) * 360.0 / self.bar_count)
        radial = np.cos(angles)[:, None] * x + np.sin(angles)[:, None] * y
        rim = np.asarray(self.centre, dtype=np.float64) + self.radius * radial
        offset = self.half_width * z
        ends: np.ndarray = np.stack((rim - offset, rim + offset), axis=1)
        return ends


@dataclass(frozen=True)
class ClickResidual:
    """How far one click is from the fitted wheel, in that camera's pixels."""

    bar: int
    side: str
    camera: str
    pixels: float


@dataclass(frozen=True)
class WheelFit:
    """A fitted wheel and the evidence for it, as the review panel shows it."""

    geometry: WheelGeometry
    #: Where each clicked bar sits round the wheel, in click order.
    indices: tuple[int, ...]
    residuals: tuple[ClickResidual, ...]
    #: Per clicked bar, how far (degrees) its triangulated position sits from its slot.
    spacing_deg: tuple[float, ...]
    #: Per clicked bar, the angle (degrees) between it and the fitted axle.
    parallel_deg: tuple[float, ...]
    #: The radius the clicks alone give, when a radius was supplied.
    implied_radius: float | None = None
    #: The mirrored wheel fits nearly as well; the preview should be checked.
    ambiguous: bool = False
    #: A mirrored wheel exists at all, so Flip has something to show.
    can_flip: bool = False

    @property
    def median_px(self) -> float:
        """Median click error in pixels."""
        return float(np.median([r.pixels for r in self.residuals])) if self.residuals else 0.0

    @property
    def max_px(self) -> float:
        """Largest click error in pixels."""
        return max((r.pixels for r in self.residuals), default=0.0)

    @property
    def skipped(self) -> bool:
        """The clicked bars are not neighbours: one or more were stepped over."""
        ordered = sorted(self.indices)
        return any(b - a != 1 for a, b in zip(ordered, ordered[1:], strict=False))


@dataclass(frozen=True)
class WheelCheck:
    """A bar end clicked on another frame, to test the encoder against the video."""

    frame: int
    encoder_angle: float
    camera: str
    x: float
    y: float


@dataclass(frozen=True)
class EncoderBinding:
    """The channel that turns the wheel, and how.

    ``reference_angle`` is the encoder's reading on the frame the wheel was
    clicked on, where the wheel's turn is zero by definition. ``measured`` is
    True only once :func:`~avialsync.core.wheel_check.settle_sign` found the
    direction from checks; until then the direction is an assumption and is
    labelled as one.
    """

    source_id: str
    channel: str
    reference_angle: float
    sign: float = 1.0
    ratio: float = 1.0
    measured: bool = False
    checks: tuple[WheelCheck, ...] = ()

    def turn(self, encoder_angle: float) -> float:
        """Degrees the wheel has turned since the reference frame."""
        return self.sign * self.ratio * (float(encoder_angle) - self.reference_angle)


@dataclass(frozen=True)
class Wheel:
    """One wheel: what was declared, what was clicked, and what was fitted."""

    spec: WheelSpec
    #: The frame the bars were clicked on.
    frame: int
    clicks: tuple[EndClick, ...]
    fit: WheelFit
    flipped: bool = False
    binding: EncoderBinding | None = None
    #: The calibration file the clicks were triangulated with.
    calibration: str = ""

    @property
    def name(self) -> str:
        """The wheel's name, which its file is named after."""
        return self.spec.name

    @property
    def geometry(self) -> WheelGeometry:
        """The fitted geometry."""
        return self.fit.geometry


class WheelStore:
    """Every wheel in the session, keyed by name.

    Observers hear the name that changed, or None for a bulk load -- the
    contract of :class:`~avialsync.core.custom_markers.CustomMarkerStore`, and
    for the same reason: files are written from the mutation, not from here.
    """

    def __init__(self) -> None:
        self._wheels: dict[str, Wheel] = {}
        self._observers: list[Callable[[str | None], None]] = []

    def __len__(self) -> int:
        return len(self._wheels)

    def __iter__(self) -> Iterator[Wheel]:
        return iter(list(self._wheels.values()))

    def get(self, name: str) -> Wheel | None:
        """The wheel called *name*, or None."""
        return self._wheels.get(name)

    def names(self) -> set[str]:
        """Every wheel name in use."""
        return set(self._wheels)

    def set(self, name: str, wheel: Wheel | None) -> bool:
        """Store *wheel* under *name*, or remove it; whether anything changed."""
        if wheel is None:
            if name not in self._wheels:
                return False
            del self._wheels[name]
        else:
            if self._wheels.get(name) == wheel:
                return False
            self._wheels[name] = wheel
        self._notify(name)
        return True

    def load(self, wheels: Iterable[Wheel]) -> None:
        """Replace everything with *wheels*, as read back from disk."""
        self._wheels = {wheel.name: wheel for wheel in wheels}
        self._notify(None)

    def clear(self) -> None:
        """Forget every wheel (a new session)."""
        if self._wheels:
            self._wheels.clear()
            self._notify(None)

    def observe(self, callback: Callable[[str | None], None]) -> Callable[[], None]:
        """Call *callback* after every change; returns a disposer."""
        self._observers.append(callback)

        def _dispose() -> None:
            if callback in self._observers:
                self._observers.remove(callback)

        return _dispose

    def _notify(self, name: str | None) -> None:
        for callback in list(self._observers):
            callback(name)


# ── seeing the wheel from a camera ───────────────────────────────────


def camera_centre(camera: CameraModel) -> np.ndarray:
    """Where *camera* is, in world coordinates."""
    centre: np.ndarray = -camera.rotation_matrix().T @ camera.translation
    return centre


def facing(geometry: WheelGeometry, ends: np.ndarray, viewer: np.ndarray) -> np.ndarray:
    """``(N,)``: which bars face a camera at *viewer*, for ends from :meth:`bar_ends`."""
    _, _, axle = geometry.basis()
    mids = ends.mean(axis=1)
    radial = mids - np.asarray(geometry.centre)
    radial -= np.outer(radial @ axle, axle)
    towards = viewer - mids
    norms = np.linalg.norm(radial, axis=1) * np.linalg.norm(towards, axis=1)
    cosine = np.einsum("ij,ij->i", radial, towards) / np.where(norms > 0, norms, 1.0)
    visible: np.ndarray = cosine >= _FACING_LIMIT
    return visible


def project_bars(
    geometry: WheelGeometry, ends: np.ndarray, camera: CameraModel
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Project bar ends into *camera*.

    Returns ``(pixels (N, 2, 2), in_front (N,), facing (N,))``. A bar with an
    end behind the camera has no meaningful projection -- it lands mirrored in
    front -- so callers draw only ``in_front``; ``facing`` separates the bars
    the camera sees from the ones behind the plate.
    """
    flat = ends.reshape(-1, 3)
    depth = flat @ camera.rotation_matrix()[2] + camera.translation[2]
    in_front: np.ndarray = (depth > 0).reshape(-1, 2).all(axis=1)
    pixels = camera.project(flat).reshape(-1, 2, 2)
    return pixels, in_front, facing(geometry, ends, camera_centre(camera))
