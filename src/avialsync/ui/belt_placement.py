"""Turn four belt placement clicks into the Props belt fields (D-165).

Clicks say where the belt is; the typed measurements say how big it is. In 3D
the four top corners, each seen by two calibrated cameras, fix the top plane,
the run, the width and the middle. In one camera, both roller hubs and the top
above each fix the side plane's perspective, so no calibration is needed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from PySide6.QtWidgets import QDoubleSpinBox

from avialsync.core.belt_rollers import BeltSideView, rollers_from_corners, side_rollers
from avialsync.core.calibration import CameraModel
from avialsync.core.errors import PropModelError
from avialsync.core.physical_props import BeltProp, LadderPoint, Point3
from avialsync.ui.i18n import tr
from avialsync.ui.props_panel import PropsPanel

__all__ = ["Placement", "place", "kept"]


@dataclass(frozen=True)
class Placement:
    """Accepted placement clicks awaiting the belt's save, and what they measured."""

    mode: str
    corners: tuple[LadderPoint, LadderPoint, LadderPoint, LadderPoint] | None
    side_view: BeltSideView | None
    report: str


def _set(fields: Sequence[QDoubleSpinBox], values: Point3) -> None:
    for field, value in zip(fields, values, strict=True):
        field.setValue(value)


def _default_direction(panel: PropsPanel, run: Point3) -> None:
    """Travel defaults to the first roller toward the second, unless already typed."""
    if all(field.value() == 0.0 for field in panel.belt_direction_fields):
        _set(panel.belt_direction_fields, run)


def _side(points: Sequence[LadderPoint], panel: PropsPanel) -> Placement | str:
    shared = set.intersection(*({click.camera for click in point.clicks} for point in points))
    if not shared:
        return tr("Click all four points in the same camera for a one-camera belt.")
    camera = sorted(shared)[0]
    clicks = [next(c for c in point.clicks if c.camera == camera) for point in points]
    distance = float(panel.belt_centre_distance.value())
    radius = float(panel.belt_radius.value())
    width = float(panel.belt_width.value())
    if distance <= 0.0 or width <= 0.0:
        return tr("Enter the measured centre distance and belt width for a one-camera belt.")
    view = BeltSideView(
        camera,
        max(click.frame for click in clicks),
        (
            (clicks[0].x, clicks[0].y),
            (clicks[1].x, clicks[1].y),
            (clicks[2].x, clicks[2].y),
            (clicks[3].x, clicks[3].y),
        ),
    )
    try:
        view.plane_view(side_rollers(distance, radius, width))
    except PropModelError:
        return tr("These clicks cannot show the belt's side; click the hubs and top again.")
    _default_direction(panel, (1.0, 0.0, 0.0))
    units = str(panel.belt_units.currentData() or "") or tr("measurement units")
    return Placement(
        "side",
        None,
        view,
        tr(
            "Placed in {camera}'s side view: centres {distance:.4g} {units} apart, "
            "radius {radius:.4g}. Not placed in 3D."
        ).format(camera=camera, distance=distance, units=units, radius=radius),
    )


def _corners(
    points: Sequence[LadderPoint], panel: PropsPanel, cameras: Mapping[str, CameraModel]
) -> Placement | str:
    solved = [point.resolved(cameras) for point in points]
    xyz: list[Point3] = []
    for point in solved:
        if point.xyz is None:
            return tr("Each top corner needs clicks in two calibrated cameras.")
        xyz.append(point.xyz)
    seen = {click.camera for point in solved for click in point.clicks} & set(cameras)
    centres = [
        -cameras[name].rotation_matrix().T @ cameras[name].translation for name in sorted(seen)
    ]
    viewpoint = np.mean(centres, axis=0)
    distance = float(panel.belt_centre_distance.value()) or None
    try:
        rollers, span, flatness = rollers_from_corners(
            (xyz[0], xyz[1], xyz[2], xyz[3]),
            float(panel.belt_radius.value()),
            distance,
            (float(viewpoint[0]), float(viewpoint[1]), float(viewpoint[2])),
        )
    except PropModelError:
        return tr("The corners must be two near each roller, apart along the belt.")
    _set(panel.belt_first_fields, rollers.first)
    _set(panel.belt_second_fields, rollers.second)
    _set(panel.belt_normal_fields, rollers.top_normal)
    panel.belt_width.setValue(rollers.width)
    run = rollers.axes()[0]
    _default_direction(panel, (float(run[0]), float(run[1]), float(run[2])))
    units = str(panel.belt_units.currentData() or "") or tr("calibration units")
    return Placement(
        "rollers",
        (solved[0], solved[1], solved[2], solved[3]),
        None,
        tr(
            "Placed in 3D: clicked span {span:.4g}, centres {distance:.4g} {units} apart, "
            "width {width:.4g}; corners within {flatness:.2g} of one plane."
        ).format(
            span=span,
            distance=rollers.run_length,
            units=units,
            width=rollers.width,
            flatness=flatness,
        ),
    )


def place(
    mode: str,
    points: Sequence[LadderPoint],
    panel: PropsPanel,
    cameras: Mapping[str, CameraModel],
) -> Placement | str:
    """Fill the panel from four clicks, or say what is missing."""
    if float(panel.belt_radius.value()) <= 0.0:
        return tr("Enter the measured roller radius before placing the belt.")
    if mode == "side":
        return _side(points, panel)
    return _corners(points, panel, cameras)


def kept(
    pending: Placement | None, before: BeltProp | None, mode: str
) -> tuple[tuple[LadderPoint, LadderPoint, LadderPoint, LadderPoint] | None, BeltSideView | None]:
    """The placement clicks a saved belt keeps for the geometry mode being saved."""
    if pending is not None and pending.mode == mode:
        return pending.corners, pending.side_view
    if before is None:
        return None, None
    return (
        before.corners if mode == "rollers" else None,
        before.side_view if mode == "side" else None,
    )
