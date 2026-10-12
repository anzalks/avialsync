"""AOL's adapter from its saved wheel model to the generic rotary proposal.

The JSON schema, radians, and direction convention are AOL acquisition facts.
Only this adapter knows them; the rest of AvialSync receives a generic
``PeriodicRotaryMotion`` proposal expressed in degrees.

The rig's own fitted model is built in (D-224) and is the AOL default; a
configured model file replaces it.
"""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path
from typing import Any

from avialsync.core.errors import RotaryCalibrationError
from avialsync.core.rotary_calibration import RotaryCalibrationProposal
from avialsync.core.rotary_motion import PeriodicRotaryMotion, RotaryHarmonic

__all__ = [
    "DEFAULT_SOURCE",
    "configure_model",
    "configured_model",
    "proposal_from_file",
    "proposal_from_payload",
]

_configured_model: Path | None = None
_PARAMETERS = (
    "lag_s",
    "phase_rad",
    "angle_gain",
    "cyclic_sin_1",
    "cyclic_cos_1",
    "cyclic_sin_2",
    "cyclic_cos_2",
)


def configure_model(value: object) -> None:
    """Set the optional AOL model file used by later session scans."""
    text = str(value or "").strip()
    global _configured_model
    _configured_model = Path(text).expanduser() if text else None


#: The AOL rig's wheel model as fitted by the wheel-calibration tool
#: (``tools/wheel_calibration/data/encoder/model.json`` of the
#: anzal_wheel_kinematics_analysis repository): 3186 SideCam rod-end clicks on
#: the corrected geometry ``7c55238f…``; lag and gain fixed at their hardware
#: values, the phase and two periodic terms fitted; median 6.0 px, residual lag
#: -0.10 ± 0.15 ms. It holds only while the cameras, wheel and encoder mounting
#: are unchanged; a refitted model is configured as a file instead.
_DEFAULT_MODEL: dict[str, Any] = {
    "schema": "wheel_rotation_v2",
    "family": "cyclic_nominal",
    "parameter_names": list(_PARAMETERS),
    "parameters": [
        0.0,
        -0.02887559305867779,
        1.0,
        -0.005922971076449978,
        -0.0015272853543092419,
        0.02721289695333099,
        -0.028215485045811815,
    ],
    "geometry_fingerprint": "7c55238f36edc1a45140045d367b17f0196cfeabff8416cb4afcfbb4d1612f3f",
    "encoder_reference_rad": 0.8640384474893164,
    "fit": {"clicks": 3186},
}

#: How a wheel names the built-in model.
DEFAULT_SOURCE = "AOL default wheel model (geometry 7c55238f)"


def configured_model() -> RotaryCalibrationProposal:
    """The configured model file's proposal, else the built-in AOL default."""
    if _configured_model is None:
        return dataclasses.replace(proposal_from_payload(_DEFAULT_MODEL), source=DEFAULT_SOURCE)
    proposal = proposal_from_file(_configured_model)
    return dataclasses.replace(proposal, source=f"AOL wheel model {_configured_model.name}")


def _parameters(payload: dict[str, Any]) -> dict[str, float]:
    if payload.get("schema") != "wheel_rotation_v2" or payload.get("family") != "cyclic_nominal":
        raise RotaryCalibrationError("not an AOL wheel_rotation_v2 cyclic_nominal model")
    names = payload.get("parameter_names")
    values = payload.get("parameters")
    if not isinstance(names, list) or not isinstance(values, list) or len(names) != len(values):
        raise RotaryCalibrationError("model parameters are missing or inconsistent")
    try:
        named = {str(name): float(value) for name, value in zip(names, values, strict=True)}
    except (TypeError, ValueError) as error:
        raise RotaryCalibrationError("model parameters must be numbers") from error
    missing = [name for name in _PARAMETERS if name not in named]
    if missing:
        raise RotaryCalibrationError(f"model is missing {', '.join(missing)}")
    if not all(math.isfinite(value) for value in named.values()):
        raise RotaryCalibrationError("model parameters must be finite")
    return named


def proposal_from_file(path: Path) -> RotaryCalibrationProposal:
    """Read an AOL model file; see :func:`proposal_from_payload`."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RotaryCalibrationError("model is not valid JSON") from error
    if not isinstance(payload, dict):
        raise RotaryCalibrationError("model root must be an object")
    return proposal_from_payload(payload)


def proposal_from_payload(payload: dict[str, Any]) -> RotaryCalibrationProposal:
    """Convert AOL's calibrated-radian model to the generic degree proposal.

    AOL writes ``-gain * encoder + phase + periodic terms``.  Generic motion
    keeps a positive encoder transfer and stores direction on the binding, so
    the periodic coefficients and constant are transformed before applying a
    direction of ``-1``.  A non-zero lag has no representation in a rotation
    model and is refused rather than folded into a source timing map.
    """
    parameters = _parameters(payload)
    if not math.isclose(parameters["lag_s"], 0.0, abs_tol=1e-9):
        raise RotaryCalibrationError("a non-zero model lag must be reviewed as source timing")
    gain = parameters["angle_gain"]
    if gain <= 0.0:
        raise RotaryCalibrationError("model angle_gain must be positive")
    try:
        reference = float(payload.get("encoder_reference_rad", 0.0))
    except (TypeError, ValueError) as error:
        raise RotaryCalibrationError("model encoder_reference_rad must be a number") from error
    if not math.isfinite(reference):
        raise RotaryCalibrationError("model encoder_reference_rad must be finite")
    model = PeriodicRotaryMotion(
        gain=gain,
        offset_degrees=-math.degrees(gain * reference + parameters["phase_rad"]),
        harmonics=(
            RotaryHarmonic(
                1,
                sine_degrees=-math.degrees(parameters["cyclic_sin_1"]),
                cosine_degrees=-math.degrees(parameters["cyclic_cos_1"]),
            ),
            RotaryHarmonic(
                2,
                sine_degrees=-math.degrees(parameters["cyclic_sin_2"]),
                cosine_degrees=-math.degrees(parameters["cyclic_cos_2"]),
            ),
        ),
    )
    fit = payload.get("fit")
    try:
        observations = int(fit.get("clicks", 0)) if isinstance(fit, dict) else 0
    except (TypeError, ValueError) as error:
        raise RotaryCalibrationError("model fit clicks must be an integer") from error
    return RotaryCalibrationProposal(model, sign=-1.0, observation_count=max(0, observations))
