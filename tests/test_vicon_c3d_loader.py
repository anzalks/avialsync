"""Vicon C3D parsing and projection onto the paired video frame grid."""

import json
import warnings
import xml.etree.ElementTree as ET
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from avialsync.engine.importer import ImportWorker
from avialsync.loaders import vicon_c3d_loader
from avialsync.loaders.vicon_c3d_loader import ViconC3DLoader, camera_from_xcp


def _write_xcp(path: Path) -> Path:
    root = ET.Element("Cameras")
    camera = ET.SubElement(
        root,
        "Camera",
        {"DEVICEID": "video-1", "TYPE": "Vue_VIDEO", "ISDV": "2", "SENSOR_SIZE": "100 80"},
    )
    frames = ET.SubElement(camera, "KeyFrames")
    ET.SubElement(
        frames,
        "KeyFrame",
        {
            "FRAME": "0",
            "FOCAL_LENGTH": "100",
            "ORIENTATION": "0 0 0 1",
            "POSITION": "0 0 0",
            "PRINCIPAL_POINT": "50 40",
            "PIXEL_ASPECT_RATIO_CORRECTION": "1",
            "VICON_RADIAL2": "Vicon3Parameter 50 40 0 0 0",
        },
    )
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


class _FakeC3DReader:
    point_rate = 2.0
    first_frame = 1
    last_frame = 4
    point_used = 2
    point_labels = ["marker", "bad/label"]

    def __init__(self, _handle) -> None:
        self._frames = [
            np.asarray([[0, 0, 100, 0, 0], [0, 0, 100, -1, 0]], dtype=np.float64),
            np.asarray([[10, 0, 100, 0, 0], [10, 0, 100, -1, 0]], dtype=np.float64),
            np.asarray([[20, 0, 100, 0, 0], [20, 0, 100, -1, 0]], dtype=np.float64),
            np.asarray([[30, 0, 100, 0, 0], [30, 0, 100, -1, 0]], dtype=np.float64),
        ]

    def read_frames(self):
        return ((index, points, np.empty(0)) for index, points in enumerate(self._frames, 1))


def test_camera_from_xcp_reads_vicon_video_projection(tmp_path: Path) -> None:
    camera = camera_from_xcp(_write_xcp(tmp_path / "trial.xcp"))

    np.testing.assert_allclose(camera.project(np.asarray([[0.0, 0.0, 100.0]])), [[50.0, 40.0]])
    assert camera.size == (100, 80)


def test_camera_from_xcp_applies_vicon_radial_as_distorted_to_ideal(tmp_path: Path) -> None:
    path = _write_xcp(tmp_path / "trial.xcp")
    tree = ET.parse(path)
    keyframe = tree.find("Camera/KeyFrames/KeyFrame")
    assert keyframe is not None
    keyframe.set("VICON_RADIAL2", "Vicon3Parameter 50 40 0.0001 0.000000002 0.0000000000001")
    tree.write(path, encoding="utf-8", xml_declaration=True)

    camera = camera_from_xcp(path)
    pixel = camera.project(np.asarray([[20.0, 0.0, 100.0]]))[0]

    # The ideal pinhole pixel is (70, 40); Vicon's correction takes the observed pixel to it.
    r2 = (pixel[0] - 50.0) ** 2
    corrected = 50.0 + (pixel[0] - 50.0) * (1.0 + 1e-4 * r2 + 2e-9 * r2**2 + 1e-13 * r2**3)
    assert pixel[0] < 70.0
    np.testing.assert_allclose(corrected, 70.0, atol=1e-9)
    np.testing.assert_allclose(pixel[1], 40.0)
    np.testing.assert_allclose(camera.normalise(pixel[None, :]), [[0.2, 0.0]], atol=1e-9)


def test_c3d_loader_filters_only_the_missing_analog_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trial.c3d"
    path.write_bytes(b"synthetic C3D fixture")
    _write_xcp(path.with_suffix(".xcp"))

    def _reader_with_expected_and_unexpected_warnings(handle):
        warnings.warn("No analog data found in file.", UserWarning, stacklevel=2)
        warnings.warn("unrelated parser warning", RuntimeWarning, stacklevel=2)
        return _FakeC3DReader(handle)

    monkeypatch.setattr(
        vicon_c3d_loader.c3d,
        "Reader",
        _reader_with_expected_and_unexpected_warnings,
    )
    loader = ViconC3DLoader()
    with pytest.warns(RuntimeWarning, match="unrelated parser warning"):
        loader.open(path, {"fps": 1.0, "frame_count": 2})


def test_c3d_loader_projects_markers_and_omits_untracked_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trial.c3d"
    path.write_bytes(b"synthetic C3D fixture")
    _write_xcp(path.with_suffix(".xcp"))
    monkeypatch.setattr(vicon_c3d_loader.c3d, "Reader", _FakeC3DReader)

    loader = ViconC3DLoader()
    loader.open(
        path,
        {"fps": 1.0, "frame_count": 2, "video_width": 50, "video_height": 40},
    )
    batch = next(loader.read_all_chunks())

    assert [channel.name for channel in loader.channels()] == [
        "marker_x",
        "marker_y",
        "bad_label_x",
        "bad_label_y",
    ]
    np.testing.assert_allclose(batch["marker_x"][0], [0.0, 1.0])
    np.testing.assert_allclose(batch["marker_x"][1], [25.0, 45.0])
    assert np.isnan(batch["bad_label_x"][1]).all()
    assert loader.pose_schema().frame_indexed
    assert len(loader.pose_schema().points) == 2


