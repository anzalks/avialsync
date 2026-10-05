"""Camera and 3D drawings of ladder layouts and belt placement clicks (D-164, D-165).

Support bars and extrapolated rungs are drawn dashed in a camera: they are
estimates between clicks, never clicks. A belt's placement clicks are solid
where this camera clicked them and dashed where only their 3D position projects
here; a one-camera belt's profile appears only in its own view.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import numpy as np

from avialsync.core.calibration import CameraModel
from avialsync.core.ladder_support import (
    Position,
    RungLayout,
    lay_out_rungs,
    rung_places,
    support_bars,
)
from avialsync.core.physical_props import BeltProp, Ladder, LadderPoint, Point3
from avialsync.ui.belt_placement_controls import placement_point_label
from avialsync.ui.i18n import tr
from avialsync.ui.prop_overlay import UNNAMED, PropDrawing, PropPixel

__all__ = [
    "ladder_layout",
    "rung_pixels",
    "rung_positions",
    "placement_pixels",
    "placement_positions",
    "side_view_pixels",
]

Scene = list[tuple[str, tuple[np.ndarray | None, ...], bool]]


def _pattern(ladder: Ladder) -> tuple[int, int, int] | None:
    """The pattern's two rungs as indices into the ladder's steps."""
    pattern = ladder.pattern
    if pattern is None:
        return None
    ids = [step.step_id for step in ladder.steps]
    if pattern.first not in ids or pattern.second not in ids:
        return None
    return ids.index(pattern.first), ids.index(pattern.second), pattern.count


def ladder_layout(ladder: Ladder, steps: Sequence[Sequence[Position | None]]) -> RungLayout:
    """Extrapolated rungs and walkway order for one space's step positions.

    *ladder* is resolved, so a step solved in 3D is placed along the run from
    its 3D points in every camera, and a 2D-only step from this view.
    """
    pattern = _pattern(ladder)
    solved = [[point.xyz for point in step.points] for step in ladder.steps]
    return lay_out_rungs(steps, pattern, rung_places(solved, pattern))


def _rung_label(number: int) -> str:
    return tr("Rung {number} (est.)").format(number=number)


def rung_pixels(ladder: Ladder, step_pixels: Sequence[Sequence[PropPixel]]) -> list[PropDrawing]:
    """This camera's extrapolated rungs and support bars, all dashed."""
    layout = ladder_layout(
        ladder,
        [[None if p is None else (p[0], p[1]) for p in pixels] for pixels in step_pixels],
    )
    drawings: list[PropDrawing] = [
        (
            _rung_label(number),
            tuple(None if p is None else (p[0], p[1], False) for p in ends),
            False,
        )
        for number, ends in layout.generated
        if any(p is not None for p in ends)
    ]
    drawings.extend(
        ("", tuple(None if p is None else (p[0], p[1], False) for p in bar), False)
        for bar in support_bars(layout.walkway, ladder.support)
    )
    return drawings


def _array(point: Position | None) -> np.ndarray | None:
    return None if point is None else np.asarray(point, dtype=np.float64)


def rung_positions(ladder: Ladder) -> Scene:
    """Extrapolated rungs and support bars through a resolved ladder's 3D points."""
    layout = ladder_layout(ladder, [[point.xyz for point in step.points] for step in ladder.steps])
    scene: Scene = [
        (_rung_label(number), (_array(ends[0]), _array(ends[1])), False)
        for number, ends in layout.generated
        if None not in ends
    ]
    scene.extend(
        ("", tuple(_array(p) for p in bar), False)
        for bar in support_bars(layout.walkway, ladder.support)
    )
    return scene


def placement_pixels(
    points: Sequence[LadderPoint],
    camera: str,
    project: Callable[[Point3], PropPixel | None],
    mode: str,
    *,
    named: bool = True,
) -> list[PropDrawing]:
    """Each placement click as its own mark; 3D corners also outlined.

    While placing, each is named, so the next click is unambiguous. A saved
    belt keeps them as unnamed squares: evidence to inspect, not captions to read.
    """
    pixels: list[PropPixel] = []
    for point in points:
        click = next((item for item in point.clicks if item.camera == camera), None)
        if click is not None:
            pixels.append((click.x, click.y, True))
        elif point.xyz is not None:
            pixels.append(project(point.xyz))
        else:
            pixels.append(None)
    drawings: list[PropDrawing] = [
        (placement_point_label(mode, index) if named else UNNAMED, (pixel,), False)
        for index, pixel in enumerate(pixels)
        if pixel is not None
    ]
    if mode == "rollers" and len(pixels) == 4:
        # The top run's outline: near pair, then far pair in reverse.
        drawings.insert(0, ("", (pixels[0], pixels[1], pixels[3], pixels[2]), True))
    return drawings


def placement_positions(belt: BeltProp, cameras: Mapping[str, CameraModel]) -> Scene:
    """Solved top corners of a belt placed in 3D, outlined."""
    if belt.corners is None:
        return []
    solved = [corner.resolved(cameras).xyz for corner in belt.corners]
    scene: Scene = [(UNNAMED, (_array(xyz),), False) for xyz in solved if xyz is not None]
    scene.insert(0, ("", tuple(_array(solved[index]) for index in (0, 1, 3, 2)), True))
    return scene


def side_view_pixels(belt: BeltProp, camera: str) -> list[PropDrawing]:
    """A one-camera belt's four reference clicks, solid, in its own view only."""
    view = belt.side_view
    if view is None or view.camera != camera:
        return []
    return [(UNNAMED, ((x, y, True),), False) for x, y in view.pixels]
