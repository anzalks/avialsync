"""Support bars and extrapolated rungs of a ladder (D-164, D-165).

A horizontal ladder's rungs are held either by a rail through each rung end or
by one beam under their middles. Bars are drawn through the clicked rungs. A
regular run may also be extrapolated from two clicked neighbours: in one camera
image through the perspective map their four ends fix, so a single view is
enough; in 3D by repeating their spacing. Extrapolated rungs are estimates. A
clicked rung at the same place replaces one, and the bars then follow the rungs
along the walkway rather than in click order.

The same rules serve camera pixels and solved 3D points, so a caller passes one
position per clicked point, or None where that point is not known in its space.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from avialsync.core.errors import PropModelError
from avialsync.core.physical_props import LadderSupport
from avialsync.core.plane_view import PlaneView

__all__ = ["Position", "RungLayout", "lay_out_rungs", "rung_places", "support_bars"]

Position = tuple[float, ...]


def _midpoint(points: Sequence[Position | None]) -> Position | None:
    """A step's centre: the foothold, the rung's middle, or an outline's mean."""
    if not points or any(point is None for point in points):
        return None
    known = [point for point in points if point is not None]
    return tuple(sum(values) / len(known) for values in zip(*known, strict=True))


def _rails(steps: Sequence[Sequence[Position | None]]) -> tuple[tuple[Position | None, ...], ...]:
    """Join same-side ends of consecutive two-point rungs.

    Users click a rung's two ends in either order. Each rung is paired with the
    previous one so the rails do not cross: the pairing with the shorter total
    span wins. Where an end is unknown the rail has a gap rather than a guess.
    """
    first: list[Position | None] = []
    second: list[Position | None] = []
    for step in steps:
        if len(step) != 2:
            continue
        a, b = step
        left = first[-1] if first else None
        right = second[-1] if second else None
        if left is not None and right is not None and a is not None and b is not None:
            straight = math.dist(left, a) + math.dist(right, b)
            crossed = math.dist(left, b) + math.dist(right, a)
            if crossed < straight:
                a, b = b, a
        first.append(a)
        second.append(b)
    return tuple(rail for rail in (tuple(first), tuple(second)) if len(rail) >= 2)


def support_bars(
    steps: Sequence[Sequence[Position | None]], support: LadderSupport
) -> tuple[tuple[Position | None, ...], ...]:
    """Polylines for the declared support, with None marking a gap.

    *steps* holds each step's point positions in the ladder's order. Side rails
    use the two-point rungs only; a centre beam passes through the middle of
    every step, footholds included.
    """
    if support == "side_rails":
        return _rails(steps)
    if support == "centre_beam":
        beam = tuple(_midpoint(step) for step in steps)
        return (beam,) if len(beam) >= 2 else ()
    return ()


#: A clicked rung within this fraction of the spacing replaces an extrapolated one.
_SAME_RUNG = 0.3


class _Lattice:
    """Rung coordinates (``u`` along a rung, ``t`` in spacings) to one view."""

    def __init__(self, a0: Position, b0: Position, a1: Position, b1: Position) -> None:
        self._image: PlaneView | None = None
        if len(a0) == 2:
            self._image = PlaneView(
                ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)),
                ((a0[0], a0[1]), (b0[0], b0[1]), (a1[0], a1[1]), (b1[0], b1[1])),
            )
        self._origin = np.asarray(a0, dtype=np.float64)
        self._across = np.asarray(b0, dtype=np.float64) - self._origin
        # The mean of both rails' steps, so a slightly skewed click averages out.
        self._pitch = (
            np.asarray(a1, dtype=np.float64)
            - self._origin
            + np.asarray(b1, dtype=np.float64)
            - np.asarray(b0, dtype=np.float64)
        ) / 2.0
        if float(self._pitch @ self._pitch) < 1e-18:
            raise PropModelError("The two pattern rungs must be apart.")

    def point(self, u: float, t: float) -> Position | None:
        if self._image is not None:
            return self._image.pixel(u, t)
        return tuple(float(value) for value in self._origin + u * self._across + t * self._pitch)

    def spacing(self, position: Position) -> float | None:
        if self._image is not None:
            plane = self._image.plane(position[0], position[1])
            return None if plane is None else plane[1]
        relative = np.asarray(position, dtype=np.float64) - self._origin
        return float(relative @ self._pitch / (self._pitch @ self._pitch))


