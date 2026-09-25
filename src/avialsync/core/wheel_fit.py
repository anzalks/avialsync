"""Fitting a wheel to both ends of a few clicked neighbouring bars (D-113).

See :mod:`avialsync.core.wheel` for what the clicks can and cannot determine.
In short: the bars' directions give the axle, their lengths the width, and the
bar count turns the gap between neighbours into the radius. A typed radius makes
the fit over-determined, and the radius the clicks imply is reported beside it.
Two bars fit two mirrored wheels; both are refined, and the closer call goes to
the one farther from the cameras. The refinement is in pixels: it moves the
whole wheel until every generated bar end lands on its click in every camera.

Headless (architecture rule 2).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from avialsync.core.calibration import CameraModel, triangulate
from avialsync.core.errors import CalibrationError, WheelFitError
from avialsync.core.wheel import (
    LEFT,
    MIN_BAR_COUNT,
    RIGHT,
    SIDES,
    ClickResidual,
    EndClick,
    WheelFit,
    WheelGeometry,
    WheelSpec,
    camera_centre,
    fit_issue,
)

__all__ = ["LabelledFit", "fit_labelled", "fit_wheel"]

#: Two candidate centres whose fits cost within this factor are both plausible,
#: and the choice between them is the cameras' rather than the residual's.
_AMBIGUOUS_COST_RATIO = 1.5
#: A mirrored candidate starting this many times worse than the best is not a
#: real alternative (measured: ambiguous pairs start within 2x, hopeless ones
#: 200x to 13000x apart), so it is not refined unless Flip asks for it.
_HOPELESS_START_RATIO = 50.0
#: Robust loss scale, in pixels: one careless click should not drag the wheel.
_LOSS_SCALE_PX = 3.0


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        raise WheelFitError("Two clicks that should differ landed on the same point.")
    unit: np.ndarray = vector / norm
    return unit


def _perpendicular_basis(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    helper = np.eye(3)[int(np.argmin(np.abs(axis)))]
    u = _unit(np.cross(axis, helper))
    return u, np.cross(axis, u)


def _triangulated_bars(
    clicks: Sequence[EndClick], cameras: Mapping[str, CameraModel]
) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """Each bar whose two ends were both clicked in at least two calibrated cameras."""
    ends: dict[tuple[int, str], np.ndarray] = {}
    for click in clicks:
        views = [(cameras[c], (x, y)) for c, x, y in click.views if c in cameras]
        if len(views) < 2:
            continue
        try:
            point, _ = triangulate(views)
        except CalibrationError:
            continue
        ends[(click.bar, click.side)] = point
    return {
        bar: (ends[(bar, LEFT)], ends[(bar, RIGHT)])
        for bar in sorted({bar for bar, _ in ends})
        if (bar, LEFT) in ends and (bar, RIGHT) in ends
    }


def _candidate_centres(flat: np.ndarray, radius: float) -> list[np.ndarray]:
    """In-plane centres of a circle of *radius* through the two closest bars."""
    count = len(flat)
    pairs = [(i, j) for i in range(count) for j in range(i + 1, count)]
    i, j = min(pairs, key=lambda pair: float(np.linalg.norm(flat[pair[0]] - flat[pair[1]])))
    chord = flat[j] - flat[i]
    middle = (flat[i] + flat[j]) / 2.0
    half = float(np.linalg.norm(chord)) / 2.0
    if half >= radius:
        return [middle]
    across = np.array([-chord[1], chord[0]]) / (2.0 * half)
    offset = math.sqrt(radius * radius - half * half)
    return [middle + offset * across, middle - offset * across]


@dataclass
class _Problem:
    """The clicks as flat arrays, so one residual call projects them all at once."""

    angles: np.ndarray  # slot angle of each view's bar, radians
    signs: np.ndarray  # -1 left, +1 right
    observed: np.ndarray  # (V, 2) pixels
    groups: list[tuple[CameraModel, np.ndarray]]  # camera, view mask
    labels: list[tuple[int, str, str]]  # (bar, side, camera) per view


def _problem(
    clicks: Sequence[EndClick],
    cameras: Mapping[str, CameraModel],
    slot_of: Mapping[int, int],
    pitch: float,
) -> _Problem:
    angles, signs, observed, labels, owner = [], [], [], [], []
    for click in clicks:
        if click.bar not in slot_of:
            continue
        for camera, x, y in click.views:
            if camera not in cameras:
                continue
            angles.append(slot_of[click.bar] * pitch)
            signs.append(-1.0 if click.side == LEFT else 1.0)
            observed.append((x, y))
            labels.append((click.bar, click.side, camera))
            owner.append(camera)
    owners = np.asarray(owner)
    return _Problem(
        angles=np.asarray(angles, dtype=np.float64),
        signs=np.asarray(signs, dtype=np.float64),
        observed=np.asarray(observed, dtype=np.float64).reshape(-1, 2),
        groups=[(cameras[name], owners == name) for name in sorted(set(owner))],
        labels=labels,
    )


def _geometry_from(params: np.ndarray, radius: float | None, bar_count: int) -> WheelGeometry:
    basis = Rotation.from_rotvec(params[0:3]).as_matrix()
    fitted_radius = float(params[6]) if radius is None else radius
    return WheelGeometry(
        centre=(float(params[3]), float(params[4]), float(params[5])),
        axle=(float(basis[0, 2]), float(basis[1, 2]), float(basis[2, 2])),
        zero=(float(basis[0, 0]), float(basis[1, 0]), float(basis[2, 0])),
        radius=abs(fitted_radius),
        half_width=abs(float(params[-1])),
        bar_count=bar_count,
    )


def _residuals(params: np.ndarray, problem: _Problem, radius: float | None) -> np.ndarray:
    basis = Rotation.from_rotvec(params[0:3]).as_matrix()
    x, y, z = basis[:, 0], basis[:, 1], basis[:, 2]
    r = float(params[6]) if radius is None else radius
    radial = np.cos(problem.angles)[:, None] * x + np.sin(problem.angles)[:, None] * y
    ends = params[3:6] + r * radial + (problem.signs * params[-1])[:, None] * z
    out = np.empty_like(problem.observed)
    for camera, mask in problem.groups:
        out[mask] = camera.project(ends[mask]) - problem.observed[mask]
    flat: np.ndarray = out.ravel()
    return flat


def _refine(problem: _Problem, start: np.ndarray, radius: float | None) -> tuple[np.ndarray, float]:
    solution = least_squares(
        _residuals,
        start,
        args=(problem, radius),
        loss="soft_l1",
        f_scale=_LOSS_SCALE_PX,
        x_scale="jac",
        max_nfev=2000,
    )
    return np.asarray(solution.x, dtype=np.float64), float(solution.cost)


def _slots(
    mids: np.ndarray, centre: np.ndarray, axle: np.ndarray
) -> tuple[np.ndarray, dict[int, int]]:
    """Bar 0's direction, and each clicked bar's slot round the wheel.

    The clicked bars *are* neighbours, in the order clicked: that is what the
    user was asked to click, so it is taken as given rather than re-derived
    from angles (D-123). Rounding each bar's own angle let a wrong radius or
    unit scatter bars clicked side by side ten slots apart. Only the direction
    round the wheel comes from the geometry.
    """
    radial = mids - centre
    radial -= np.outer(radial @ axle, axle)
    zero = _unit(radial[0])
    quarter = np.cross(axle, zero)
    angles = np.arctan2(radial @ quarter, radial @ zero)
    step = 1 if len(angles) < 2 or float(angles[1]) >= 0.0 else -1
    return zero, {index: index * step for index in range(len(angles))}


def _fit_candidate(
    spec: WheelSpec,
    clicks: Sequence[EndClick],
    cameras: Mapping[str, CameraModel],
    mids: np.ndarray,
    axle: np.ndarray,
    centre: np.ndarray,
    radius: float,
    half_width: float,
    radius_fixed: bool,
) -> tuple[_Problem, np.ndarray, dict[int, int]]:
    """One candidate's problem and linear starting point, not yet refined."""
    pitch = math.radians(spec.pitch)
    zero, slots = _slots(mids, centre, axle)
    order = sorted({click.bar for click in clicks})
    slot_of = {bar: slots[index] for index, bar in enumerate(order) if index in slots}
    problem = _problem(clicks, cameras, slot_of, pitch)
    basis = np.column_stack((zero, np.cross(axle, zero), axle))
    rotvec = Rotation.from_matrix(basis).as_rotvec()
    tail = [half_width] if radius_fixed else [radius, half_width]
    return problem, np.concatenate((rotvec, centre, tail)), slot_of


