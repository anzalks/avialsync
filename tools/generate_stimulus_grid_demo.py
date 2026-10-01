"""Rebuild the stimulus-grid screenshots and MP4 from a synthetic three-camera scene.

Run on a desktop display with ``conda run -n avialsync python
tools/generate_stimulus_grid_demo.py``. Every input is generated in a temporary
directory; the published images contain no private paths or data.
"""

from __future__ import annotations

import math
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import av
import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtCore import QEventLoop, QLocale, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QFileDialog

from avialsync.engine.transcode import encode_video
from avialsync.loaders.csv_loader import CSVLoader
from avialsync.ui import recovery
from avialsync.ui.main_window import MainWindow
from avialsync.ui.stimulus_grid_dialog import StimulusGridDialog

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screenshot_kit import capture, pin_appearance, pin_layout, settle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "_static" / "screenshots"
EVENTS = (1.5, 7.0, 12.5)
SOURCE_SECONDS = 17.0
SOURCE_FPS = 30


@dataclass(frozen=True)
class CameraFixture:
    """A distinct view and source-clock offset of the same synthetic scene."""

    path: Path
    label: str
    yaw: float
    offset: float


def _motion(master_time: float) -> tuple[float, float, bool]:
    """Move the marker only within 450 ms of its nearest stimulus onset."""
    delta = min((master_time - event for event in EVENTS), key=abs)
    if abs(delta) > 0.45:
        return 0.0, 0.0, False
    pulse = math.sin(math.pi * (delta + 0.45) / 0.9)
    return 0.55 * pulse, 0.23 * pulse, -0.15 <= delta <= 0.35


def _project(point: tuple[float, float, float], yaw: float, lift: float) -> tuple[int, int]:
    """Project one world point into a yawed camera with a modest downward pitch."""
    x, y, z = point
    turned_x = math.cos(yaw) * x + math.sin(yaw) * z
    depth = -math.sin(yaw) * x + math.cos(yaw) * z
    pitched_y = math.cos(0.25) * (y + lift) - math.sin(0.25) * depth
    scale = 145.0 / (1.0 + 0.18 * depth)
    return round(320 + scale * turned_x), round(205 - scale * pitched_y)


def _scene_frame(master_time: float, camera_yaw: float) -> np.ndarray:
    """Draw three fixed prongs that briefly move, plus a transient off-white point."""
    turn, lift, show_dot = _motion(master_time)
    image = Image.new("RGB", (640, 360), (104, 110, 110))
    draw = ImageDraw.Draw(image)
    draw.line((0, 290, 640, 290), fill=(94, 100, 100), width=2)
    hub = _project((0.0, 0.0, 0.0), camera_yaw + turn, lift)
    prongs = (
        ((0.9, 0.0, 0.0), (181, 189, 187)),
        ((0.0, 0.9, 0.0), (161, 174, 174)),
        ((0.0, 0.0, 0.9), (143, 160, 162)),
    )
    endpoints = []
    for point, color in prongs:
        tip = _project(point, camera_yaw + turn, lift)
        endpoints.append(tip)
        draw.line((*hub, *tip), fill=color, width=7, joint="curve")
        draw.ellipse((tip[0] - 5, tip[1] - 5, tip[0] + 5, tip[1] + 5), fill=color)
    draw.ellipse((hub[0] - 8, hub[1] - 8, hub[0] + 8, hub[1] + 8), fill=(188, 194, 190))
    if show_dot:
        x, y = endpoints[0]
        draw.ellipse((x - 15, y - 15, x + 15, y + 15), fill=(205, 209, 198))
        draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=(246, 244, 229))
    return np.asarray(image)


def _write_camera(camera: CameraFixture) -> None:
    """Encode a source video whose visible action follows the shared master events."""
    count = round(SOURCE_SECONDS * SOURCE_FPS)

    def frames() -> Iterator[tuple[np.ndarray, float]]:
        for index in range(count):
            source_time = index / SOURCE_FPS
            yield _scene_frame(source_time - camera.offset, camera.yaw), source_time

    encode_video(camera.path, frames(), rate=Fraction(SOURCE_FPS, 1))


def _write_signal_csv(folder: Path) -> Path:
    """Write a generated TTL recording for the app's ordinary CSV importer."""
    times = np.arange(0.0, SOURCE_SECONDS, 0.005)
    values = np.zeros_like(times)
    for event in EVENTS:
        values[(times >= event) & (times < event + 0.15)] = 1.0
    path = folder / "stimulus_ttl.csv"
    np.savetxt(
        path, np.column_stack((times, values)), delimiter=",", header="time,TTL", comments=""
    )
    return path


