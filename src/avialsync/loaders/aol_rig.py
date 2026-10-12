"""The AOL rig's calibrated wheel and camera correction (D-226).

The wheel-calibration analysis publishes one bundle: the native calibration, a
SideCam image correction fitted on it, and the wheel geometry fitted through
both. Its rotation model (:mod:`avialsync.loaders.aol_rotary_calibration`)
names that bundle's fingerprint, so the three are only used together: a model
fitted on another geometry gets none of them.

Only this module knows the bundle's JSON schemas; the rest of AvialSync sees a
generic :class:`ImageCorrection`, :class:`CameraModel` and
:class:`WheelGeometry`.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import json
from typing import Any

from avialsync.core.calibration import ImageCorrection, parse_calibration
from avialsync.core.source import CameraCorrectionHint
from avialsync.core.wheel import WheelGeometry
from avialsync.loaders import aol_rig_bundle

__all__ = ["GEOMETRY_SOURCE", "camera_corrections", "fingerprint", "rig_geometry"]

#: How a wheel names the rig's geometry.
GEOMETRY_SOURCE = f"AOL rig wheel (geometry {aol_rig_bundle.FINGERPRINT[:8]})"
#: Pixels are divided by this before the residual field is evaluated.
_RESIDUAL_SCALE = 720.0


def _file(name: str) -> bytes:
    return base64.b64decode(aol_rig_bundle.FILES_BASE64[name])


def fingerprint() -> str:
    """The bundle's SHA-256, computed as the analysis computes it."""
    return hashlib.sha256(b"".join(_file(name) for name in aol_rig_bundle.NAMES)).hexdigest()


def _json(name: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(_file(name).decode("utf-8"))
    return document


@functools.cache
def rig_geometry() -> WheelGeometry:
    """The wheel in the native calibration's world frame; bar 0 at absolute turn 0."""
    shape = _json("wheel_geometry.json")["geometry"]
    return WheelGeometry(
        centre=tuple(float(v) for v in shape["centre"]),  # type: ignore[arg-type]
        axle=tuple(float(v) for v in shape["axle"]),  # type: ignore[arg-type]
        zero=tuple(float(v) for v in shape["zero"]),  # type: ignore[arg-type]
        radius=float(shape["radius"]),
        half_width=float(shape["half_width"]),
        bar_count=int(shape["bar_count"]),
    )


@functools.cache
def camera_corrections() -> tuple[CameraCorrectionHint, ...]:
    """Each corrected camera with the native camera its correction was fitted on."""
    native = parse_calibration(_file("calibration.toml").decode("utf-8"), "calibration.toml")
    out = []
    for name, entry in _json("projection_model.json")["cameras"].items():
        camera = native.camera(name)
        if camera is None or "image_affine" not in entry:
            continue
        correction = ImageCorrection(
            affine=tuple(tuple(float(v) for v in row) for row in entry["image_affine"]),  # type: ignore[misc]
            control_pixels=tuple((float(x), float(y)) for x, y in entry.get("control_pixels", ())),
            displacements=tuple(
                (float(x), float(y)) for x, y in entry.get("residual_displacements_px", ())
            ),
            smoothing=float(entry.get("smoothing") or 0.0),
            scale=_RESIDUAL_SCALE,
            size=tuple(int(v) for v in entry["image_size"]),  # type: ignore[arg-type]
            source=f"AOL rig {name} correction (geometry {aol_rig_bundle.FINGERPRINT[:8]})",
        )
        out.append(CameraCorrectionHint(camera, correction))
    return tuple(out)
