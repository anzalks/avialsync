"""Fit reusable rotary-transfer models from observed cyclic angles.

The fitter has no knowledge of a prop, camera, or data-source format.  An
adapter turns its own evidence into :class:`RotaryObservation`: an unwrapped
encoder reading and the observed output angle modulo a known cycle.  That keeps
the mathematical calibration reusable while the source of an observation and
its review workflow remain where they belong.

The returned result is a proposal.  Callers must show its residuals and obtain
an explicit acceptance before changing a visible prop.

Headless.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from avialsync.core.errors import RotaryCalibrationError
from avialsync.core.rotary_motion import PeriodicRotaryMotion, RotaryHarmonic

__all__ = [
    "RotaryCalibrationProposal",
    "RotaryObservation",
    "fit_periodic_rotary",
]


@dataclass(frozen=True)
class RotaryObservation:
    """One observed rotary angle at an unwrapped encoder *reading*.

    ``angle_degrees`` is cyclic: it lies in ``[0, period_degrees)`` and need
    not identify which visually identical feature was observed.  It is enough
    for a periodic transfer fit, provided readings span enough motion.
    """

    reading: float
    angle_degrees: float


@dataclass(frozen=True)
class RotaryCalibrationProposal:
    """A transfer proposed from observations, before a caller accepts it."""

    motion_model: PeriodicRotaryMotion
    sign: float
    observation_count: int = 0
    residuals_degrees: tuple[float, ...] = ()

    @property
    def rms_degrees(self) -> float | None:
        """Root-mean-square cyclic residual, or None without observations."""
        if not self.residuals_degrees:
            return None
        mean_square = sum(value * value for value in self.residuals_degrees) / len(
            self.residuals_degrees
        )
        return math.sqrt(mean_square)

    @property
    def max_abs_degrees(self) -> float | None:
        """Largest cyclic residual magnitude, or None without observations."""
        return max((abs(value) for value in self.residuals_degrees), default=None)


def _wrap(values: np.ndarray, period: float) -> np.ndarray:
    return (values + period / 2.0) % period - period / 2.0


def _validate(
    observations: Sequence[RotaryObservation],
    reference_reading: float,
    period_degrees: float,
    harmonic_orders: Sequence[int],
    initial_gain: float,
) -> tuple[np.ndarray, np.ndarray, tuple[int, ...]]:
    """Validate inputs and return finite vectors and canonical harmonic orders."""
    if not math.isfinite(reference_reading):
        raise RotaryCalibrationError("The reference encoder reading must be finite.")
    if not math.isfinite(period_degrees) or period_degrees <= 0.0:
        raise RotaryCalibrationError("The observed rotation period must be positive.")
    if not math.isfinite(initial_gain) or initial_gain <= 0.0:
        raise RotaryCalibrationError("The starting rotary gain must be positive.")
    orders = tuple(int(order) for order in harmonic_orders)
    if any(order < 1 for order in orders) or len(set(orders)) != len(orders):
        raise RotaryCalibrationError("Correction orders must be distinct positive integers.")
    readings = np.asarray([item.reading for item in observations], dtype=np.float64)
    observed = np.asarray([item.angle_degrees for item in observations], dtype=np.float64)
    if not np.all(np.isfinite(readings)) or not np.all(np.isfinite(observed)):
        raise RotaryCalibrationError("Rotary observations must be finite.")
    parameters = 1 + 2 * len(orders)
    required = 2 * parameters + 1
    if len(readings) < required:
        raise RotaryCalibrationError(
            f"{required} observations are needed for this rotation model; "
            f"only {len(readings)} were collected."
        )
    if float(np.ptp(readings)) <= np.finfo(np.float64).eps:
        raise RotaryCalibrationError(
            "The selected frames do not span any encoder motion for calibration."
        )
    return readings, observed % period_degrees, orders


def _design(readings: np.ndarray, reference: float, harmonic_orders: Sequence[int]) -> np.ndarray:
    """Linear relative-transfer features before direction and cyclic wrapping."""
    columns = [readings - reference]
    for order in harmonic_orders:
        phase = np.radians(order * readings)
        reference_phase = math.radians(order * reference)
        columns.append(np.sin(phase) - math.sin(reference_phase))
        columns.append(np.cos(phase) - math.cos(reference_phase))
    return np.column_stack(columns)


def _initial_parameters(
    orders: Sequence[int], initial_gain: float, initial_model: PeriodicRotaryMotion | None
) -> np.ndarray:
    """Start from the accepted transfer when it has matching correction terms."""
    coefficients = {term.order: term for term in (initial_model.harmonics if initial_model else ())}
    gain = initial_model.gain if initial_model is not None else initial_gain
    values = [gain]
    for order in orders:
        term = coefficients.get(order)
        values.extend((0.0, 0.0) if term is None else (term.sine_degrees, term.cosine_degrees))
    return np.asarray(values, dtype=np.float64)


def _proposal(
    parameters: np.ndarray,
    sign: float,
    design: np.ndarray,
    observed: np.ndarray,
    period: float,
    orders: Sequence[int],
) -> RotaryCalibrationProposal:
    """Build the model and its cyclic residual record from one fitted vector."""
    harmonics = tuple(
        RotaryHarmonic(order, parameters[index], parameters[index + 1])
        for index, order in zip(range(1, len(parameters), 2), orders, strict=True)
    )
    model = PeriodicRotaryMotion(gain=float(parameters[0]), harmonics=harmonics)
    residuals = _wrap(observed - sign * (design @ parameters), period)
    return RotaryCalibrationProposal(
        motion_model=model,
        sign=sign,
        observation_count=len(observed),
        residuals_degrees=tuple(float(value) for value in residuals),
    )


def fit_periodic_rotary(
    observations: Sequence[RotaryObservation],
    reference_reading: float,
    period_degrees: float,
    *,
    initial_gain: float = 1.0,
    initial_sign: float = 1.0,
    harmonic_orders: Sequence[int] = (),
    initial_model: PeriodicRotaryMotion | None = None,
    gain_tolerance: float = 0.15,
) -> RotaryCalibrationProposal:
    """Fit a signed, periodic rotary transfer from cyclic angular observations.

    The fit compares the model's relative output with every observed angle
    modulo ``period_degrees``.  It tries both directions, retains a positive
    gain near the declared coarse transfer, uses robust residuals, and rejects
    rank-deficient evidence instead of manufacturing a correction.  An
    identical-bar click cannot distinguish a gain from one that adds an exact
    number of bar pitches between observations; ``gain_tolerance`` deliberately
    keeps the fit in the stated calibration neighbourhood.  Set the binding's
    coarse ratio first when it is not already known. The model's constant
    offset is deliberately zero: a relative turn makes it unidentifiable and
    the visible prop's reference pose is its authority.
    """
    readings, observed, orders = _validate(
        observations, reference_reading, period_degrees, harmonic_orders, initial_gain
    )
    design = _design(readings, reference_reading, orders)
    parameters = design.shape[1]
    if np.linalg.matrix_rank(design) != parameters:
        raise RotaryCalibrationError(
            "The selected frames do not span enough encoder positions for this rotation model."
        )
    if not math.isfinite(gain_tolerance) or not 0.0 < gain_tolerance < 1.0:
        raise RotaryCalibrationError("The rotary gain tolerance must be between zero and one.")
    start = _initial_parameters(orders, initial_gain, initial_model)
    signs = (1.0, -1.0) if initial_sign >= 0.0 else (-1.0, 1.0)
    lower = np.full(parameters, -np.inf, dtype=np.float64)
    upper = np.full(parameters, np.inf, dtype=np.float64)
    lower[0] = max(np.finfo(np.float64).eps, start[0] * (1.0 - gain_tolerance))
    upper[0] = start[0] * (1.0 + gain_tolerance)
    # Cyclic observations repeat at one visual period.  Explore the nearby
    # residual basins, but only around the declared transfer: a bar click
    # cannot say which otherwise-identical full turn occurred between frames.
    gain_step = period_degrees / float(np.ptp(readings))
    starts: list[np.ndarray] = []
    for multiple in range(-4, 5):
        start_candidate = start.copy()
        start_candidate[0] = float(np.clip(start[0] + multiple * gain_step, lower[0], upper[0]))
        starts.append(start_candidate)
    best: RotaryCalibrationProposal | None = None
    best_cost = math.inf
    for sign in signs:
        for start_values in starts:
            result = least_squares(
                lambda values, direction=sign: _wrap(
                    observed - direction * (design @ values), period_degrees
                ),
                start_values,
                bounds=(lower, upper),
                loss="soft_l1",
                f_scale=period_degrees / 10.0,
                x_scale="jac",
            )
            if not result.success or not np.all(np.isfinite(result.x)):
                continue
            proposal = _proposal(result.x, sign, design, observed, period_degrees, orders)
            cost = sum(value * value for value in proposal.residuals_degrees)
            if cost < best_cost:
                best = proposal
                best_cost = cost
    if best is None:
        raise RotaryCalibrationError(
            "The rotary fit did not converge; collect clearer observations."
        )
    return best
