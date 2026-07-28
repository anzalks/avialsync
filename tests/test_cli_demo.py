"""Tests for the installed ``avialview demo`` command."""

from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QWidget

from avialview import demo
from avialview.__main__ import _parse_args


def test_demo_command_is_accepted() -> None:
    """The installed CLI exposes a real demo subcommand."""
    assert _parse_args(["demo"]).command == "demo"


def test_demo_generation_uses_resolved_ffmpeg(monkeypatch, tmp_path: Path) -> None:
    """Generated inputs do not depend on a repository checkout or caller PATH."""
    video_path = tmp_path / "camera.mp4"
    calls: list[list[str]] = []

    class FakeProcess:
        stdout = ["out_time_us=10000000\n", "progress=end\n"]
        stderr = None

        def wait(self) -> int:
            video_path.write_bytes(b"video")
            return 0

    def fake_popen(command: list[str], **_kwargs: object) -> FakeProcess:
        calls.append(command)
        return FakeProcess()

    monkeypatch.setattr(demo, "demo_data_dir", lambda: tmp_path)
    monkeypatch.setattr(demo, "require_ffmpeg", lambda: Path("bundled-ffmpeg"))
    monkeypatch.setattr(demo.subprocess, "Popen", fake_popen)

    generated_video, csv_path = demo.ensure_demo_data()

    assert generated_video == video_path
    assert calls[0][0] == "bundled-ffmpeg"
    assert ["-loglevel", "error"] == calls[0][2:4]
    assert ["-progress", "pipe:1"] == calls[0][-4:-2]
    data = np.loadtxt(csv_path, delimiter=",", skiprows=1)
    assert data.shape == (10_000, 3)


def test_demo_reuses_existing_files_without_running_ffmpeg(monkeypatch, tmp_path: Path) -> None:
    """A subsequent demo launch reports reuse instead of regenerating its inputs."""
    video_path = tmp_path / "camera.mp4"
    csv_path = tmp_path / "sensors.csv"
    video_path.write_bytes(b"video")
    csv_path.write_text("time,signal_a,signal_b\n0,0,1\n", encoding="utf-8")
    messages: list[str] = []
    monkeypatch.setattr(demo, "demo_data_dir", lambda: tmp_path)
    monkeypatch.setattr(demo, "require_ffmpeg", lambda: (_ for _ in ()).throw(AssertionError()))

    assert demo.ensure_demo_data(lambda _value, message: messages.append(message)) == (
        video_path,
        csv_path,
    )
    assert any("Reusing existing demo video" in message for message in messages)
    assert any("Reusing existing demo sensor trace" in message for message in messages)


def test_demo_progress_dialog_shows_status_and_log(qtbot) -> None:
    """First-run preparation is visible rather than appearing as a frozen window."""
    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = demo.DemoProgressDialog(parent)
    qtbot.addWidget(dialog)

    dialog.update_progress(42, "Generating demo video…")

    assert dialog._progress.value() == 42
    assert dialog._status.text() == "Generating demo video…"
    assert "Generating demo video" in dialog._log.toPlainText()
    assert dialog.metaObject().indexOfSlot("update_progress(int,QString)") >= 0


def test_demo_launch_generates_first_run_inputs_in_a_worker(
    monkeypatch, qtbot, tmp_path: Path
) -> None:
    """The first run remains event-driven while FFmpeg creates demo inputs."""
    generated_video = tmp_path / "camera.mp4"
    generated_csv = tmp_path / "sensors.csv"
    loaded: list[Path] = []

    class Window(QWidget):
        def _load_video(self, path: Path) -> None:
            loaded.append(path)

        def _enqueue_import(self, path: Path, _loader: type, _config: dict[str, str]) -> None:
            loaded.append(path)

    monkeypatch.setattr(demo, "demo_data_dir", lambda: tmp_path)
    window = Window()
    qtbot.addWidget(window)
    launcher = demo.DemoLaunch(window)
    launcher.start()

    qtbot.waitUntil(
        lambda: generated_video.is_file() and generated_csv.is_file() and len(loaded) == 2,
        timeout=30_000,
    )
    launcher._thread.wait(5_000)

    assert loaded == [generated_video, generated_csv]


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