@dataclass(frozen=True)
class RungLayout:
    """Extrapolated rungs and the walkway order support bars follow.

    ``generated`` holds each extrapolated rung's number in the run (1 is the
    first pattern rung) and its two ends. ``walkway`` lists every rung's points
    in the order bars join them.
    """

    generated: tuple[tuple[int, tuple[Position | None, Position | None]], ...]
    walkway: tuple[tuple[Position | None, ...], ...]


def _pair(
    previous: tuple[Position, Position], ends: Sequence[Position | None]
) -> tuple[Position | None, Position | None]:
    a, b = ends[0], ends[1]
    if a is not None and b is not None:
        straight = math.dist(previous[0], a) + math.dist(previous[1], b)
        if math.dist(previous[0], b) + math.dist(previous[1], a) < straight:
            return b, a
    return a, b


def _lattice(
    steps: Sequence[Sequence[Position | None]], pattern: tuple[int, int, int]
) -> _Lattice | None:
    first, second, _count = pattern
    if not (0 <= first < len(steps) and 0 <= second < len(steps)):
        return None
    near, far = steps[first], steps[second]
    if len(near) != 2 or len(far) != 2 or None in (*near, *far):
        return None
    a0, b0 = near[0], near[1]
    assert a0 is not None and b0 is not None
    a1, b1 = _pair((a0, b0), far)
    assert a1 is not None and b1 is not None
    try:
        return _Lattice(a0, b0, a1, b1)
    except PropModelError:
        return None


def _place(lattice: _Lattice, step: Sequence[Position | None]) -> float | None:
    """Where a fully known step sits along the run, in rung spacings."""
    if not step or any(point is None for point in step):
        return None
    spacings = [lattice.spacing(point) for point in step if point is not None]
    if any(value is None for value in spacings):
        return None
    return sum(value for value in spacings if value is not None) / len(spacings)


def rung_places(
    steps: Sequence[Sequence[Position | None]], pattern: tuple[int, int, int] | None
) -> tuple[float | None, ...]:
    """Each step's place along the run, from positions where it is known.

    Computed from solved 3D points, this is the authority every camera uses:
    a raised rung's image is displaced from the plane of the pattern rungs, so
    reading its place from one image would misjudge which rung it is.
    """
    lattice = None if pattern is None else _lattice(steps, pattern)
    return tuple(None if lattice is None else _place(lattice, step) for step in steps)


def lay_out_rungs(
    steps: Sequence[Sequence[Position | None]],
    pattern: tuple[int, int, int] | None,
    places: Sequence[float | None] = (),
) -> RungLayout:
    """Extrapolate a regular run, if one is declared and visible in this space.

    *pattern* holds the indices of the two clicked neighbour rungs in *steps*
    and the number of rungs in the run. Without it, or when either rung's ends
    are unknown here, nothing is extrapolated and bars follow click order.
    *places* are steps' known places along the run from 3D (see
    :func:`rung_places`); a step without one is placed from these positions.
    """
    clicked = tuple(tuple(step) for step in steps)
    lattice = None if pattern is None else _lattice(steps, pattern)
    if pattern is None or lattice is None:
        return RungLayout((), clicked)
    count = pattern[2]
    placed: list[tuple[float, tuple[Position | None, ...]]] = []
    taken: list[float] = []
    for index, step in enumerate(steps):
        known = places[index] if index < len(places) else None
        where = known if known is not None else _place(lattice, step)
        if where is None:
            continue
        taken.append(where)
        if all(point is not None for point in step):
            placed.append((where, clicked[index]))
    generated: list[tuple[int, tuple[Position | None, Position | None]]] = []
    for number in range(2, count):
        if any(abs(where - number) < _SAME_RUNG for where in taken):
            continue
        ends = (lattice.point(0.0, float(number)), lattice.point(1.0, float(number)))
        generated.append((number + 1, ends))
        if None not in ends:
            placed.append((float(number), ends))
    placed.sort(key=lambda item: item[0])
    return RungLayout(tuple(generated), tuple(points for _where, points in placed))
