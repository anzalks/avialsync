"""The camera calibration: anipose's file, triangulation, and fitting a lost one (D-112).

Judged against the synthetic rig in ``tests/wheel_fixture.py`` -- three known
cameras -- so each result is compared with the truth that produced it.
"""

from __future__ import annotations

import numpy as np
import pytest

from avialsync.core.calibration import (
    Calibration,
    CameraModel,
    fit_camera,
    read_calibration,
    triangulate,
    write_calibration,
)
from avialsync.core.errors import CalibrationError
from tests.wheel_fixture import CAMERAS


def _rig() -> Calibration:
    return Calibration(cameras=tuple(CAMERAS.values()), metadata={"adjusted": False, "error": 0.5})


def test_a_calibration_survives_its_file(tmp_path) -> None:
    path = write_calibration(tmp_path / "calibration.toml", _rig())
    read = read_calibration(path)
    assert read.names == ("Front", "Left", "Right")
    for original, back in zip(CAMERAS.values(), read.cameras, strict=True):
        assert back.size == original.size
        assert np.allclose(back.matrix, original.matrix)
        assert np.allclose(back.rotation, original.rotation)
        assert np.allclose(back.translation, original.translation)
    assert read.metadata == {"adjusted": False, "error": 0.5}


def test_the_writer_leaves_no_temporary_file(tmp_path) -> None:
    write_calibration(tmp_path / "calibration.toml", _rig())
    assert [p.name for p in tmp_path.iterdir()] == ["calibration.toml"]


def test_a_fisheye_camera_is_refused_not_approximated(tmp_path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        '[cam_0]\nname = "A"\nsize = [ 640, 480,]\nfisheye = true\n'
        "matrix = [ [ 1.0, 0.0, 0.0,], [ 0.0, 1.0, 0.0,], [ 0.0, 0.0, 1.0,],]\n"
        "rotation = [ 0.0, 0.0, 0.0,]\ntranslation = [ 0.0, 0.0, 0.0,]\n",
        encoding="utf-8",
    )
    with pytest.raises(CalibrationError, match="fisheye"):
        read_calibration(path)


def test_an_incomplete_camera_is_named(tmp_path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text('[cam_0]\nname = "A"\nsize = [ 640, 480,]\n', encoding="utf-8")
    with pytest.raises(CalibrationError, match="cam_0"):
        read_calibration(path)


def test_a_file_with_no_cameras_is_refused(tmp_path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text("[metadata]\nerror = 1.0\n", encoding="utf-8")
    with pytest.raises(CalibrationError, match="no cameras"):
        read_calibration(path)


def test_a_missing_file_is_a_calibration_error(tmp_path) -> None:
    with pytest.raises(CalibrationError):
        read_calibration(tmp_path / "absent.toml")


def test_triangulation_recovers_a_known_point() -> None:
    truth = np.array([12.0, -30.0, 95.0])
    views = [(camera, tuple(camera.project(truth)[0])) for camera in CAMERAS.values()]
    point, error = triangulate(views)
    assert np.allclose(point, truth, atol=1e-6)
    assert error < 1e-6


def test_one_view_has_no_depth() -> None:
    camera = CAMERAS["Front"]
    with pytest.raises(CalibrationError, match="at least two cameras"):
        triangulate([(camera, (1.0, 2.0))])


def test_distortion_round_trips_through_normalise() -> None:
    base = CAMERAS["Front"]
    lens = CameraModel(
        name="lens",
        size=base.size,
        matrix=base.matrix,
        distortions=np.array([-0.2, 0.05, 0.001, -0.001, 0.0]),
        rotation=base.rotation,
        translation=base.translation,
    )
    world = np.array([[10.0, -20.0, 90.0], [-40.0, 15.0, 110.0]])
    pixels = lens.project(world)
    camera = world @ lens.rotation_matrix().T + lens.translation
    ideal = camera[:, :2] / camera[:, 2:3]
    assert np.allclose(lens.normalise(pixels), ideal, atol=1e-6)


def test_a_camera_is_refitted_from_its_own_observations() -> None:
    """A lost calibration recovered from 3D/2D pairs projects like the original."""
    rng = np.random.default_rng(3)
    world = rng.uniform([-60.0, -60.0, 40.0], [60.0, 60.0, 140.0], size=(400, 3))
    truth = CAMERAS["Left"]
    pixels = truth.project(world) + rng.normal(0.0, 0.5, size=(400, 2))
    fitted, error = fit_camera("Left", truth.size, world, pixels)
    assert error < 1.5
    held_out = rng.uniform([-60.0, -60.0, 40.0], [60.0, 60.0, 140.0], size=(50, 3))
    assert np.max(np.linalg.norm(fitted.project(held_out) - truth.project(held_out), axis=1)) < 3.0


def test_too_few_pairs_are_refused() -> None:
    world = np.zeros((10, 3))
    with pytest.raises(CalibrationError, match="at least 50"):
        fit_camera("A", (640, 480), world, np.zeros((10, 2)))
