"""Fitting a lost calibration from the session's own tracking (D-112).

The 3D pose and each camera's 2D tracking are synthesised from the known rig in
``tests/wheel_fixture.py``; the worker must recover cameras that project like
the originals, write them beside the pose, and overwrite nothing it finds there.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from avialsync.core import calibration_ref
from avialsync.core.calibration import read_calibration
from avialsync.engine.calibration_worker import CalibrationFitWorker, CameraFitInput
from tests.wheel_fixture import CAMERAS

BODYPARTS = ("nose", "paw", "tail")
FRAMES = 60


def _world() -> np.ndarray:
    """``(frames, bodyparts, 3)`` of points moving through the cameras' view."""
    rng = np.random.default_rng(7)
    return rng.uniform([-60.0, -60.0, 40.0], [60.0, 60.0, 140.0], size=(FRAMES, len(BODYPARTS), 3))


def _write_3d(path: Path, world: np.ndarray) -> Path:
    header = [f"{b}_{a}" for b in BODYPARTS for a in "xyz"] + ["fnum"]
    rows = [",".join(header)]
    for frame in range(FRAMES):
        rows.append(",".join([*(f"{v:.6f}" for v in world[frame].ravel()), str(frame)]))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _write_2d(path: Path, name: str, world: np.ndarray) -> Path:
    camera = CAMERAS[name]
    rng = np.random.default_rng(len(name))
    rows = [
        ",".join(["scorer", *(["model"] * 3 * len(BODYPARTS))]),
        ",".join(["bodyparts", *(b for b in BODYPARTS for _ in range(3))]),
        ",".join(["coords", *(["x", "y", "likelihood"] * len(BODYPARTS))]),
    ]
    for frame in range(FRAMES):
        pixels = camera.project(world[frame]) + rng.normal(0.0, 0.5, size=(len(BODYPARTS), 2))
        cells = [str(frame)]
        for x, y in pixels:
            cells += [f"{x:.4f}", f"{y:.4f}", "0.99"]
        rows.append(",".join(cells))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _run(session: Path) -> tuple[list[tuple[str, str, str]], list[str]]:
    world = _world()
    pose3d = session / "pose-3d"
    pose3d.mkdir(parents=True, exist_ok=True)
    pose_3d = _write_3d(pose3d / "_eks.csv", world)
    inputs = [
        CameraFitInput(
            name, CAMERAS[name].size, _write_2d(session / f"{name}_eks.csv", name, world)
        )
        for name in CAMERAS
    ]
    worker = CalibrationFitWorker(pose_3d, inputs, pose3d, [f"{n}.mp4" for n in CAMERAS])
    finished: list[tuple[str, str, str]] = []
    errors: list[str] = []
    worker.finished.connect(lambda path, summary, kept: finished.append((path, summary, kept)))
    worker.error.connect(errors.append)
    worker.run()
    return finished, errors


def test_the_fit_projects_like_the_rig_that_made_the_tracking(qapp, tmp_path) -> None:
    finished, errors = _run(tmp_path)
    assert errors == []
    ((path, summary, kept),) = finished
    assert Path(path) == tmp_path / "pose-3d" / "calibration.toml"
    assert kept == ""
    fitted = read_calibration(path)
    assert fitted.names == tuple(CAMERAS)
    assert fitted.metadata["fitted_by"] == "avialsync"
    probe = np.random.default_rng(11).uniform([-50, -50, 50], [50, 50, 130], size=(40, 3))
    for name, truth in CAMERAS.items():
        camera = fitted.camera(name)
        assert camera is not None
        error = np.linalg.norm(camera.project(probe) - truth.project(probe), axis=1)
        assert float(np.max(error)) < 3.0, f"{name} reprojects {np.max(error):.1f} px off"
    link = calibration_ref.read_ref(tmp_path / "pose-3d" / calibration_ref.REF_NAME)
    assert link is not None and link.calibration == Path(path)


def test_an_existing_calibration_and_reference_are_never_overwritten(qapp, tmp_path) -> None:
    pose3d = tmp_path / "pose-3d"
    pose3d.mkdir(parents=True)
    theirs = pose3d / "calibration.toml"
    theirs.write_text("# someone else's\n", encoding="utf-8")
    note = "# 3d rotation matrix location\n/hand/written.toml\n"
    (pose3d / calibration_ref.REF_NAME).write_text(note, encoding="utf-8")

    finished, errors = _run(tmp_path)

    assert errors == []
    ((path, _, kept),) = finished
    assert Path(path) == pose3d / "calibration_fitted.toml"
    assert theirs.read_text(encoding="utf-8") == "# someone else's\n"
    assert Path(kept).read_text(encoding="utf-8") == note


def test_a_second_fit_gets_a_name_of_its_own(qapp, tmp_path) -> None:
    _run(tmp_path)
    ((second, _, _),) = _run(tmp_path)[0]
    assert Path(second).name == "calibration_fitted.toml"
    ((third, _, _),) = _run(tmp_path)[0]
    assert Path(third).name == "calibration_fitted-2.toml"


def test_too_few_cameras_report_an_error(qapp, tmp_path) -> None:
    world = _world()
    pose3d = tmp_path / "pose-3d"
    pose3d.mkdir(parents=True)
    worker = CalibrationFitWorker(
        _write_3d(pose3d / "_eks.csv", world),
        [CameraFitInput("Front", (1280, 1024), _write_2d(tmp_path / "Front.csv", "Front", world))],
        pose3d,
        ["Front.mp4"],
    )
    errors: list[str] = []
    worker.error.connect(errors.append)
    worker.run()
    assert errors and "two cameras" in errors[0]
    assert not (pose3d / "calibration.toml").exists()


@pytest.mark.parametrize("likelihood", ["0.5"])
def test_unsure_detections_do_not_pair(qapp, tmp_path, likelihood) -> None:
    """Below the likelihood floor a 2D point is left out of the fit, not trusted."""
    from avialsync.engine.calibration_worker import _read_2d

    path = tmp_path / "cam.csv"
    path.write_text(
        "scorer,m,m,m\nbodyparts,nose,nose,nose\ncoords,x,y,likelihood\n"
        f"0,1.0,2.0,{likelihood}\n1,3.0,4.0,0.99\n",
        encoding="utf-8",
    )
    frames, points = _read_2d(path)
    assert list(frames) == [0.0, 1.0]
    assert np.isnan(points["nose"][0]).all() and points["nose"][1].tolist() == [3.0, 4.0]
