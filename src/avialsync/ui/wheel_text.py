"""What the Wheels tab says about a wheel: its fit and its encoder, in words (D-113, D-123).

Split from :mod:`avialsync.ui.wheel_panel`, which lays the tab out; the
placement review in :mod:`avialsync.ui.controllers.wheel_placement` uses the
same words, so a fit reads the same while placing and once placed.
"""

from __future__ import annotations

from collections.abc import Sequence

from avialsync.core.wheel import EndClick, Wheel, WheelFit, WheelSpec, fit_issue
from avialsync.ui.i18n import tr

__all__ = ["describe_encoder", "describe_fit"]

#: Relative disagreement between a typed radius and the clicks' own, beyond
#: which the numbers say so in words: units, bar count, or calibration scale.
_RADIUS_WARNING = 0.07


def _unreliable(issue: str) -> str:
    """Why :func:`fit_issue` doubts a fit, and what to check. It is still drawn (D-123)."""
    cause = (
        tr("The clicked bars do not sit in neighbouring slots.")
        if issue == "bars_not_neighbours"
        else tr("The wheel is far from your camera clicks.")
    )
    return tr(
        "Poor fit. {cause} Check the clicked bar ends, the 3D units and the camera calibration."
    ).format(cause=cause)


def describe_fit(wheel_spec: WheelSpec, fit: WheelFit, clicks: Sequence[EndClick]) -> str:
    """The fit in one paragraph: size, click error, and anything to check."""
    units = f" {wheel_spec.units}" if wheel_spec.units else ""
    geometry = fit.geometry
    issue = fit_issue(fit, clicks)
    parts = [
        tr("{bars} bars, radius {radius:.1f}{units}, width {width:.1f}{units}.").format(
            bars=geometry.bar_count,
            radius=geometry.radius,
            width=2 * geometry.half_width,
            units=units,
        ),
        tr("Clicks sit {median:.1f} px from the wheel (worst {worst:.1f} px).").format(
            median=fit.median_px, worst=fit.max_px
        ),
    ]
    if fit.spacing_deg:
        parts.append(
            tr("Bars within {spacing:.1f}° of their slots, {parallel:.1f}° of the axle.").format(
                spacing=max(abs(v) for v in fit.spacing_deg),
                parallel=max(fit.parallel_deg, default=0.0),
            )
        )
    typed = wheel_spec.known_radius
    if (
        typed is not None
        and fit.implied_radius is None
        and abs(geometry.radius - typed) > (_RADIUS_WARNING * typed)
    ):
        parts.append(
            tr(
                "Built from the radius your clicks imply, not the {typed:.1f}{units} entered."
            ).format(typed=typed, units=units)
        )
    if fit.implied_radius is not None and wheel_spec.radius:
        share = abs(fit.implied_radius - wheel_spec.radius) / wheel_spec.radius
        parts.append(
            tr("You entered {typed:.1f}{units}; the clicks imply {implied:.1f}{units}.").format(
                typed=wheel_spec.radius, implied=fit.implied_radius, units=units
            )
        )
        if share > _RADIUS_WARNING:
            parts.append(
                tr(
                    "That is {share:.0%} apart: check the 3D units, the bar count, and "
                    "the calibration's scale."
                ).format(share=share)
            )
    if fit.ambiguous:
        parts.append(
            tr(
                "A mirrored wheel fits almost as well. Check the bars drawn over the "
                "video, and Flip if the wheel is on the wrong side."
            )
        )
    if issue is not None:
        parts.insert(0, _unreliable(issue))
    return " ".join(parts)


def describe_encoder(wheel: Wheel) -> str:
    """How the wheel turns, and how sure the direction is."""
    binding = wheel.binding
    if binding is None:
        return tr("Not turned by an encoder: drawn on frame {frame} only.").format(
            frame=wheel.frame
        )
    direction = tr("forward") if binding.sign > 0 else tr("reverse")
    if binding.measured:
        state = tr("direction {direction}, measured from {count} checks.").format(
            direction=direction, count=len(binding.checks)
        )
    else:
        state = tr(
            "direction {direction} is assumed. Verify on a frame a few turns away to measure it."
        ).format(direction=direction)
    return tr("Turned by {channel}; {state}").format(channel=binding.channel, state=state)
