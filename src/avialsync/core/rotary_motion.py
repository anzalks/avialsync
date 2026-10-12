"""Calibrated transfer functions for periodically imperfect rotary sensors.

Rotary encoders are often close to linear but can have repeatable eccentricity
or quantisation errors within a revolution.  This module describes that
instrument correction independently of a prop, rig, file format, or loader.
The caller owns source-specific units and direction: readings and output are
both degrees, the gain is positive, and a prop binding applies its verified
direction to the whole result.

Headless.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["PeriodicRotaryMotion", "RotaryHarmonic"]


@dataclass(frozen=True)
class RotaryHarmonic:
    """One sinusoidal correction term, expressed in output degrees.

    ``order`` is the number of cycles per input revolution.  Terms with the
    same order would be mathematically redundant and are rejected so a stored
    calibration has one unambiguous representation.
    """

    order: int
    sine_degrees: float = 0.0
    cosine_degrees: float = 0.0

    def __post_init__(self) -> None:
        if self.order < 1:
            raise ValueError("A rotary harmonic order must be at least one.")
        if not math.isfinite(self.sine_degrees) or not math.isfinite(self.cosine_degrees):
            raise ValueError("Rotary harmonic coefficients must be finite.")


@dataclass(frozen=True)
class PeriodicRotaryMotion:
    """Map an unwrapped encoder angle to a calibrated rotary angle.

    The calibrated angle is ``gain * reading + offset_degrees`` plus each
    harmonic's sine and cosine term.  Inputs and outputs use degrees.  A
    relative turn is evaluated at both readings rather than by scaling their
    difference, which retains periodic correction as the encoder crosses a
    revolution boundary.

    Direction intentionally is not a field here.  It belongs to the binding
    between this generic transfer and a visible prop, where video checks can
    verify and reverse it.
    """

    gain: float = 1.0
    offset_degrees: float = 0.0
    harmonics: tuple[RotaryHarmonic, ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(self.gain) or self.gain <= 0.0:
            raise ValueError("A rotary motion gain must be finite and positive.")
        if not math.isfinite(self.offset_degrees):
            raise ValueError("A rotary motion offset must be finite.")
        harmonics = tuple(self.harmonics)
        if len({term.order for term in harmonics}) != len(harmonics):
            raise ValueError("A rotary motion may contain each harmonic order only once.")
        object.__setattr__(self, "harmonics", harmonics)

    def angle_degrees(self, reading: float) -> float:
        """Return calibrated angle at finite unwrapped encoder *reading*."""
        value = float(reading)
        if not math.isfinite(value):
            raise ValueError("A rotary encoder reading must be finite.")
        angle = self.gain * value + self.offset_degrees
        base = math.radians(value)
        for term in self.harmonics:
            phase = term.order * base
            angle += term.sine_degrees * math.sin(phase)
            angle += term.cosine_degrees * math.cos(phase)
        return angle

    def relative_turn_degrees(self, reading: float, reference: float) -> float:
        """Return calibrated turn from *reference* to *reading*, in degrees."""
        return self.angle_degrees(reading) - self.angle_degrees(reference)
