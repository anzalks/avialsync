"""Testing the encoder that turns a wheel against the video (D-113).

A wheel fitted on one frame is carried to every other frame by the encoder:
``turn = sign * ratio * (angle - reference_angle)``. The ratio is 1 for an
encoder on the axle, and the user sets it otherwise; the **sign** is not
something anyone should have to know, and guessing it wrong turns the wheel
backwards while every frame near the reference still looks right. So it is
measured: the user clicks any bar end, in any one camera, on a frame far from
the reference, and each sign predicts where the bars should be.

**A click fixes the turn only up to one bar gap.** The bars are identical, so a
click says "a bar is here", never which. The observed turn is therefore known
modulo the pitch, and a check is only *informative* once the wheel has moved at
least a whole gap since the reference -- before that, both signs predict nearly
the same picture. Two informative checks that agree settle the sign; one is
reported, not trusted.

Headless (architecture rule 2).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize_scalar

from avialsync.core.calibration import CameraModel
from avialsync.core.wheel import EncoderBinding, WheelCheck, WheelGeometry, project_bars

__all__ = ["CheckResult", "observed_turn", "check", "settle_sign"]

#: Turns sampled across one bar gap before refining; fine enough that the
#: refinement starts in the right basin.
_STEPS = 240
#: A sign is settled when every informative check sits within this share of a
#: bar gap, and the other sign does clearly worse.
_SETTLED_SHARE = 1.0 / 6.0
_MIN_SETTLING_CHECKS = 2


@dataclass(frozen=True)
class CheckResult:
    """How one check agrees with the encoder."""

    check: WheelCheck
    #: Degrees between the turn the click shows and the turn the encoder says.
    residual_deg: float
    #: Pixels from the click to the nearest bar end the encoder puts on screen.
    residual_px: float
    #: The wheel has turned at least one bar gap, so this check can tell signs apart.
    informative: bool


def _distances(
    geometry: WheelGeometry, turns: np.ndarray, camera: CameraModel, pixel: np.ndarray
) -> np.ndarray:
    """Distance from *pixel* to the nearest visible bar end, per turn.

    Every turn's wheel is projected in one call: a loop over turns cost ~90 ms
    for three checks, over the UI thread's 30 ms ceiling (rule 3).
    """
    x, y, z = geometry.basis()
    count = geometry.bar_count
    angles = np.radians(turns[:, None] + np.arange(count)[None, :] * 360.0 / count)
    radial = np.cos(angles)[..., None] * x + np.sin(angles)[..., None] * y
    rim = np.asarray(geometry.centre, dtype=np.float64) + geometry.radius * radial
    offset = geometry.half_width * z
    ends = np.stack((rim - offset, rim + offset), axis=2).reshape(-1, 2, 3)
    pixels, in_front, facing = project_bars(geometry, ends, camera)
    distance = np.linalg.norm(pixels - pixel, axis=2).min(axis=1)
    distance[~(in_front & facing)] = np.inf
    out: np.ndarray = distance.reshape(len(turns), count).min(axis=1)
    return out


def observed_turn(
    geometry: WheelGeometry, camera: CameraModel, x: float, y: float
) -> tuple[float, float]:
    """The turn in ``[0, pitch)`` that best puts a visible bar end at *(x, y)*.

    Returns ``(turn in degrees, pixels off)``; ``(nan, inf)`` when no bar faces
    the camera at all.
    """
    pitch = 360.0 / geometry.bar_count
    pixel = np.asarray([x, y], dtype=np.float64)
    turns = np.linspace(0.0, pitch, _STEPS, endpoint=False)
    coarse = _distances(geometry, turns, camera, pixel)
    if not np.any(np.isfinite(coarse)):
        # No bar faces this camera at any turn: the click cannot be matched.
        return math.nan, math.inf
    best = float(turns[int(np.argmin(coarse))])
    step = pitch / _STEPS
    result = minimize_scalar(
        lambda t: float(_distances(geometry, np.asarray([t]), camera, pixel)[0]),
        bounds=(best - step, best + step),
        method="bounded",
    )
    turn = float(result.x) % pitch
    return turn, float(result.fun)


def _wrap(value: float, period: float) -> float:
    return (value + period / 2.0) % period - period / 2.0


def check(
    geometry: WheelGeometry,
    binding: EncoderBinding,
    camera: CameraModel,
    item: WheelCheck,
    seen: float | None = None,
) -> CheckResult:
    """Compare one check with what *binding* predicts.

    *seen* is the click's :func:`observed_turn`, when the caller already has
    it: it does not depend on the binding, so trying both signs need not
    search for it twice.
    """
    pitch = 360.0 / geometry.bar_count
    predicted = binding.turn(item.encoder_angle)
    if seen is None:
        seen, _ = observed_turn(geometry, camera, item.x, item.y)
    pixel = np.asarray([item.x, item.y], dtype=np.float64)
    off = _distances(geometry, np.asarray([predicted]), camera, pixel)[0]
    moved = abs(binding.ratio * (item.encoder_angle - binding.reference_angle))
    matched = math.isfinite(seen)
    return CheckResult(
        check=item,
        residual_deg=_wrap(seen - predicted, pitch) if matched else math.nan,
        residual_px=float(off),
        informative=matched and moved >= pitch,
    )


def settle_sign(
    geometry: WheelGeometry,
    binding: EncoderBinding,
    cameras: Mapping[str, CameraModel],
    checks: Sequence[WheelCheck] | None = None,
) -> tuple[EncoderBinding, list[CheckResult]]:
    """Choose the direction the checks support, and say whether it is settled.

    Returns the binding with ``sign`` and ``measured`` updated and every check
    stored on it, plus each check's result under the chosen sign. With too few
    informative checks the sign is left as it was and ``measured`` is False.
    """
    items = list(binding.checks if checks is None else checks)
    usable = [item for item in items if item.camera in cameras]
    pitch = 360.0 / geometry.bar_count
    seen = [observed_turn(geometry, cameras[i.camera], i.x, i.y)[0] for i in usable]
    outcomes: dict[float, list[CheckResult]] = {}
    for sign in (1.0, -1.0):
        trial = dataclasses.replace(binding, sign=sign)
        outcomes[sign] = [
            check(geometry, trial, cameras[i.camera], i, turn)
            for i, turn in zip(usable, seen, strict=True)
        ]
    informative = [r.informative for r in outcomes[1.0]]

    def spread(results: list[CheckResult]) -> float:
        chosen = [r.residual_deg for r, keep in zip(results, informative, strict=True) if keep]
        return math.sqrt(sum(r * r for r in chosen) / len(chosen)) if chosen else math.inf

    sign = binding.sign
    measured = False
    if sum(informative) >= 1:
        sign = min((1.0, -1.0), key=lambda s: spread(outcomes[s]))
    if sum(informative) >= _MIN_SETTLING_CHECKS:
        worst = max(
            abs(r.residual_deg) for r, keep in zip(outcomes[sign], informative, strict=True) if keep
        )
        measured = worst <= pitch * _SETTLED_SHARE and spread(outcomes[-sign]) > 2.0 * worst
    settled = dataclasses.replace(binding, sign=sign, measured=measured, checks=tuple(items))
    return settled, outcomes[sign]
