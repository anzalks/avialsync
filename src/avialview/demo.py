"""Self-contained demo generation and loading for every supported installation mode."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol

import numpy as np

from avialview.runtime import require_ffmpeg


class DemoWindow(Protocol):
    """The source-loading surface the demo needs from the main window."""

    def _load_video(self, path: Path) -> None: ...

    def _enqueue_import(
        self, path: Path, loader_cls: type[object], config: dict[str, str]
    ) -> None: ...


def demo_data_dir() -> Path:
    """Return the platform-appropriate directory for generated demo inputs."""
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "avialview" / "demo"


def ensure_demo_data() -> tuple[Path, Path]:
    """Create a small deterministic video and signal CSV if they do not exist."""
    directory = demo_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    video_path = directory / "camera.mp4"
    csv_path = directory / "sensors.csv"

    if not video_path.is_file():
        subprocess.run(
            [
                str(require_ffmpeg()),
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=duration=10:size=640x360:rate=30",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(video_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    if not csv_path.is_file():
        times = np.linspace(0.0, 10.0, 10_000)
        values = np.column_stack(
            (times, np.sin(2 * np.pi * 1.5 * times), np.cos(2 * np.pi * 0.5 * times))
        )
        np.savetxt(csv_path, values, delimiter=",", header="time,signal_a,signal_b", comments="")

    return video_path, csv_path


def load_demo(window: DemoWindow, video_path: Path, csv_path: Path) -> None:
    """Load generated inputs through AvialView's asynchronous source paths."""
    from avialview.loaders.csv_loader import CSVLoader

    window._load_video(video_path)
    window._enqueue_import(
        csv_path,
        CSVLoader,
        {"time_col": "time", "time_unit": "s", "separator": ","},
    )