@dataclass
class _Start:
    """The linear first guess: what the triangulated bars say before any refinement."""

    axle: np.ndarray
    mids: np.ndarray
    half_width: float
    radius: float
    #: Candidate centres in 3D -- two for a chord, one when the bars span a diameter.
    centres: list[np.ndarray]


def _start(spec: WheelSpec, bars: Mapping[int, tuple[np.ndarray, np.ndarray]]) -> _Start:
    lefts = np.asarray([bars[bar][0] for bar in bars])
    rights = np.asarray([bars[bar][1] for bar in bars])
    vectors = rights - lefts
    for bar, vector in zip(bars, vectors, strict=True):
        # Every bar is parallel to the axle, so one clicked end-first the other
        # way round points backwards -- and would cancel the axle out of the mean.
        if float(vector @ vectors[0]) < 0:
            raise WheelFitError(
                f"Bar {bar + 1}'s ends were clicked in the opposite order to the first "
                "bar's. Click the end on the same side of the wheel first on every bar."
            )
    axle = _unit(np.sum([_unit(v) for v in vectors], axis=0))
    mids = (lefts + rights) / 2.0
    u, v = _perpendicular_basis(axle)
    flat = np.column_stack((mids @ u, mids @ v))
    height = float(np.mean(mids @ axle))
    radius = spec.known_radius
    if radius is None:
        # The gap between the closest two -- neighbours -- and the bar count.
        closest = min(
            float(np.linalg.norm(flat[i] - flat[j]))
            for i in range(len(flat))
            for j in range(i + 1, len(flat))
        )
        radius = closest / (2.0 * math.sin(math.radians(spec.pitch) / 2.0))
    return _Start(
        axle=axle,
        mids=mids,
        half_width=float(np.mean(np.abs(vectors @ axle))) / 2.0,
        radius=radius,
        centres=[height * axle + c[0] * u + c[1] * v for c in _candidate_centres(flat, radius)],
    )


