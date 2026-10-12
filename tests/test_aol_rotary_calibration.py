"""AOL-only conversion of its persisted wheel model into the generic API."""

from __future__ import annotations

import json
import math

import pytest

from avialsync.core.errors import RotaryCalibrationError
from avialsync.loaders.aol_rotary_calibration import proposal_from_file


def _model(*, lag_s: float = 0.0) -> dict[str, object]:
    return {
        "schema": "wheel_rotation_v2",
        "family": "cyclic_nominal",
        "parameter_names": [
            "lag_s",
            "phase_rad",
            "angle_gain",
            "cyclic_sin_1",
            "cyclic_cos_1",
            "cyclic_sin_2",
            "cyclic_cos_2",
        ],
        "parameters": [lag_s, 0.2, 1.1, 0.01, -0.02, 0.03, -0.04],
        "encoder_reference_rad": 0.4,
        "fit": {"clicks": 42},
    }


def test_aol_model_becomes_a_generic_positive_transfer_with_external_direction(tmp_path) -> None:
    path = tmp_path / "model.json"
    path.write_text(json.dumps(_model()), encoding="utf-8")

    proposal = proposal_from_file(path)

    assert proposal.sign == -1.0
    assert proposal.observation_count == 42
    assert proposal.motion_model.gain == pytest.approx(1.1)
    assert proposal.motion_model.offset_degrees == pytest.approx(-math.degrees(1.1 * 0.4 + 0.2))
    first, second = proposal.motion_model.harmonics
    assert (first.sine_degrees, first.cosine_degrees) == pytest.approx(
        (-math.degrees(0.01), math.degrees(0.02))
    )
    assert (second.sine_degrees, second.cosine_degrees) == pytest.approx(
        (-math.degrees(0.03), math.degrees(0.04))
    )
    encoder_rad = 1.2
    external = -1.1 * (encoder_rad - 0.4) + 0.2
    external += 0.01 * math.sin(encoder_rad) - 0.02 * math.cos(encoder_rad)
    external += 0.03 * math.sin(2.0 * encoder_rad) - 0.04 * math.cos(2.0 * encoder_rad)
    converted = proposal.sign * proposal.motion_model.angle_degrees(math.degrees(encoder_rad))
    assert converted == pytest.approx(math.degrees(external))


def test_aol_model_refuses_a_lag_that_cannot_be_a_rotation_transfer(tmp_path) -> None:
    path = tmp_path / "model.json"
    path.write_text(json.dumps(_model(lag_s=0.002)), encoding="utf-8")
    with pytest.raises(RotaryCalibrationError, match="lag"):
        proposal_from_file(path)


def test_aol_session_offers_its_configured_model_without_applying_it(tmp_path) -> None:
    from avialsync.loaders.aol_pairing import configure_aol
    from avialsync.loaders.aol_session_loader import AOLManifest, _rotary_hint

    model = tmp_path / "model.json"
    model.write_text(json.dumps(_model()), encoding="utf-8")
    encoder = tmp_path / "encoder_log.txt"
    encoder.write_text("09:35:26:000 0 0 0\n", encoding="utf-8")
    try:
        configure_aol({"wheel_calibration_model": str(model)})
        hint = _rotary_hint(AOLManifest(session_dir=tmp_path, encoder_file=encoder))
    finally:
        configure_aol({})

    assert hint is not None
    assert hint.motion_model is not None
    assert hint.motion_sign == -1.0