def test_c3d_loader_exposes_native_xyz_for_3d_pose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trial.c3d"
    path.write_bytes(b"synthetic C3D fixture")
    _write_xcp(path.with_suffix(".xcp"))
    monkeypatch.setattr(vicon_c3d_loader.c3d, "Reader", _FakeC3DReader)

    loader = ViconC3DLoader()
    loader.open(path, {"role": "pose3d", "fps": 1.0, "frame_count": 2})
    batch = next(loader.read_all_chunks())

    assert "pose3d" in loader.pose_roles()
    assert loader.pose_schema().is_3d
    assert [channel.name for channel in loader.channels()] == [
        "marker_x",
        "marker_y",
        "marker_z",
        "bad_label_x",
        "bad_label_y",
        "bad_label_z",
    ]
    np.testing.assert_allclose(batch["marker_x"][1], [0.0, 20.0])
    np.testing.assert_allclose(batch["marker_y"][1], [0.0, 0.0])
    np.testing.assert_allclose(batch["marker_z"][1], [100.0, 100.0])


def test_c3d_loader_emits_xyz_and_projected_xy_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trial.c3d"
    path.write_bytes(b"synthetic C3D fixture")
    _write_xcp(path.with_suffix(".xcp"))
    monkeypatch.setattr(vicon_c3d_loader.c3d, "Reader", _FakeC3DReader)

    loader = ViconC3DLoader()
    loader.open(
        path,
        {
            "role": "pose3d_overlay2d",
            "fps": 1.0,
            "frame_count": 2,
            "video_width": 50,
            "video_height": 40,
        },
    )
    batch = next(loader.read_all_chunks())
    projected_x, projected_y = loader._config["vicon_projection_channels"]["marker"]

    assert loader.pose_schema().is_3d
    np.testing.assert_allclose(batch["marker_x"][1], [0.0, 20.0])
    np.testing.assert_allclose(batch["marker_y"][1], [0.0, 0.0])
    np.testing.assert_allclose(batch["marker_z"][1], [100.0, 100.0])
    np.testing.assert_allclose(batch[projected_x][1], [25.0, 45.0])
    np.testing.assert_allclose(batch[projected_y][1], [20.0, 20.0])


def test_batch_import_probes_video_size_before_cache_key_and_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trial.c3d"
    video_path = tmp_path / "trial.avi"
    path.write_bytes(b"synthetic C3D fixture")
    video_path.touch()
    _write_xcp(path.with_suffix(".xcp"))
    video_stream = SimpleNamespace(width=50, height=40)
    container = SimpleNamespace(streams=SimpleNamespace(video=[video_stream]))
    monkeypatch.setattr(vicon_c3d_loader.av, "open", lambda _path: nullcontext(container))
    monkeypatch.setattr(vicon_c3d_loader.c3d, "Reader", _FakeC3DReader)

    worker = ImportWorker(
        path,
        {"overlay_video": str(video_path), "fps": 1.0, "frame_count": 2},
        ViconC3DLoader,
    )
    cache_manager = worker._cache_manager()
    key = json.loads(cache_manager.generate_key(path))

    assert worker.config["video_width"] == 50
    assert worker.config["video_height"] == 40
    assert key["cache_config"]["config"]["video_width"] == 50
    assert key["cache_config"]["config"]["video_height"] == 40
    assert key["cache_config"]["config"]["_vicon_projection_revision"] == 5

    loader = ViconC3DLoader()
    loader.open(path, worker.config)
    batch = next(loader.read_all_chunks())
    np.testing.assert_allclose(batch["marker_x"][1], [25.0, 45.0])
    np.testing.assert_allclose(batch["marker_y"][1], [20.0, 20.0])


def test_c3d_loader_centers_a_smaller_video_on_the_sensor_instead_of_scaling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trial.c3d"
    path.write_bytes(b"synthetic C3D fixture")
    _write_xcp(path.with_suffix(".xcp"))
    monkeypatch.setattr(vicon_c3d_loader.c3d, "Reader", _FakeC3DReader)

    loader = ViconC3DLoader()
    loader.open(path, {"fps": 1.0, "frame_count": 2, "video_width": 60, "video_height": 80})
    batch = next(loader.read_all_chunks())

    # Sensor is 100x80: a 60x80 ROI starts at x=20, so sensor x=70 lands at 50.
    np.testing.assert_allclose(batch["marker_x"][1], [30.0, 50.0])
    np.testing.assert_allclose(batch["marker_y"][1], [40.0, 40.0])


def test_c3d_loader_scales_a_video_larger_than_the_sensor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trial.c3d"
    path.write_bytes(b"synthetic C3D fixture")
    _write_xcp(path.with_suffix(".xcp"))
    monkeypatch.setattr(vicon_c3d_loader.c3d, "Reader", _FakeC3DReader)

    loader = ViconC3DLoader()
    loader.open(path, {"fps": 1.0, "frame_count": 2, "video_width": 200, "video_height": 160})
    batch = next(loader.read_all_chunks())

    np.testing.assert_allclose(batch["marker_x"][1], [100.0, 140.0])


def test_loader_claims_c3d_only_with_a_paired_xcp(tmp_path: Path) -> None:
    path = tmp_path / "trial.c3d"
    path.touch()

    assert ViconC3DLoader.can_open(path) == 0.0
    path.with_suffix(".xcp").touch()
    assert ViconC3DLoader.can_open(path) == 0.9
