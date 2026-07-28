"""Regression tests for generated, user-facing demo inputs."""

from pathlib import Path
from types import SimpleNamespace

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
        "nose_likelihood",
        "tail_x",
        "tail_y",
        "tail_likelihood",
    ]
    times, values = next(loader.read_chunks("nose_x"))
    assert times[0] == 0.0
    assert times[-1] == 299 / 30
    assert len(times) == len(values) == 300


def test_demo_launcher_starts_at_the_visible_beginning(monkeypatch, tmp_path: Path) -> None:
    """The launcher leaves short demo media visible instead of playing to its end."""
    from avialview.engine import importer

    class FakeImportWorker:
        def __init__(self, *_args) -> None:
            pass

        def run(self) -> None:
            pass

    class FakePlayer:
        def __init__(self) -> None:
            self.seek_calls: list[float] = []

        def seek(self, time_s: float) -> None:
            self.seek_calls.append(time_s)

    loaded_videos: list[tuple[Path, float, float]] = []
    completed_imports: list[tuple[object, ...]] = []
    player = FakePlayer()
    window = SimpleNamespace(
        _frame_indexed_sources=[],
        _load_video=lambda path, offset=0.0, drift_ppm=0.0: loaded_videos.append(
            (path, offset, drift_ppm)
        ),
        _on_import_finished=lambda *args: completed_imports.append(args),
        player=player,
    )
    monkeypatch.setattr(importer, "ImportWorker", FakeImportWorker)
    monkeypatch.chdir(tmp_path)

    launch_demo.load_data(window)

    assert len(loaded_videos) == 4
    assert len(completed_imports) == 2
    assert player.seek_calls == [0.0]
