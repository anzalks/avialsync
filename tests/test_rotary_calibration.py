"""Tests for generic fitting of cyclic rotary observations."""

from __future__ import annotations

import pytest

from avialsync.core.errors import RotaryCalibrationError
from avialsync.core.rotary_calibration import RotaryObservation, fit_periodic_rotary
from avialsync.core.rotary_motion import PeriodicRotaryMotion, RotaryHarmonic


def _observations(
    model: PeriodicRotaryMotion, sign: float, reference: float
) -> list[RotaryObservation]:
    readings = (3.0, 17.0, 41.0, 63.0, 92.0, 126.0, 159.0, 201.0, 244.0, 288.0, 331.0)
    return [
        RotaryObservation(
            reading,
            sign * model.relative_turn_degrees(reading, reference) % 10.0,
        )
        for reading in readings
    ]


def test_periodic_fit_recovers_direction_gain_and_harmonics_from_cyclic_observations() -> None:
    truth = PeriodicRotaryMotion(
        gain=1.07,
        harmonics=(
            RotaryHarmonic(1, sine_degrees=0.7, cosine_degrees=-0.4),
            RotaryHarmonic(2, sine_degrees=0.2, cosine_degrees=0.3),
        ),
    )
    proposal = fit_periodic_rotary(
        _observations(truth, -1.0, 0.0),
        0.0,
        10.0,
        initial_gain=1.0,
        harmonic_orders=(1, 2),
    )
    assert proposal.sign == -1.0
    assert proposal.motion_model.gain == pytest.approx(truth.gain, abs=1e-5)
    assert [term.sine_degrees for term in proposal.motion_model.harmonics] == pytest.approx(
        [term.sine_degrees for term in truth.harmonics], abs=1e-5
    )
    assert [term.cosine_degrees for term in proposal.motion_model.harmonics] == pytest.approx(
        [term.cosine_degrees for term in truth.harmonics], abs=1e-5
    )
    assert proposal.rms_degrees == pytest.approx(0.0, abs=1e-5)


def test_periodic_fit_rejects_too_few_observations_or_no_encoder_span() -> None:
    with pytest.raises(RotaryCalibrationError, match="needed"):
        fit_periodic_rotary([RotaryObservation(0.0, 0.0)] * 2, 0.0, 10.0)
    observations = [RotaryObservation(20.0, float(index)) for index in range(3)]
    with pytest.raises(RotaryCalibrationError, match="span"):
        fit_periodic_rotary(observations, 0.0, 10.0)


def test_proposal_reports_cyclic_residuals() -> None:
    proposal = fit_periodic_rotary(
        [RotaryObservation(value, value % 10.0) for value in (0.0, 11.0, 22.0)],
        0.0,
        10.0,
    )
    assert proposal.observation_count == 3
    assert proposal.max_abs_degrees == pytest.approx(0.0)
    assert proposal.rms_degrees == pytest.approx(0.0)
