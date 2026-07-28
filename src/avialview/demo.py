"""Self-contained demo generation and loading for every supported installation mode."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from avialview.runtime import require_ffmpeg

if TYPE_CHECKING:
    from avialview.ui.main_window import MainWindow

ProgressCallback = Callable[[int, str], None]
CancelledCallback = Callable[[], bool]


class DemoWindow(Protocol):
    """The source-loading surface the demo needs from the main window."""

    def _load_video(self, path: Path, offset: float = 0.0, drift_ppm: float = 0.0) -> None: ...

    def _enqueue_import(
        self, path: Path, loader_cls: type[object], config: dict[str, Any]
    ) -> None: ...


@dataclass(frozen=True)
class DemoData:
    """Paths comprising the installed inspection demo."""

    videos: tuple[Path, Path, Path, Path]
    sensors: Path
    ephys: Path
    tracking: Path


def demo_data_dir() -> Path:
    """Return the platform-appropriate directory for generated demo inputs."""
    override = os.environ.get("AVIALVIEW_DEMO_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "avialview" / "demo"


def _generate_video(
    video_path: Path,
    progress: ProgressCallback,
    cancelled: CancelledCallback,
    progress_start: int,
    progress_end: int,
    *,
    duration: float = 10.0,
    vfr: bool = False,
) -> None:
    """Generate one camera while translating FFmpeg progress into a percentage."""
    partial_path = video_path.with_name(f"{video_path.stem}.partial{video_path.suffix}")
    partial_path.unlink(missing_ok=True)
    command = [
        str(require_ffmpeg()),
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=640x360:rate=30",
    ]
    if vfr:
        command.extend(["-vf", r"select=not(eq(mod(n\,7)\,0))", "-fps_mode", "vfr"])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-progress",
            "pipe:1",
            "-nostats",
            str(partial_path),
        ]
    )
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    for line in process.stdout:
        if cancelled():
            process.terminate()
            process.wait()
            partial_path.unlink(missing_ok=True)
            raise RuntimeError("Demo preparation was cancelled.")
        key, separator, value = line.strip().partition("=")
        if separator and key in {"out_time_ms", "out_time_us"}:
            try:
                encoded_us = float(value)
            except ValueError:
                continue
            fraction = min(1.0, encoded_us / (duration * 1_000_000))
            current = progress_start + round(fraction * (progress_end - progress_start))
            progress(current, f"Generating {video_path.name}…")
    stderr = process.stderr.read() if process.stderr is not None else ""
    if process.wait() != 0:
        partial_path.unlink(missing_ok=True)
        raise RuntimeError(f"FFmpeg could not generate {video_path.name}:\n{stderr[-2000:]}")
    partial_path.replace(video_path)


def _write_sensors(path: Path) -> None:
    """Write a deterministic 1 kHz four-channel sensor trace."""
    rng = np.random.default_rng(42)
    times = np.linspace(0.0, 10.0, 10_000)
    values = np.column_stack(
        (
            times,
            np.sin(2 * np.pi * 1.5 * times) + rng.normal(0.0, 0.1, len(times)),
            np.cos(2 * np.pi * 0.5 * times) * np.exp(-times / 5),
            rng.normal(0.0, 1.0, len(times)).cumsum() * 0.1,
            np.sign(np.sin(2 * np.pi * 0.2 * times)) * 2.0,
        )
    )
    np.savetxt(
        path,
        values,
        delimiter=",",
        header="time,Accel_X,Accel_Y,Gyro_Z,Steering_Angle",
        comments="",
    )


def _write_ephys(path: Path) -> None:
    """Write a deterministic dense trace with gaps, NaNs, and sentinel values."""
    rng = np.random.default_rng(43)
    rate_hz = 10_000
    times = np.linspace(0.0, 10.0, rate_hz * 10)
    keep = np.ones(len(times), dtype=bool)
    for gap_center in (2.5, 5.0, 8.0):
        center = int(gap_center * rate_hz)
        keep[center - 250 : center + 250] = False
    times = times[keep]
    electrode = np.sin(2 * np.pi * 5.0 * times) + rng.normal(0.0, 0.05, len(times))
    ttl = np.cos(2 * np.pi * 2.0 * times) * np.exp(-times / 8)
    electrode[rng.integers(0, len(times), size=len(times) // 1000)] = np.nan
    ttl[rng.integers(0, len(times), size=len(times) // 2000)] = -9999.0
    np.savetxt(
        path,
        np.column_stack((times, electrode, ttl)),
        delimiter=",",
        header="time,Electrode_1,TTL",
        comments="",
    )


def _write_tracking(path: Path) -> None:
    """Write a minimal deterministic DLC-style tracking table."""
    rng = np.random.default_rng(44)
    frames = np.arange(300)
    phase = 2 * np.pi * frames / 150
    data = np.column_stack(
        (
            frames,
            320.0 + 40 * np.sin(phase) + rng.normal(0, 2, len(frames)),
            180.0 + 20 * np.cos(phase) + rng.normal(0, 2, len(frames)),
            rng.uniform(0.7, 1.0, len(frames)),
            320.0 - 40 * np.sin(phase) + rng.normal(0, 2, len(frames)),
            180.0 - 20 * np.cos(phase) + rng.normal(0, 2, len(frames)),
            rng.uniform(0.7, 1.0, len(frames)),
        )
    )
    headers = (
        "scorer,DLC,DLC,DLC,DLC,DLC,DLC",
        "bodyparts,nose,nose,nose,tail,tail,tail",
        "coords,x,y,likelihood,x,y,likelihood",
    )
    rows = [",".join([str(int(row[0])), *(f"{value:.8f}" for value in row[1:])]) for row in data]
    path.write_text("\n".join((*headers, *rows)) + "\n", encoding="utf-8")


def _has_header(path: Path, expected: str) -> bool:
    """Return whether a cached demo table matches the current data contract."""
    try:
        with path.open(encoding="utf-8") as table:
            return table.readline().strip() == expected
    except OSError:
        return False


def ensure_demo_data(
    progress: ProgressCallback | None = None,
    cancelled: CancelledCallback | None = None,
    directory: Path | None = None,
) -> DemoData:
    """Create or reuse the complete deterministic inspection demo."""
    directory = demo_data_dir() if directory is None else directory
    directory.mkdir(parents=True, exist_ok=True)
    video_specs = (
        (directory / "camera_1.mp4", 10.0, False),
        (directory / "camera_2.mp4", 10.0, False),
        (directory / "camera_3.mp4", 10.01, False),
        (directory / "camera_vfr.mp4", 10.0, True),
    )
    sensors = directory / "sensors.csv"
    ephys = directory / "ephys_gaps.csv"
    tracking = directory / "pose.csv"
    report = progress or (lambda _value, _message: None)
    is_cancelled = cancelled or (lambda: False)
    report(0, f"Preparing demo data in {directory}")

    for index, (video_path, duration, is_vfr) in enumerate(video_specs):
        if is_cancelled():
            raise RuntimeError("Demo preparation was cancelled.")
        start = 5 + index * 17
        end = start + 17
        if video_path.is_file() and video_path.stat().st_size > 1024:
            report(end, f"Reusing {video_path.name}.")
        else:
            _generate_video(
                video_path,
                report,
                is_cancelled,
                start,
                end,
                duration=duration,
                vfr=is_vfr,
            )

    generated_tables = (
        (
            sensors,
            _write_sensors,
            80,
            "sensor trace",
            "time,Accel_X,Accel_Y,Gyro_Z,Steering_Angle",
        ),
        (ephys, _write_ephys, 88, "ephys trace", "time,Electrode_1,TTL"),
        (tracking, _write_tracking, 96, "tracking data", "scorer,DLC,DLC,DLC,DLC,DLC,DLC"),
    )
    for path, writer, value, label, header in generated_tables:
        if is_cancelled():
            raise RuntimeError("Demo preparation was cancelled.")
        if _has_header(path, header):
            report(value, f"Reusing {path.name}.")
        else:
            report(value - 3, f"Generating demo {label}…")
            writer(path)

    report(100, "Demo is ready.")
    videos = (video_specs[0][0], video_specs[1][0], video_specs[2][0], video_specs[3][0])
    return DemoData(videos, sensors, ephys, tracking)


def load_demo(window: DemoWindow, data: DemoData) -> None:
    """Load the complete synchronized demo through normal asynchronous paths."""
    from avialview.loaders.csv_loader import CSVLoader
    from avialview.loaders.tracking_loader import TrackingLoader

    camera_1, camera_2, camera_3, camera_vfr = data.videos
    window._load_video(camera_1)
    window._load_video(camera_2, offset=1.234)
    window._load_video(camera_3, drift_ppm=1000.0)
    window._load_video(camera_vfr)
    window._enqueue_import(
        data.sensors,
        CSVLoader,
        {
            "time_col": "time",
            "time_unit": "s",
            "separator": ",",
            "units": {
                "Accel_X": "m/s²",
                "Accel_Y": "m/s²",
                "Gyro_Z": "deg/s",
                "Steering_Angle": "deg",
            },
        },
    )
    window._enqueue_import(
        data.ephys,
        CSVLoader,
        {
            "time_col": "time",
            "time_unit": "s",
            "separator": ",",
            "sentinel": -9999.0,
            "units": {"Electrode_1": "mV", "TTL": "V"},
        },
    )
    window._enqueue_import(data.tracking, TrackingLoader, {"fps": 30.0})


class DemoProgressDialog(QDialog):
    """Show demo generation progress and an inspectable activity log."""

    cancelled = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preparing AvialView Demo")
        self.setModal(True)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        self._status = QLabel("Starting demo preparation…")
        self._progress = QProgressBar()
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(120)
        self._cancel = QPushButton("Cancel")
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._cancel)
        layout.addWidget(self._status)
        layout.addWidget(self._progress)
        layout.addWidget(self._log)
        layout.addLayout(buttons)
        self._cancel.clicked.connect(self.cancelled)

    @Slot(int, str)
    def update_progress(self, value: int, message: str) -> None:
        """Display a worker status event."""
        self._progress.setValue(value)
        self._status.setText(message)
        self._log.append(message)


class DemoGenerationWorker(QObject):
    """Generate or reuse demo inputs outside the UI thread."""

    progress = Signal(int, str)
    finished = Signal(object)
    failed = Signal(str)

    @Slot()
    def run(self) -> None:
        """Generate inputs and report the resulting paths."""
        try:
            thread = QThread.currentThread()
            data = ensure_demo_data(self.progress.emit, thread.isInterruptionRequested)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            self.failed.emit(str(error))
            return
        self.finished.emit(data)


class DemoLaunch(QObject):
    """Coordinate visible demo preparation with a worker thread."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self._window = window
        self._dialog = DemoProgressDialog(window)
        self._thread = QThread(self)
        self._worker = DemoGenerationWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._dialog.update_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._dialog.cancelled.connect(self._on_cancelled)

    def start(self) -> None:
        """Show progress UI and start generation."""
        self._dialog.show()
        self._thread.start()

    @Slot()
    def _on_cancelled(self) -> None:
        """Request cancellation without touching the worker from the UI thread."""
        self._thread.requestInterruption()
        self._dialog.update_progress(self._dialog._progress.value(), "Cancelling demo preparation…")
        self._dialog._cancel.setEnabled(False)

    @Slot(object)
    def _on_finished(self, data: object) -> None:
        """Close progress UI and load the newly available demo files."""
        self._dialog.close()
        if isinstance(data, DemoData):
            QTimer.singleShot(0, lambda: load_demo(self._window, data))

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        """Surface the failed command's diagnostic text to the user."""
        self._dialog.close()
        if message == "Demo preparation was cancelled.":
            return
        QMessageBox.critical(self._window, "Demo Preparation Failed", message)
