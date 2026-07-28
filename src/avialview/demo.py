"""Self-contained demo generation and loading for every supported installation mode."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

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


def _generate_video(
    video_path: Path, progress: ProgressCallback, cancelled: CancelledCallback
) -> None:
    """Generate the video while translating FFmpeg progress into a percentage."""
    command = [
        str(require_ffmpeg()),
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=10:size=640x360:rate=30",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-progress",
        "pipe:1",
        "-nostats",
        str(video_path),
    ]
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
            raise RuntimeError("Demo preparation was cancelled.")
        key, separator, value = line.strip().partition("=")
        if separator and key in {"out_time_ms", "out_time_us"}:
            try:
                encoded_us = float(value)
            except ValueError:
                continue
            progress(min(70, 5 + int(encoded_us / 10_000_000 * 65)), "Generating demo video…")
    stderr = process.stderr.read() if process.stderr is not None else ""
    if process.wait() != 0:
        raise RuntimeError(f"FFmpeg could not generate the demo video:\n{stderr[-2000:]}")


def ensure_demo_data(
    progress: ProgressCallback | None = None, cancelled: CancelledCallback | None = None
) -> tuple[Path, Path]:
    """Create a small deterministic video and signal CSV if they do not exist."""
    directory = demo_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    video_path = directory / "camera.mp4"
    csv_path = directory / "sensors.csv"
    report = progress or (lambda _value, _message: None)
    is_cancelled = cancelled or (lambda: False)
    report(0, f"Preparing demo data in {directory}")

    if not video_path.is_file():
        report(5, "Generating demo video…")
        _generate_video(video_path, report, is_cancelled)
    else:
        report(70, "Reusing existing demo video.")

    if not csv_path.is_file():
        if is_cancelled():
            raise RuntimeError("Demo preparation was cancelled.")
        report(80, "Generating demo sensor trace…")
        times = np.linspace(0.0, 10.0, 10_000)
        values = np.column_stack(
            (times, np.sin(2 * np.pi * 1.5 * times), np.cos(2 * np.pi * 0.5 * times))
        )
        np.savetxt(csv_path, values, delimiter=",", header="time,signal_a,signal_b", comments="")
    else:
        report(90, "Reusing existing demo sensor trace.")

    report(100, "Demo is ready.")
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
    finished = Signal(object, object)
    failed = Signal(str)

    @Slot()
    def run(self) -> None:
        """Generate inputs and report the resulting paths."""
        try:
            thread = QThread.currentThread()
            video_path, csv_path = ensure_demo_data(
                self.progress.emit, thread.isInterruptionRequested
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            self.failed.emit(str(error))
            return
        self.finished.emit(video_path, csv_path)


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

    @Slot(object, object)
    def _on_finished(self, video_path: object, csv_path: object) -> None:
        """Close progress UI and load the newly available demo files."""
        self._dialog.close()
        if isinstance(video_path, Path) and isinstance(csv_path, Path):
            QTimer.singleShot(0, lambda: load_demo(self._window, video_path, csv_path))

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        """Surface the failed command's diagnostic text to the user."""
        self._dialog.close()
        if message == "Demo preparation was cancelled.":
            return
        QMessageBox.critical(self._window, "Demo Preparation Failed", message)
