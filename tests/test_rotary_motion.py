"""Tests for reusable calibrated rotary transfer functions."""

from __future__ import annotations

import math

import pytest

from avialsync.core.rotary_motion import PeriodicRotaryMotion, RotaryHarmonic


def test_periodic_motion_keeps_harmonic_correction_in_a_relative_turn() -> None:
    motion = PeriodicRotaryMotion(
        gain=1.1,
        offset_degrees=47.0,
        harmonics=(
            RotaryHarmonic(1, sine_degrees=2.0, cosine_degrees=-3.0),
            RotaryHarmonic(2, sine_degrees=0.5),
        ),
    )
    expected = (1.1 * 90.0) + (2.0 * math.sin(math.pi / 2)) + 3.0
    assert motion.relative_turn_degrees(90.0, 0.0) == pytest.approx(expected)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"gain": 0.0}, "positive"),
        ({"offset_degrees": math.nan}, "finite"),
        ({"harmonics": (RotaryHarmonic(1), RotaryHarmonic(1))}, "only once"),
    ],
)
def test_periodic_motion_rejects_ambiguous_or_invalid_calibrations(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        PeriodicRotaryMotion(**kwargs)


@pytest.mark.parametrize("order", [0, -1])
def test_harmonic_order_must_be_positive(order: int) -> None:
    with pytest.raises(ValueError, match="at least one"):
        RotaryHarmonic(order)
