"""Recovery policy for fitting a labelled wheel from imperfect click sets.

The geometric optimizer stays in :mod:`avialsync.core.wheel_fit`; this module
only decides which labelled subsets and radius constraints deserve a fit.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from avialsync.core.calibration import CameraModel
from avialsync.core.errors import WheelFitError
from avialsync.core.wheel import EndClick, WheelFit, WheelSpec

_REQUIRED_BARS = 2
_CONTRADICTION_FACTOR = 2.0


@dataclass(frozen=True)
class LabelledFit:
    """The wheel a user's clicks describe, and what had to give way for it."""

    fit: WheelFit
    dropped_third: str | None = None
    radius_from_clicks: bool = False


def _attempts(
    spec: WheelSpec, clicks: Sequence[EndClick]
) -> list[tuple[Sequence[EndClick], WheelSpec, bool, bool]]:
    first = [click for click in clicks if click.bar < _REQUIRED_BARS]
    free = dataclasses.replace(spec, radius=None) if spec.known_radius is not None else None
    attempts = [(clicks, spec, False, False)]
    if len(first) < len(clicks):
        attempts.append((first, spec, True, False))
    if free is not None:
        attempts.append((clicks, free, False, True))
        if len(first) < len(clicks):
            attempts.append((first, free, True, True))
    return attempts


def _contradicts(fit: WheelFit, spec: WheelSpec) -> bool:
    typed, implied = spec.known_radius, fit.implied_radius
    if typed is None or implied is None or typed <= 0.0 or implied <= 0.0:
        return False
    return max(typed, implied) / min(typed, implied) > _CONTRADICTION_FACTOR


def fit_labelled(
    spec: WheelSpec,
    clicks: Sequence[EndClick],
    cameras: Mapping[str, CameraModel],
    *,
    flipped: bool,
    fitter: Callable[..., WheelFit],
    quality: Callable[[WheelFit, Sequence[EndClick]], str | None],
) -> LabelledFit:
    """Try valid labelled subsets before reporting the best available fit."""
    best: tuple[WheelFit, bool] | None = None
    contradicted: WheelFit | None = None
    error: WheelFitError | None = None
    for used, used_spec, dropped, radius_from_clicks in _attempts(spec, clicks):
        try:
            fit = fitter(used_spec, used, cameras, flipped=flipped)
        except WheelFitError as failure:
            error = error or failure
            continue
        if _contradicts(fit, used_spec):
            contradicted = contradicted or fit
            continue
        best = best or (fit, radius_from_clicks)
        if quality(fit, clicks) is None:
            dropped_third = (str(error) if error is not None else "") if dropped else None
            return LabelledFit(fit, dropped_third, radius_from_clicks)
    if best is not None:
        return LabelledFit(best[0], radius_from_clicks=best[1])
    if contradicted is not None:
        return LabelledFit(contradicted)
    raise error or WheelFitError("No wheel fits the clicked bars.")