def fit_wheel(
    spec: WheelSpec,
    clicks: Sequence[EndClick],
    cameras: Mapping[str, CameraModel],
    *,
    flipped: bool = False,
) -> WheelFit:
    """Fit a wheel of ``spec.bar_count`` bars to both ends of clicked neighbours.

    *cameras* maps each camera name used in the clicks to its calibrated model.
    Raises :class:`WheelFitError` with the reason when the clicks cannot
    determine a wheel.
    """
    if spec.bar_count < MIN_BAR_COUNT:
        raise WheelFitError(f"A wheel needs at least {MIN_BAR_COUNT} bars.")
    bars = _triangulated_bars(clicks, cameras)
    if len(bars) < 2:
        raise WheelFitError(
            "Both ends of at least two bars are needed, each clicked in two or more cameras."
        )
    used = [click for click in clicks if click.bar in bars]
    start = _start(spec, bars)
    typed = spec.known_radius
    prepared = []
    for centre in start.centres:
        try:
            prepared.append(
                _fit_candidate(
                    spec,
                    used,
                    cameras,
                    start.mids,
                    start.axle,
                    centre,
                    start.radius,
                    start.half_width,
                    typed is not None,
                )
            )
        except WheelFitError:
            continue
    if not prepared:
        raise WheelFitError("No wheel with this bar count fits the clicked bars.")
    candidates = _refine_candidates(prepared, typed, flipped)

    chosen, ambiguous = _choose(candidates, typed, spec.bar_count, cameras, flipped)
    params, _, slot_of = candidates[chosen]
    geometry = _geometry_from(params, typed, spec.bar_count)
    implied = None
    if typed is not None:
        problem = _problem(used, cameras, slot_of, math.radians(spec.pitch))
        free, _ = _refine(problem, np.concatenate((params[:6], [typed, params[-1]])), None)
        implied = abs(float(free[6]))
    return _report(geometry, used, cameras, bars, slot_of, implied, ambiguous, len(prepared))


def _refine_candidates(
    prepared: list[tuple[_Problem, np.ndarray, dict[int, int]]],
    radius: float | None,
    flipped: bool,
) -> list[tuple[np.ndarray, float, dict[int, int]]]:
    """Refine the candidates worth refining, the most promising first.

    A candidate starting many times worse than the best is the mirror of a
    wheel the bars already decide: genuinely ambiguous pairs start within a
    few times of each other, a hopeless mirror hundreds of times apart. It is
    refined only when the user asked for the mirror with Flip.
    """
    costs = [
        float(0.5 * np.sum(_residuals(start, problem, radius) ** 2))
        for problem, start, _ in prepared
    ]
    order = sorted(range(len(prepared)), key=costs.__getitem__)
    floor = max(costs[order[0]], 1e-12)
    out: list[tuple[np.ndarray, float, dict[int, int]]] = []
    for index in order:
        if out and not flipped and costs[index] > _HOPELESS_START_RATIO * floor:
            continue
        problem, start, slot_of = prepared[index]
        params, cost = _refine(problem, start, radius)
        out.append((params, cost, slot_of))
    return out


