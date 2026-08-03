"""Regression tests for generated, user-facing demo inputs."""

from pathlib import Path

from avialsync.__main__ import main
from avialsync.loaders.tracking_loader import TrackingLoader
from tools import launch_demo
from tools.generate_demo_data import _is_dlc_pose_csv, _make_pose_csv


def test_generated_pose_csv_is_importable_dlc_data(tmp_path: Path) -> None:
    """The demo tracking file must match the loader's three-row DLC contract."""
    pose_path = tmp_path / "pose.csv"
    _make_pose_csv(pose_path)

    assert _is_dlc_pose_csv(pose_path)
    assert TrackingLoader.can_open(pose_path) == 1.0

    loader = TrackingLoader()
    loader.open(pose_path, {"fps": 30.0})
    channels = loader.channels()
    assert [channel.name for channel in channels] == [
        "left_toe_x",
        "left_toe_y",
        "left_toe_z",
        "left_toe_likelihood",
        "left_paw_x",
        "left_paw_y",
        "left_paw_z",
        "left_paw_likelihood",
        "left_elbow_x",
        "left_elbow_y",
        "left_elbow_z",
        "left_elbow_likelihood",
        "left_shoulder_x",
        "left_shoulder_y",
        "left_shoulder_z",
        "left_shoulder_likelihood",
        "head_x",
        "head_y",
        "head_z",
        "head_likelihood",
        "right_shoulder_x",
        "right_shoulder_y",
        "right_shoulder_z",
        "right_shoulder_likelihood",
        "right_elbow_x",
        "right_elbow_y",
        "right_elbow_z",
        "right_elbow_likelihood",
        "right_paw_x",
        "right_paw_y",
        "right_paw_z",
        "right_paw_likelihood",
        "right_toe_x",
        "right_toe_y",
        "right_toe_z",
        "right_toe_likelihood",
    ]
    times, values = next(loader.read_chunks("head_z"))
    assert times[0] == 0.0
    assert times[-1] == 299 / 30
    assert len(times) == len(values) == 300


def test_tools_launcher_delegates_to_installed_application() -> None:
    """The compatibility script cannot drift from ``avialsync demo`` again."""
    assert launch_demo.main is main
