"""A rig's image correction on top of a calibrated camera (D-226)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from scipy.interpolate import RBFInterpolator

from avialsync.core.calibration import (
    Calibration,
    ImageCorrection,
    corrected,
    same_native_camera,
    triangulate,
)
from tests.wheel_fixture import CAMERAS, TRUTH

CONTROLS = ((300.0, 400.0), (700.0, 380.0), (1000.0, 600.0), (500.0, 800.0), (850.0, 250.0))
SHIFTS = ((-2.0, 3.0), (1.5, -4.0), (3.0, 2.0), (-1.0, -1.5), (2.5, 0.5))
AFFINE = ((0.94, -0.14, 125.0), (-0.017, 0.87, 75.5), (0.0, 0.0, 1.0))


def _correction() -> ImageCorrection:
    return ImageCorrection(AFFINE, CONTROLS, SHIFTS, smoothing=0.01, size=(1440, 1080))


def test_correction_is_the_affine_then_the_thin_plate_spline_residual() -> None:
    """Term for term what the wheel-calibration analysis's ProjectionCamera.warp computes."""
    pixels = np.asarray([[100.0, 200.0], [720.0, 540.0], [1300.0, 900.0]])
    affine = np.asarray(AFFINE)
    moved = pixels @ affine[:2, :2].T + affine[:2, 2]
    field = RBFInterpolator(
        np.asarray(CONTROLS) / 720, np.asarray(SHIFTS), smoothing=0.01, kernel="thin_plate_spline"
    )
    expected = moved + field(moved / 720)

    assert _correction().apply(pixels) == pytest.approx(expected, abs=1e-12)


def test_correction_inverts_to_a_thousandth_of_a_pixel() -> None:
    pixels = np.asarray([[100.0, 200.0], [720.0, 540.0], [1300.0, 900.0]])
    correction = _correction()
    assert correction.invert(correction.apply(pixels)) == pytest.approx(pixels, abs=1e-3)


def test_a_corrected_camera_projects_and_triangulates_through_its_correction() -> None:
    front = dataclasses.replace(CAMERAS["Front"], correction=_correction())
    side = CAMERAS["Left"]
    point = np.asarray(TRUTH.centre) + 10.0
    native = CAMERAS["Front"].project(point)

    assert front.project(point) == pytest.approx(_correction().apply(native))
    found, error = triangulate(
        [(front, tuple(front.project(point)[0])), (side, tuple(side.project(point)[0]))]
    )
    assert found == pytest.approx(point, abs=1e-4)
    assert error < 1e-3


def test_a_correction_applies_only_to_the_native_camera_it_was_fitted_on() -> None:
    calibration = Calibration(cameras=(CAMERAS["Front"], CAMERAS["Left"]))
    moved = dataclasses.replace(
        CAMERAS["Left"], translation=np.asarray(CAMERAS["Left"].translation) + 1.0
    )

    result = corrected(calibration, [(CAMERAS["Front"], _correction()), (moved, _correction())])

    front, side = result.cameras
    assert front.correction is not None and front.size == (1440, 1080)
    assert side.correction is None, "a recalibrated camera does not take an old correction"
    assert same_native_camera(dataclasses.replace(CAMERAS["Front"], size=(1, 1)), CAMERAS["Front"])
