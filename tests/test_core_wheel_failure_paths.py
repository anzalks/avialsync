"""Wheel fitting keeps imperfect evidence and refuses unavailable or degenerate solutions."""

import math
from dataclasses import replace

import numpy as np
import pytest

from avialsync.core import wheel_check, wheel_fit, wheel_fit_labelled
from avialsync.core.errors import CalibrationError, WheelFitError
from avialsync.core.wheel import (
    EncoderBinding,
    EndClick,
    WheelCheck,
    WheelFit,
    WheelSpec,
    fit_issue,
)
from tests.wheel_fixture import CAMERAS, TRUTH, clicks_for


def _fit() -> WheelFit:
    return WheelFit(TRUTH, (), (), (), ())


def test_zero_vector_and_unreachable_chord_do_not_invent_a_circle() -> None:
    with pytest.raises(WheelFitError):
        wheel_fit._unit(np.zeros(3))
    centres = wheel_fit._candidate_centres(np.array([[0.0, 0.0], [4.0, 0.0]]), 1)
    np.testing.assert_array_equal(centres, [[2.0, 0.0]])
    assert fit_issue(_fit(), ()) == "clicks_far_from_fit"


def test_failed_triangulation_and_candidate_fit_do_not_produce_geometry(monkeypatch) -> None:
    def failed(*args, **kwargs):
        raise CalibrationError("parallel views")

    clicks = clicks_for([0, 1])
    with monkeypatch.context() as patch:
        patch.setattr(wheel_fit, "triangulate", failed)
        assert wheel_fit._triangulated_bars(clicks, CAMERAS) == {}

    def invalid(*args, **kwargs):
        raise WheelFitError("impossible geometry")

    monkeypatch.setattr(wheel_fit, "_fit_candidate", invalid)
    with pytest.raises(WheelFitError, match="No wheel"):
        wheel_fit.fit_wheel(WheelSpec("wheel", 36), clicks, CAMERAS)


def test_unavailable_cameras_and_unlabelled_bars_are_ignored_consistently() -> None:
    click = EndClick(0, "left").with_view("missing", 1, 2)
    problem = wheel_fit._problem((click, replace(click, bar=1)), CAMERAS, {0: 0}, 0.1)
    assert problem.observed.size == 0 and not problem.groups
    report = wheel_fit._report(
        TRUTH, (click, replace(click, bar=1)), CAMERAS, {}, {0: 0}, None, False, 1
    )
    assert not report.residuals


def test_unambiguous_candidate_selection_uses_residual_cost() -> None:
    params = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 100.0, 25.0])
    candidates = [(params, 1.0, {}), (params.copy(), 10.0, {})]
    assert wheel_fit._choose(candidates, None, 36, CAMERAS, False) == (0, False)


def test_labelled_recovery_retains_best_imperfect_fit_and_contradicted_measurement() -> None:
    fit = _fit()
    spec = WheelSpec("wheel", 36)
    result = wheel_fit_labelled.fit_labelled(
        spec,
        (),
        CAMERAS,
        flipped=False,
        fitter=lambda *args, **kwargs: fit,
        quality=lambda *args: "clicks_far_from_fit",
    )
    assert result.fit is fit
    contradicted = replace(fit, implied_radius=1000)

    def fitter(used_spec, *args, **kwargs):
        if used_spec.known_radius is None:
            raise WheelFitError("free radius is underdetermined")
        return contradicted

    result = wheel_fit_labelled.fit_labelled(
        replace(spec, radius=10, units="mm"),
        (),
        CAMERAS,
        flipped=False,
        fitter=fitter,
        quality=lambda *args: None,
    )
    assert result.fit is contradicted


def test_motion_observations_skip_missing_and_unmatched_camera_evidence(monkeypatch) -> None:
    camera = CAMERAS["Front"]
    pixel = camera.project(TRUTH.bar_ends()[0, 0])[0]
    item = WheelCheck(1, 2, "Front", float(pixel[0]), float(pixel[1]))
    assert wheel_check.motion_observations(TRUTH, CAMERAS, [replace(item, camera="missing"), item])
    monkeypatch.setattr(
        wheel_check, "_distances", lambda geometry, turns, *args: np.full(len(turns), np.inf)
    )
    turn, error = wheel_check.observed_turn(TRUTH, camera, *pixel)
    assert math.isnan(turn) and math.isinf(error)
    assert wheel_check.motion_observations(TRUTH, CAMERAS, [item]) == ()
    assert wheel_check.motion_observations(TRUTH, CAMERAS, []) == ()
    binding = EncoderBinding("source", "angle", 0)
    settled, results = wheel_check.settle_sign(
        TRUTH, binding, CAMERAS, [replace(item, encoder_angle=0)]
    )
    assert not settled.measured and settled.sign == binding.sign and not results[0].informative
