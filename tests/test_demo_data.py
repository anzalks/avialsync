"""Regression tests for generated, user-facing demo inputs."""

from pathlib import Path

from avialview.__main__ import main
from avialview.loaders.tracking_loader import TrackingLoader
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
        "nose_x",
        "nose_y",
        "nose_z",
        "nose_likelihood",
        "head_x",
        "head_y",
        "head_z",
        "head_likelihood",
        "spine_x",
        "spine_y",
        "spine_z",
        "spine_likelihood",
        "hip_x",
        "hip_y",
        "hip_z",
        "hip_likelihood",
        "tail_x",
        "tail_y",
        "tail_z",
        "tail_likelihood",
    ]
    times, values = next(loader.read_chunks("nose_z"))
    assert times[0] == 0.0
    assert times[-1] == 299 / 30
    assert len(times) == len(values) == 300


def test_tools_launcher_delegates_to_installed_application() -> None:
    """The compatibility script cannot drift from ``avialview demo`` again."""
    assert launch_demo.main is main
