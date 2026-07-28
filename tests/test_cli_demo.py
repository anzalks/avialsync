"""Tests for the installed ``avialview demo`` command."""

from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtWidgets import QWidget

from avialview import demo
from avialview.__main__ import _parse_args


def test_demo_command_is_accepted() -> None:
    """The installed CLI exposes a real demo subcommand."""
    assert _parse_args(["demo"]).command == "demo"


def test_demo_directory_can_be_isolated_for_release_smoke(monkeypatch, tmp_path: Path) -> None:
    """The staged bundle gate must generate fresh media outside user data."""
    monkeypatch.setenv("AVIALVIEW_DEMO_DIR", str(tmp_path))

    assert demo.demo_data_dir() == tmp_path


def test_demo_generation_builds_four_cameras_and_all_tables(monkeypatch, tmp_path: Path) -> None:
    """The installed demo retains the full inspection fixture contract."""
    calls: list[list[str]] = []

    class FakeProcess:
        stdout = ["out_time_us=10000000\n", "progress=end\n"]
        stderr = None

        def __init__(self, target: Path) -> None:
            self.target = target

        def wait(self) -> int:
            self.target.write_bytes(b"video" * 300)
            return 0

        def terminate(self) -> None:
            return

    def fake_popen(command: list[str], **_kwargs: object) -> FakeProcess:
        calls.append(command)
        return FakeProcess(Path(command[-1]))

    monkeypatch.setattr(demo, "demo_data_dir", lambda: tmp_path)
    monkeypatch.setattr(demo, "require_ffmpeg", lambda: Path("bundled-ffmpeg"))
    monkeypatch.setattr(demo.subprocess, "Popen", fake_popen)

    data = demo.ensure_demo_data()

    assert [path.name for path in data.videos] == [
        "camera_1.mp4",
        "camera_2.mp4",
        "camera_3.mp4",
        "camera_vfr.mp4",
    ]
    assert len(calls) == 4
    assert all(call[0] == "bundled-ffmpeg" for call in calls)
    assert ["-loglevel", "error"] == calls[0][2:4]
    assert "-fps_mode" in calls[3]
    assert np.loadtxt(data.sensors, delimiter=",", skiprows=1).shape == (10_000, 5)
    assert np.loadtxt(data.ephys, delimiter=",", skiprows=1).shape == (98_500, 3)
    assert data.tracking.read_text(encoding="utf-8").startswith("scorer,DLC")


def test_demo_reuses_complete_existing_dataset(monkeypatch, tmp_path: Path) -> None:
    """Subsequent launches reuse every valid generated input."""
    for name in ("camera_1.mp4", "camera_2.mp4", "camera_3.mp4", "camera_vfr.mp4"):
        (tmp_path / name).write_bytes(b"video" * 300)
    demo._write_sensors(tmp_path / "sensors.csv")
    demo._write_ephys(tmp_path / "ephys_gaps.csv")
    demo._write_tracking(tmp_path / "pose.csv")
    messages: list[str] = []
    monkeypatch.setattr(demo, "demo_data_dir", lambda: tmp_path)
    monkeypatch.setattr(demo, "require_ffmpeg", lambda: (_ for _ in ()).throw(AssertionError()))

    data = demo.ensure_demo_data(lambda _value, message: messages.append(message))

    assert len(data.videos) == 4
    assert sum("Reusing camera_" in message for message in messages) == 4
    assert any("Reusing sensors.csv" in message for message in messages)
    assert any("Reusing ephys_gaps.csv" in message for message in messages)
    assert any("Reusing pose.csv" in message for message in messages)


def test_demo_replaces_obsolete_toy_sensor_cache(monkeypatch, tmp_path: Path) -> None:
    """The previous two-channel cache cannot silently downgrade the restored demo."""
    for name in ("camera_1.mp4", "camera_2.mp4", "camera_3.mp4", "camera_vfr.mp4"):
        (tmp_path / name).write_bytes(b"video" * 300)
    (tmp_path / "sensors.csv").write_text("time,signal_a,signal_b\n0,0,1\n", encoding="utf-8")
    demo._write_ephys(tmp_path / "ephys_gaps.csv")
    demo._write_tracking(tmp_path / "pose.csv")
    monkeypatch.setattr(demo, "demo_data_dir", lambda: tmp_path)

    data = demo.ensure_demo_data()

    assert data.sensors.read_text(encoding="utf-8").startswith(
        "time,Accel_X,Accel_Y,Gyro_Z,Steering_Angle"
    )


def test_demo_progress_dialog_shows_status_and_log(qtbot) -> None:
    """First-run preparation is visible rather than appearing as a frozen window."""
    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = demo.DemoProgressDialog(parent)
    qtbot.addWidget(dialog)

    dialog.update_progress(42, "Generating camera_2.mp4…")

    assert dialog._progress.value() == 42
    assert dialog._status.text() == "Generating camera_2.mp4…"
    assert "camera_2.mp4" in dialog._log.toPlainText()
    assert dialog.metaObject().indexOfSlot("update_progress(int,QString)") >= 0


def test_demo_launch_generates_first_run_inputs_in_a_worker(
    monkeypatch, qtbot, tmp_path: Path
) -> None:
    """The first run remains event-driven while FFmpeg creates every input."""
    loaded: list[Path] = []

    class Window(QWidget):
        def _load_video(self, path: Path, offset: float = 0.0, drift_ppm: float = 0.0) -> None:
            loaded.append(path)

        def _enqueue_import(self, path: Path, _loader: type, _config: dict[str, Any]) -> None:
            loaded.append(path)

    monkeypatch.setattr(demo, "demo_data_dir", lambda: tmp_path)
    window = Window()
    qtbot.addWidget(window)
    launcher = demo.DemoLaunch(window)
    launcher.start()

    qtbot.waitUntil(lambda: len(loaded) == 7, timeout=60_000)
    launcher._thread.wait(5_000)

    assert [path.name for path in loaded] == [
        "camera_1.mp4",
        "camera_2.mp4",
        "camera_3.mp4",
        "camera_vfr.mp4",
        "sensors.csv",
        "ephys_gaps.csv",
        "pose.csv",
    ]


def test_demo_loads_alignment_and_sources_through_normal_paths(tmp_path: Path) -> None:
    """The demo applies known mappings and queues sensor/ephys/tracking sources."""
    videos = tuple(tmp_path / f"camera_{name}.mp4" for name in ("1", "2", "3", "vfr"))
    data = demo.DemoData(
        videos,
        tmp_path / "sensors.csv",
        tmp_path / "ephys_gaps.csv",
        tmp_path / "pose.csv",
    )
    loaded_videos: list[tuple[Path, float, float]] = []
    imports: list[tuple[Path, type, dict[str, Any]]] = []

    class Window:
        def _load_video(self, path: Path, offset: float = 0.0, drift_ppm: float = 0.0) -> None:
            loaded_videos.append((path, offset, drift_ppm))

        def _enqueue_import(self, path: Path, loader: type, config: dict[str, Any]) -> None:
            imports.append((path, loader, config))

    demo.load_demo(Window(), data)

    assert loaded_videos == [
        (videos[0], 0.0, 0.0),
        (videos[1], 1.234, 0.0),
        (videos[2], 0.0, 1000.0),
        (videos[3], 0.0, 0.0),
    ]
    assert [item[0] for item in imports] == [data.sensors, data.ephys, data.tracking]
    assert imports[0][2]["time_col"] == "time"
    assert imports[1][2]["sentinel"] == -9999.0
    assert imports[2][2]["fps"] == 30.0