def _choose(
    candidates: list[tuple[np.ndarray, float, dict[int, int]]],
    radius: float | None,
    bar_count: int,
    cameras: Mapping[str, CameraModel],
    flipped: bool,
) -> tuple[int, bool]:
    """Index of the candidate to use, and whether the choice was close."""
    if len(candidates) == 1:
        return 0, False
    costs = [cost for _, cost, _ in candidates]
    best = int(np.argmin(costs))
    worst = 1 - best
    ambiguous = costs[worst] <= max(costs[best], 1e-12) * _AMBIGUOUS_COST_RATIO
    if ambiguous:
        # The bars a camera sees face it, so the axle lies beyond them.
        viewers = np.mean([camera_centre(c) for c in cameras.values()], axis=0)
        centres = [
            np.asarray(_geometry_from(p, radius, bar_count).centre) for p, _, _ in candidates
        ]
        best = int(np.argmax([np.linalg.norm(c - viewers) for c in centres]))
        worst = 1 - best
    return (worst if flipped else best), ambiguous


def _report(
    geometry: WheelGeometry,
    clicks: Sequence[EndClick],
    cameras: Mapping[str, CameraModel],
    bars: Mapping[int, tuple[np.ndarray, np.ndarray]],
    slot_of: Mapping[int, int],
    implied: float | None,
    ambiguous: bool,
    candidates: int,
) -> WheelFit:
    ends = geometry.bar_ends()
    residuals = []
    for click in clicks:
        slot = slot_of.get(click.bar)
        if slot is None:
            continue
        point = ends[slot % geometry.bar_count, SIDES.index(click.side)]
        for camera, x, y in click.views:
            if camera in cameras:
                pixel = cameras[camera].project(point)[0]
                error = float(np.hypot(pixel[0] - x, pixel[1] - y))
                residuals.append(ClickResidual(click.bar, click.side, camera, error))
    x_axis, y_axis, z_axis = geometry.basis()
    centre = np.asarray(geometry.centre)
    spacing, parallel, indices = [], [], []
    for bar in sorted(bars):
        left, right = bars[bar]
        radial = (left + right) / 2.0 - centre
        angle = math.degrees(math.atan2(float(radial @ y_axis), float(radial @ x_axis)))
        slot_angle = slot_of[bar] * 360.0 / geometry.bar_count
        spacing.append((angle - slot_angle + 180.0) % 360.0 - 180.0)
        cosine = float(abs(_unit(right - left) @ z_axis))
        parallel.append(math.degrees(math.acos(min(1.0, cosine))))
        indices.append(slot_of[bar])
    return WheelFit(
        geometry=geometry,
        indices=tuple(indices),
        residuals=tuple(residuals),
        spacing_deg=tuple(spacing),
        parallel_deg=tuple(parallel),
        implied_radius=implied,
        ambiguous=ambiguous,
        can_flip=candidates > 1,
    )


#: Bars 1 and 2 -- the least a labelled wheel needs.
_REQUIRED_BARS = 2


@dataclass(frozen=True)
class LabelledFit:
    """The wheel a user's clicks describe, and what had to give way for it (D-122, D-123)."""

    fit: WheelFit
    #: Why bar 3 was left out of the fit -- the fit's own error, or "" when it
    #: fitted but disagreed with bars 1 and 2. None when it was not left out.
    dropped_third: str | None = None
    #: Whether a typed radius contradicted the clicks and gave way to theirs.
    radius_from_clicks: bool = False


def fit_labelled(
    spec: WheelSpec,
    clicks: Sequence[EndClick],
    cameras: Mapping[str, CameraModel],
    *,
    flipped: bool = False,
) -> LabelledFit:
    """Fit the wheel the clicks describe, trying less of the input only when it must.

    In order, the first plausible fit (:func:`fit_issue`) winning: every located
    bar with the typed radius; bars 1 and 2 alone; every bar with the radius
    the clicks imply; bars 1 and 2 with it. When none is plausible, the first
    fit that exists is returned -- the user sees it however poor. Raises
    :class:`WheelFitError` only when no fit exists at all.
    """
    first = [click for click in clicks if click.bar < _REQUIRED_BARS]
    free = dataclasses.replace(spec, radius=None) if spec.known_radius is not None else None
    attempts: list[tuple[Sequence[EndClick], WheelSpec, bool]] = [(clicks, spec, False)]
    if len(first) < len(clicks):
        attempts.append((first, spec, True))
    if free is not None:
        attempts.append((clicks, free, False))
        if len(first) < len(clicks):
            attempts.append((first, free, True))
    best: WheelFit | None = None
    error: WheelFitError | None = None
    for used, used_spec, dropped in attempts:
        try:
            fit = fit_wheel(used_spec, used, cameras, flipped=flipped)
        except WheelFitError as failure:
            error = error or failure
            continue
        best = best or fit
        if fit_issue(fit, clicks) is None:
            return LabelledFit(
                fit,
                dropped_third=(str(error) if error is not None else "") if dropped else None,
                radius_from_clicks=used_spec is free,
            )
    if best is None:
        raise error or WheelFitError("No wheel fits the clicked bars.")
    return LabelledFit(best)
