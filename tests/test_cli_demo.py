"""Tests for the installed ``avialview demo`` command."""

from pathlib import Path

import numpy as np

from avialview import demo
from avialview.__main__ import _parse_args


def test_demo_command_is_accepted() -> None:
    """The installed CLI exposes a real demo subcommand."""
    assert _parse_args(["demo"]).command == "demo"


def test_demo_generation_uses_resolved_ffmpeg(monkeypatch, tmp_path: Path) -> None:
    """Generated inputs do not depend on a repository checkout or caller PATH."""
    video_path = tmp_path / "camera.mp4"
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> None:
        calls.append(command)
        video_path.write_bytes(b"video")

    monkeypatch.setattr(demo, "demo_data_dir", lambda: tmp_path)
    monkeypatch.setattr(demo, "require_ffmpeg", lambda: Path("bundled-ffmpeg"))
    monkeypatch.setattr(demo.subprocess, "run", fake_run)

    generated_video, csv_path = demo.ensure_demo_data()

    assert generated_video == video_path
    assert calls[0][0] == "bundled-ffmpeg"
    data = np.loadtxt(csv_path, delimiter=",", skiprows=1)
    assert data.shape == (10_000, 3)


def test_demo_loads_video_and_csv_through_normal_source_paths(tmp_path: Path) -> None:
    """The demo uses the same asynchronous loading APIs as an end user."""
    video_path = tmp_path / "camera.mp4"
    csv_path = tmp_path / "sensors.csv"
    loaded_videos: list[Path] = []
    imports: list[tuple[Path, type, dict[str, str]]] = []

    class Window:
        def _load_video(self, path: Path) -> None:
            loaded_videos.append(path)

        def _enqueue_import(self, path: Path, loader: type, config: dict[str, str]) -> None:
            imports.append((path, loader, config))

    demo.load_demo(Window(), video_path, csv_path)

    assert loaded_videos == [video_path]
    assert imports[0][0] == csv_path
    assert imports[0][2]["time_col"] == "time"
