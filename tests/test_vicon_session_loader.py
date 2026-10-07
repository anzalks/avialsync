"""Vicon session discovery pairs a C3D trial with its calibrated video."""

from pathlib import Path

import numpy as np
import pytest

from avialsync.core.calibration import CameraModel
from avialsync.core.registry import LoaderRegistry
from avialsync.loaders import vicon_session_loader
from avialsync.loaders.vicon_session_loader import ViconSessionSource


def test_session_pairs_trial_files_and_declares_video_frame_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c3d_path = tmp_path / "trial.c3d"
    xcp_path = tmp_path / "trial.xcp"
    video_path = tmp_path / "trial.video-1.20260625143252.avi"
    for path in (c3d_path, xcp_path, video_path):
        path.touch()

    camera = CameraModel(
        name="video-1",
        size=(1920, 1080),
        matrix=np.eye(3),
    )
    monkeypatch.setattr(vicon_session_loader, "camera_from_xcp", lambda _path: camera)
    monkeypatch.setattr(
        vicon_session_loader, "_video_metadata", lambda _path: (100.0, 2921, 1280, 720)
    )

    layout = ViconSessionSource().scan(tmp_path, LoaderRegistry(plugin_dirs=[]))

    assert ViconSessionSource.can_open(tmp_path) == 0.9
    assert [item.path for item in layout.items] == [video_path, c3d_path]
    assert layout.items[1].config["role"] == "pose3d_overlay2d"
    assert layout.items[1].config["overlay_video"] == str(video_path)
    assert layout.items[1].config["fps"] == 100.0
    assert layout.warnings == []


def test_session_reports_unpaired_c3d_instead_of_guessing(tmp_path: Path) -> None:
    (tmp_path / "trial.c3d").touch()

    layout = ViconSessionSource().scan(tmp_path, LoaderRegistry(plugin_dirs=[]))

    assert layout.items == []
    assert any("no matching XCP" in warning for warning in layout.warnings)


def test_session_does_not_claim_a_trial_without_video(tmp_path: Path) -> None:
    (tmp_path / "trial.c3d").touch()
    (tmp_path / "trial.xcp").touch()

    assert ViconSessionSource.can_open(tmp_path) == 0.0


def test_builtin_registry_discovers_vicon_loader_and_session(tmp_path: Path) -> None:
    from avialsync.loaders.vicon_c3d_loader import ViconC3DLoader

    c3d_path = tmp_path / "trial.c3d"
    c3d_path.touch()
    c3d_path.with_suffix(".xcp").touch()
    (tmp_path / "trial.video-1.capture.avi").touch()
    registry = LoaderRegistry(plugin_dirs=[])

    assert registry.find_best_loader(c3d_path) is ViconC3DLoader
    assert registry.find_best_session(tmp_path) is ViconSessionSource
