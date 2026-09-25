"""A wheel being labelled: its clicks, what they locate, and what to say (D-116, D-119, D-122).

Split from :mod:`avialsync.ui.controllers.wheel_display`, which draws, and
:mod:`avialsync.ui.controllers.wheel_controller`, which acts. What is here is
read off the placement alone -- no window -- so the rules are tested directly:

* **Real clicks are the only evidence.** Two camera clicks on an end locate it
  in 3D and project it into the unclicked views. A projection guides the next
  click and never enters the fit or the wheel file.
* **Done Labelling from the second bar on.** Once both ends of bars 1 and 2
  have two real views each, whatever fit the clicks give can be finished. A
  fit :func:`~avialsync.core.wheel.fit_issue` doubts is drawn and saved
  with a warning rather than hidden or refused (D-123).
* **The clicks decide.** Clicked bars are neighbours in click order, and a
  typed radius that contradicts them gives way to the one they imply.
* **A third bar can only help.** It joins the fit when both of its ends are
  located and it agrees with the first two. One that does not is left out --
  said so in the review -- and its clicks are kept.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from avialsync.core.calibration import CameraModel, triangulate
from avialsync.core.errors import CalibrationError
from avialsync.core.wheel import SIDES, EndClick, WheelFit, WheelSpec
from avialsync.core.wheel_fit import LabelledFit
from avialsync.ui.i18n import tr
from avialsync.ui.wheel_panel import PlacementView, describe_fit

__all__ = [
    "POINTS",
    "Placement",
    "end_label",
    "estimate_missing",
    "describe_adjustment",
    "placement_view",
]

#: The named ends 1A…3B: bar ``step // 2``, side ``SIDES[step % 2]``.
POINTS = 6
#: Bars 1 and 2 -- the least Done Labelling needs.
_REQUIRED_BARS = 2
#: Two cameras placing one end this far apart in 3D is worth a second look.
_CLICK_REPROJECTION_WARN_PX = 10.0

Marks = tuple[tuple[str, float, float], ...]


def end_label(bar: int, side: str) -> str:
    """``"2b"`` for bar index 1's second end: how a point is named on the video."""
    return f"{bar + 1}{'ab'[SIDES.index(side)]}"


