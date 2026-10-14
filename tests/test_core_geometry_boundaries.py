"""Numerical and visibility boundaries retain only identifiable, finite geometry."""

import numpy as np
import pytest

from avialsync.core import alignment, calibration, ladder_support, rotary_calibration
from avialsync.core.belt_rollers import BeltRollers
from avialsync.core.errors import PropModelError, RotaryCalibrationError, SyncEvidenceError
from avialsync.core.physical_props import BeltTrack
from avialsync.core.rotary_calibration import RotaryObservation
from avialsync.core.sync import SyncFit, SyncMatch, SyncProposal


def test_nonfinite_rollers_and_rounded_path_end_have_explicit_outcomes() -> None:
    with pytest.raises(PropModelError, match="finite"):
        BeltRollers((np.nan, 0.0, 0.0), (10.0, 0.0, 0.0), 1, 2, (0.0, 1.0, 0.0))
    track = BeltTrack(((0.0, 0.0, 0.0), (1e16, 0.0, 0.0), (1e16, 3.0, 0.0), (1e16, 7.0, 0.0)))
    assert track.material_point(track.length, 0) == track.vertices[-1]


def test_camera_decomposition_corrects_a_reflected_projection() -> None:
    projection = np.column_stack((-np.eye(3), np.array([1.0, 2.0, 3.0])))
    intrinsic, rotation, translation = calibration._decompose(projection)
    assert np.linalg.det(rotation) == pytest.approx(1)
    recomposed = intrinsic @ np.column_stack((rotation, translation))
    np.testing.assert_allclose(recomposed, -projection)


def test_ladder_extrapolation_keeps_horizon_and_known_missing_rungs_empty() -> None:
    near, far = ((0.0, 0.0), (1.0, 0.0)), ((0.0, 1.5), (1.5, 1.5))
    layout = ladder_support.lay_out_rungs([near, far, (None, None)], (0, 1, 5), (0, 1, 2))
    assert len(layout.walkway) == 2
    assert all(a is None and b is None for _, (a, b) in layout.generated)
    assert ladder_support.rung_places([near, far, ((0.0, -4.0),)], (0, 1, 5))[-1] is None


def test_rank_deficient_periodic_evidence_cannot_identify_harmonic_corrections() -> None:
    observations = [RotaryObservation(float(index * 360), 0) for index in range(7)]
    with pytest.raises(RotaryCalibrationError, match="enough encoder positions"):
        rotary_calibration.fit_periodic_rotary(observations, 0, 10, harmonic_orders=(1,))


def test_piecewise_adapter_refuses_nonchronological_matched_evidence(monkeypatch) -> None:
    fit = SyncFit(0, 0, 0, 0, 5, 0)
    matches = tuple(SyncMatch(float(i), float(i), 0) for i in (0, 1, 1, 3, 4))
    proposal = SyncProposal("a", "b", fit, matches, 0.001)
    monkeypatch.setattr(alignment, "fit_sync_events", lambda *args, **kwargs: proposal)
    with pytest.raises(SyncEvidenceError, match="strictly increasing"):
        alignment.fit_piecewise(np.arange(5.0), np.arange(5.0), reference_id="a", target_id="b")
