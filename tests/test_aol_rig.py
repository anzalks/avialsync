"""The AOL rig's published wheel bundle, as the AOL plugin hands it over (D-226)."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from avialsync.loaders import aol_rig, aol_rig_bundle
from avialsync.loaders.aol_rotary_calibration import _DEFAULT_MODEL


def test_the_embedded_bundle_is_the_one_the_default_wheel_model_was_fitted_on() -> None:
    assert aol_rig.fingerprint() == aol_rig_bundle.FINGERPRINT
    assert aol_rig.fingerprint() == _DEFAULT_MODEL["geometry_fingerprint"]


def test_rig_geometry_is_the_published_wheel() -> None:
    geometry = aol_rig.rig_geometry()
    assert geometry.bar_count == 50
    assert geometry.radius == pytest.approx(182.33830991148437)
    assert np.linalg.norm(geometry.axle) == pytest.approx(1.0, abs=1e-9)
    assert abs(float(np.dot(geometry.axle, geometry.zero))) < 1e-6


def test_only_sidecam_carries_a_correction_and_it_inverts() -> None:
    hints = aol_rig.camera_corrections()
    assert [hint.camera.name for hint in hints] == ["SideCam"]
    correction = hints[0].correction
    assert correction.size == (1440, 1080)
    pixels = np.asarray([[400.0, 300.0], [900.0, 650.0]])
    assert correction.invert(correction.apply(pixels)) == pytest.approx(pixels, abs=1e-3)


def _hint(tmp_path, values):
    from avialsync.loaders.aol_pairing import configure_aol
    from avialsync.loaders.aol_session_loader import AOLManifest, _rotary_hint

    encoder = tmp_path / "encoder_log.txt"
    encoder.write_text("09:35:26:000 0 0 0\n", encoding="utf-8")
    try:
        configure_aol(values)
        return _rotary_hint(AOLManifest(session_dir=tmp_path, encoder_file=encoder))
    finally:
        configure_aol({})


def test_the_rig_wheel_comes_only_with_a_model_fitted_on_it(tmp_path) -> None:
    hint = _hint(tmp_path, {})
    assert hint is not None and hint.geometry == aol_rig.rig_geometry()
    assert hint.geometry_source == aol_rig.GEOMETRY_SOURCE

    other = dict(_DEFAULT_MODEL, geometry_fingerprint="0" * 64)
    path = tmp_path / "model.json"
    path.write_text(json.dumps(other), encoding="utf-8")
    hint = _hint(tmp_path, {"wheel_calibration_model": str(path)})
    assert hint is not None and hint.motion_model is not None
    assert hint.geometry is None, "a model fitted on another geometry gets none of this one"
    assert math.isfinite(hint.motion_model.gain)
