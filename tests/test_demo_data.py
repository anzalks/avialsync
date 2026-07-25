"""Regression tests for generated, user-facing demo inputs."""

from pathlib import Path

from kinochronix.loaders.tracking_loader import TrackingLoader
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
        "nose_likelihood",
        "tail_x",
        "tail_y",
        "tail_likelihood",
    ]
    times, values = next(loader.read_chunks("nose_x"))
    assert times[0] == 0.0
    assert times[-1] == 299 / 30
    assert len(times) == len(values) == 300