def _wait_until(app: QApplication, ready: Callable[[], bool], label: str) -> None:
    """Let the app's workers and queued UI signals complete while driving the demo."""
    if ready():
        return
    loop = QEventLoop(app)
    poll = QTimer(loop)
    poll.setInterval(10)
    poll.timeout.connect(lambda: loop.quit() if ready() else None)
    deadline = QTimer(loop)
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(60_000)
    loop.exec()
    poll.stop()
    deadline.stop()
    loop.deleteLater()
    if not ready():
        raise RuntimeError(f"Timed out waiting for {label}.")


def _drive_dialog(window: MainWindow, errors: list[str]) -> None:
    """Use the real stimulus dialog and scan job, then accept the selected events."""
    dialogs = [dialog for dialog in window.findChildren(StimulusGridDialog) if dialog.isVisible()]
    if len(dialogs) != 1:
        errors.append("The stimulus-grid dialog did not open.")
        return
    dialog = dialogs[0]
    dialog.resize(900, 800)
    dialog.before_spin.setValue(0.5)
    dialog.after_spin.setValue(1.5)
    dialog.fps_spin.setValue(12)
    dialog.threshold_spin.setValue(0.5)
    deadline = time.monotonic() + 20.0

    def finish_scan() -> None:
        if dialog.event_table.rowCount() == len(EVENTS) and dialog.scan_button.isEnabled():
            capture(dialog, OUTPUT / "stimulus_grid_select_events.png")
            dialog.accept()
        elif time.monotonic() > deadline:
            errors.append(
                f"The app did not find {len(EVENTS)} TTL events: {dialog.scan_status.text()}"
            )
            dialog.reject()
        else:
            QTimer.singleShot(20, dialog, finish_scan)

    dialog.scan_button.click()
    QTimer.singleShot(20, dialog, finish_scan)


def _export_via_app(
    app: QApplication,
    folder: Path,
    cameras: tuple[CameraFixture, ...],
    signal_csv: Path,
    movie: Path,
) -> None:
    """Open generated sources and run File → Export Stimulus Grid through MainWindow."""
    appdata = folder / "appdata"
    appdata.mkdir()
    with patch.object(recovery, "recovery_dir", return_value=appdata):
        window = MainWindow()
        window.resize(1280, 860)
        window.show()
        settle(app)
        pin_layout(window)
        try:
            for camera in cameras:
                window._load_video(camera.path, offset=camera.offset)
            window._enqueue_import(signal_csv, CSVLoader, {"time_col": "time", "time_unit": "s"})
            _wait_until(app, lambda: len(window.video_grid.panes) == len(cameras), "video panes")
            _wait_until(
                app,
                lambda: any(ch.name == "TTL" for ch in window.plot_pane.channels),
                "the TTL channel",
            )
            action = next(a for a in window._all_actions if a.text() == "Export Stimulus Grid…")
            if not action.isEnabled():
                raise RuntimeError(f"The app disabled stimulus-grid export: {action.toolTip()}")
            errors: list[str] = []
            movie.unlink(missing_ok=True)
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(movie), "MP4")):
                QTimer.singleShot(0, window, lambda: _drive_dialog(window, errors))
                action.trigger()
            if errors:
                raise RuntimeError(errors[0])
            _wait_until(
                app,
                lambda: (
                    movie.is_file()
                    and not any(
                        "stimulus grid" in job.label.lower() for job in window._job_manager.jobs()
                    )
                ),
                "the app's stimulus-grid export",
            )
        finally:
            window.close()
            settle(app)


def _save_video_frame(movie: Path, image_path: Path) -> None:
    """Save a decoded frame near stimulus onset, when every view shows the dot."""
    with av.open(str(movie)) as container:
        frames = list(container.decode(video=0))
    index = min(round(0.6 * 12), len(frames) - 1)
    frame = np.ascontiguousarray(frames[index].to_ndarray(format="rgb24"))
    image = QImage(
        frame.data, frame.shape[1], frame.shape[0], frame.strides[0], QImage.Format.Format_RGB888
    ).copy()
    image.save(str(image_path))


def generate() -> None:
    """Create the selection screenshot, two-second MP4, and exported-frame still."""
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
    app = QApplication.instance() or QApplication(sys.argv)
    pin_appearance(app)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="avialsync-grid-docs-") as scratch:
        folder = Path(scratch)
        cameras = (
            CameraFixture(folder / "camera_left.mp4", "Left view", -0.7, -0.08),
            CameraFixture(folder / "camera_front.mp4", "Front view", 0.0, 0.0),
            CameraFixture(folder / "camera_right.mp4", "Right view", 0.7, 0.08),
        )
        for camera in cameras:
            _write_camera(camera)
        signal_csv = _write_signal_csv(folder)
        movie = OUTPUT / "stimulus_grid_demo.mp4"
        _export_via_app(app, folder, cameras, signal_csv, movie)
        _save_video_frame(movie, OUTPUT / "stimulus_grid_export.png")
    print(f"Wrote stimulus-grid demo assets to {OUTPUT}")


if __name__ == "__main__":
    generate()