@dataclass
class Placement:
    """A wheel being clicked: what was declared, and the clicks so far."""

    spec: WheelSpec
    channel: tuple[str, str] | None
    frame: int
    clicks: dict[tuple[int, str], EndClick] = field(default_factory=dict)
    #: Reprojections from real clicks in two or more views; never fit evidence.
    estimates: dict[tuple[int, str, str], tuple[float, float]] = field(default_factory=dict)
    triangulation_errors: dict[tuple[int, str], float] = field(default_factory=dict)
    #: Which end is wanted: bar ``step // 2``, side ``SIDES[step % 2]``.
    step: int = 0
    #: ``(step, camera, what that camera had before)`` per click, for Undo Click.
    history: list[tuple[int, str, tuple[float, float] | None]] = field(default_factory=list)
    fit: WheelFit | None = None
    #: Updated on refresh; pane painting reads it without rechecking all clicks.
    quality_issue: str | None = None
    #: Why no fit exists, when none does.
    problem: str = ""
    #: What had to give way for a plausible fit: a third bar, or a typed radius.
    note: str = ""
    #: A fit is running in the background; Done Labelling waits for it.
    fitting: bool = False
    #: Bumped per change of clicks or spec, so a stale background fit is ignored.
    generation: int = 0
    flipped: bool = False
    #: What the notification strip last said of the preview: "", "shown" or "hidden".
    announced: str = ""
    #: The wheel this placement will replace on Done Labelling (Re-place), if any.
    replacing: str | None = None

    @property
    def end(self) -> tuple[int, str]:
        return self.step // 2, SIDES[self.step % 2]

    def ordered(self) -> tuple[EndClick, ...]:
        return tuple(self.clicks[key] for key in sorted(self.clicks))

    def views(self, bar: int, side: str) -> set[str]:
        """The cameras with a real click on this end."""
        return {camera for camera, _, _ in self.clicks.get((bar, side), EndClick(bar, side)).views}

    def count(self, step: int) -> int:
        """Number of real camera clicks for the named point *step*."""
        return len(self.views(step // 2, SIDES[step % 2]))

    def ready(self, cameras: set[str]) -> bool:
        """The first two bars each have both ends in two calibrated cameras."""
        if len(cameras) < 2:
            return False
        return all(
            len(self.views(bar, side) & cameras) >= 2
            for bar in range(_REQUIRED_BARS)
            for side in SIDES
        )

    def step_near(self, camera: str, x: float, y: float, radius: float) -> int | None:
        """The point whose projected mark in *camera* is within *radius* of ``(x, y)``."""
        near = [
            ((px - x) ** 2 + (py - y) ** 2, bar * 2 + SIDES.index(side))
            for (bar, side, view), (px, py) in self.estimates.items()
            if view == camera
        ]
        if not near:
            return None
        distance, step = min(near)
        return step if distance <= radius**2 else None

    def marks(self, camera: str) -> tuple[Marks, Marks, str]:
        """``(clicks, projections, cue)`` to draw over *camera*'s video."""
        clicks = tuple(
            (end_label(bar, side), x, y)
            for (bar, side), click in sorted(self.clicks.items())
            for view, x, y in click.views
            if view == camera
        )
        projections = tuple(
            (end_label(bar, side), *xy)
            for (bar, side, view), xy in sorted(self.estimates.items())
            if view == camera
        )
        if self.step >= POINTS:
            return clicks, projections, tr("Select a point to correct it, or choose Done Labelling")
        bar, side = self.end
        point = end_label(bar, side).upper()
        if camera in self.views(bar, side):
            cue = tr("Point {point} clicked here").format(point=point)
        elif (bar, side, camera) in self.estimates:
            cue = tr("Point {point} projected here — click to confirm").format(point=point)
        else:
            cue = tr("Click point {point} here").format(point=point)
        return clicks, projections, cue


def estimate_missing(placement: Placement, cameras: Mapping[str, CameraModel]) -> None:
    """Project triangulated clicks into unclicked views without adding fit evidence."""
    placement.estimates.clear()
    placement.triangulation_errors.clear()
    for (bar, side), click in placement.clicks.items():
        views = [(cameras[name], (x, y)) for name, x, y in click.views if name in cameras]
        if len(views) < 2:
            continue
        try:
            point, error = triangulate(views)
        except CalibrationError:
            continue
        if not np.all(np.isfinite(point)):
            continue
        placement.triangulation_errors[(bar, side)] = error
        clicked = placement.views(bar, side)
        for name, camera in cameras.items():
            if name in clicked:
                continue
            depth = (point @ camera.rotation_matrix().T + camera.translation)[2]
            if depth <= 0:
                continue
            x, y = camera.project(point)[0]
            if (
                np.isfinite(x)
                and np.isfinite(y)
                and 0 <= x < camera.size[0]
                and 0 <= y < camera.size[1]
            ):
                placement.estimates[(bar, side, name)] = float(x), float(y)


def describe_adjustment(spec: WheelSpec, labelled: LabelledFit) -> str:
    """What gave way for a plausible fit, in the words the Wheels tab uses."""
    notes = []
    if labelled.dropped_third is not None:
        notes.append(
            _left_out(labelled.dropped_third or tr("it does not agree with bars 1 and 2."))
        )
    if labelled.radius_from_clicks:
        notes.append(_radius_note(spec, labelled.fit.geometry.radius))
    return " ".join(notes)


def _radius_note(spec: WheelSpec, implied: float) -> str:
    """The typed radius gave way to the clicks: say so, and suspect the units."""
    typed = float(spec.radius or 0.0)
    ratio = implied / typed if typed > 0 else 0.0
    note = tr(
        "The radius you entered ({typed:.1f} {units}) does not fit your clicks, which imply "
        "{implied:.1f} {units}, so the wheel is built from the clicks."
    ).format(typed=typed, implied=implied, units=spec.units)
    for factor in (10, 100, 1000):
        if 0.8 * factor < ratio < 1.25 * factor or 0.8 / factor < ratio < 1.25 / factor:
            note += " " + tr(
                "That is about {factor}× apart, as if the calibration's 3D units were not "
                "{units}: check the 3D units."
            ).format(factor=factor, units=spec.units)
            break
    return note


def _left_out(reason: str) -> str:
    return tr(
        "Bar 3 is left out of the fit: {reason} Its clicks are kept; correct 3A or 3B to "
        "include it."
    ).format(reason=reason)


def placement_view(placement: Placement, cameras: Sequence[str]) -> PlacementView:
    """What the Wheels tab shows while *placement* is being labelled."""
    ready = placement.ready(set(cameras))
    return PlacementView(
        spec=placement.spec,
        frame=placement.frame,
        instruction=_instruction(placement, cameras, ready),
        summary=_summary(placement, ready),
        active_step=placement.step,
        point_counts=tuple(placement.count(step) for step in range(POINTS)),
        camera_count=len(cameras),
        estimated_count=len(placement.estimates),
        can_next=placement.step < POINTS - 1,
        can_undo=bool(placement.history),
        can_flip=placement.fit is not None and placement.fit.can_flip,
        # From bars 1 and 2 on, whatever the fit's quality: an unreliable one
        # is saved hidden, never refused (D-122).
        can_accept=placement.fit is not None and ready and not placement.fitting,
    )


def _instruction(placement: Placement, cameras: Sequence[str], ready: bool) -> str:
    """The next click wanted, and how far the selected point has got."""
    if placement.step >= POINTS:
        return (
            tr("Review the fit and choose Done Labelling, or select a point to add a camera click.")
            if ready
            else tr("Some points need a second camera click. Select a point above to finish it.")
        )
    bar, side = placement.end
    clicked = placement.views(bar, side)
    end = tr("first end") if side == SIDES[0] else tr("second end")
    instruction = (
        tr("Point {point} · bar {bar}, {end} · {count}/{total} cameras.").format(
            point=end_label(bar, side).upper(),
            bar=bar + 1,
            end=end,
            count=len(clicked),
            total=len(cameras),
        )
        + " "
        + _point_detail(placement, clicked, [c for c in cameras if c not in clicked])
    )
    error = placement.triangulation_errors.get((bar, side))
    if error is not None and error > _CLICK_REPROJECTION_WARN_PX:
        instruction += " " + tr("Clicks disagree by {error:.1f} px; check them.").format(
            error=error
        )
    return instruction


def _point_detail(placement: Placement, clicked: set[str], remaining: list[str]) -> str:
    if not clicked:
        return tr("Click here, or choose another point.")
    if len(clicked) == 1:
        return tr("Clicked in {clicked}. Click one more camera for 3D.").format(
            clicked=", ".join(sorted(clicked))
        )
    if not remaining:
        return tr("Clicked in every camera. Next Point or review the fit.")
    bar, side = placement.end
    projected = [name for name in remaining if (bar, side, name) in placement.estimates]
    off_frame = [name for name in remaining if name not in projected]
    parts = []
    if projected:
        parts.append(
            tr("Projected in {cameras}. Click there or Next Point.").format(
                cameras=", ".join(projected)
            )
        )
    if off_frame:
        parts.append(
            tr("No on-frame projection in {cameras}; click manually.").format(
                cameras=", ".join(off_frame)
            )
        )
    return " ".join(parts)


def _summary(placement: Placement, ready: bool) -> str:
    """The fit so far, and what Done Labelling would do with it."""
    if placement.fitting:
        return tr("Generating wheel…")
    if placement.fit is None:
        return placement.problem or tr("Click both ends of at least two neighbouring bars.")
    parts = [describe_fit(placement.spec, placement.fit, placement.ordered())]
    third = (placement.count(4), placement.count(5))
    if placement.note:
        parts.append(placement.note)
    if not ready:
        parts.append(
            tr("Done Labelling needs two real camera clicks at both ends of bars 1 and 2.")
        )
    elif placement.quality_issue is not None:
        parts.append(tr("Done Labelling still saves this wheel as drawn; Re-place it later."))
    elif any(third) and min(third) < 2 and not placement.note:
        parts.append(tr("An incomplete third bar is saved as clicks; the fit uses complete bars."))
    elif not any(third):
        parts.append(
            tr("Done Labelling is available. Bar 3 (3A, 3B) is optional and can improve the fit.")
        )
    return " ".join(parts)
