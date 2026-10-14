"""Degenerate geometry and failed numerical fits cannot manufacture apparatus facts."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from avialsync.core import calibration, ladder_support, rotary_calibration
from avialsync.core.belt_rollers import BeltRollers, BeltSideView, rollers_from_corners
from avialsync.core.errors import CalibrationError, PropModelError, RotaryCalibrationError
from avialsync.core.rotary_calibration import RotaryObservation, fit_periodic_rotary
from avialsync.core.rotary_motion import PeriodicRotaryMotion, RotaryHarmonic

ROLLERS = BeltRollers((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), 1, 2, (0.0, 1.0, 0.0))


@pytest.mark.parametrize(
    "changes", [{"radius": 0}, {"second": ROLLERS.first}, {"top_normal": (1.0, 0.0, 0.0)}]
)
def test_roller_dimensions_and_axes_are_validated(changes) -> None:
    with pytest.raises(PropModelError):
        replace(ROLLERS, **changes)


def test_invalid_travel_tessellation_and_corner_geometry_are_rejected() -> None:
    with pytest.raises(PropModelError):
        ROLLERS.point_at(np.inf)
    with pytest.raises(ValueError):
        ROLLERS.sample_distances(1)
    for corners in [((0, 0, 0),), ((0, 0, 0),) * 4]:
        with pytest.raises(PropModelError):
            rollers_from_corners(corners, 1, None, (0, 0, 1))
    corners = ((0, 0, 0), (0, 2, 0), (10, 0, 0), (10, 2, 0))
    rollers, span, error = rollers_from_corners(corners, 1, None, (0, 0, -1))
    assert rollers.top_normal[2] < 0 and span == 10 and error == 0


@pytest.mark.parametrize("args", [("", 0, ((0, 0),) * 4), ("camera", 0, ((np.nan, 0),) * 4)])
def test_invalid_side_view_clicks_are_rejected(args) -> None:
    with pytest.raises(PropModelError):
        BeltSideView(*args)


def test_incomplete_or_degenerate_ladder_patterns_preserve_clicked_steps() -> None:
    a = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    b = ((0.0, 1.0, 0.0), (1.0, 1.0, 0.0))
    assert ladder_support.support_bars([(a[0],), a, b], "side_rails") == (
        (a[0], b[0]),
        (a[1], b[1]),
    )
    for steps, pattern in [([a, a], (0, 1, 3)), ([a], (0, 3, 3)), ([a, (None, None)], (0, 1, 3))]:
        assert ladder_support.lay_out_rungs(steps, pattern).generated == ()
    assert ladder_support._pair(a, (None, b[1])) == (None, b[1])
    layout = ladder_support.lay_out_rungs([a, b, (None, None)], (0, 1, 4))
    assert len(layout.generated) == 2 and len(layout.walkway) == 4


def test_image_correction_without_independent_controls_is_affine_only() -> None:
    affine = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    values = np.array([[3.0, 4.0]])
    for controls in [(), ((0, 0), (1, 1), (2, 2))]:
        correction = calibration.ImageCorrection(affine, controls, tuple((0, 0) for _ in controls))
        np.testing.assert_array_equal(correction.apply(values), values)
    assert calibration.Calibration(()).camera("absent") is None
    with pytest.raises(CalibrationError):
        calibration.parse_calibration("[not closed")


@pytest.mark.parametrize(
    "options",
    [
        {"reference_reading": np.inf},
        {"period_degrees": 0},
        {"initial_gain": 0},
        {"harmonic_orders": (0,)},
        {"harmonic_orders": (1, 1)},
        {"gain_tolerance": 1},
    ],
)
def test_rotary_fit_rejects_invalid_calibration_parameters(options) -> None:
    arguments = {"reference_reading": 0, "period_degrees": 10, **options}
    with pytest.raises(RotaryCalibrationError):
        fit_periodic_rotary([RotaryObservation(x, x) for x in (0, 1, 2)], **arguments)


def test_rotary_nonfinite_evidence_and_failed_solver_have_no_result(monkeypatch) -> None:
    with pytest.raises(RotaryCalibrationError, match="finite"):
        fit_periodic_rotary([RotaryObservation(np.nan, 0)], 0, 10)
    monkeypatch.setattr(
        rotary_calibration,
        "least_squares",
        lambda *args, **kwargs: SimpleNamespace(success=False, x=np.array([1])),
    )
    with pytest.raises(RotaryCalibrationError, match="converge"):
        fit_periodic_rotary([RotaryObservation(x, x) for x in (0, 1, 2)], 0, 10)
    empty = rotary_calibration.RotaryCalibrationProposal(PeriodicRotaryMotion(), 1)
    assert empty.rms_degrees is None
    with pytest.raises(ValueError):
        RotaryHarmonic(1, np.nan)
    with pytest.raises(ValueError):
        PeriodicRotaryMotion().angle_degrees(np.nan)
