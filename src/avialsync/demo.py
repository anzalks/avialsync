"""Self-contained demo generation and loading for every supported installation mode."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from fractions import Fraction
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

from avialsync.engine.transcode import TranscodeCancelled, encode_video

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow
    from avialsync.ui.tracking_3d_pane import Tracking3DPane

ProgressCallback = Callable[[int, str], None]
CancelledCallback = Callable[[], bool]


class DemoWindow(Protocol):
    """The source-loading surface the demo needs from the main window."""

    tracking_3d_pane: Tracking3DPane

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
    override = os.environ.get("AVIALSYNC_DEMO_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "avialsync" / "demo"


#: Presentation grid for generated demo media. 90 kHz is the MPEG convention
#: and divides 30 fps exactly, so the demo's timestamps are not themselves a
#: source of rounding error for anyone reading the sync tools against it.
_DEMO_TIME_BASE = Fraction(1, 90_000)
_DEMO_RATE = Fraction(30, 1)

#: Length of each generated demo camera. A module constant rather than a default
#: argument so a test can shorten it without patching a signature.
DEMO_VIDEO_SECONDS = 10.0
_DEMO_SIZE = (360, 640)  # height, width


def _demo_frame(index: int, height: int, width: int) -> np.ndarray:
    """Draw one recognisable test frame.

    A moving bar over a static gradient, plus a block that steps once per
    second. It replaces FFmpeg's ``testsrc`` pattern, which is no longer
    reachable now that nothing shells out to the command line (D-075); what it
    has to be is *visibly moving*, so that someone scrubbing the demo can see
    at a glance that the cameras are in step.
    """
    rows = np.arange(height, dtype=np.int32)[:, None]
    columns = np.arange(width, dtype=np.int32)[None, :]
    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[:, :, 0] = ((columns * 255) // max(1, width - 1)).astype(np.uint8)
    frame[:, :, 1] = ((rows * 255) // max(1, height - 1)).astype(np.uint8)
    frame[:, :, 2] = np.uint8(40)

    bar = (index * 7) % max(1, width - 24)
    frame[:, bar : bar + 24, :] = 255

    second = index // 30
    size = height // 6
    top = 8
    left = 8 + (second % 6) * (size + 4)
    frame[top : top + size, left : min(width, left + size), :] = 255
    return frame


def _demo_frame_times(duration: float, vfr: bool) -> list[float]:
    """Return presentation times for one generated camera.

    The VFR camera drops every seventh exposure and leaves the survivors where
    they were, which is what a real camera under a varying trigger does. The
    old generator asked FFmpeg to ``select`` frames out and re-time the rest;
    writing the timestamps directly is both simpler and a truer VFR fixture.
    """
    count = int(round(duration * float(_DEMO_RATE)))
    times = [index / float(_DEMO_RATE) for index in range(count)]
    if not vfr:
        return times
    return [seconds for index, seconds in enumerate(times) if index % 7 != 0]


def _generate_video(
    video_path: Path,
    progress: ProgressCallback,
    cancelled: CancelledCallback,
    progress_start: int,
    progress_end: int,
    *,
    duration: float = DEMO_VIDEO_SECONDS,
    vfr: bool = False,
) -> None:
    """Generate one camera, reporting progress as a percentage.

    Encoded in-process with PyAV, so `avialsync demo` works on a machine with
    no media runtime installed — which is the whole point of D-075 and the last
    place the application shelled out to FFmpeg.
    """
    partial_path = video_path.with_name(f"{video_path.stem}.partial{video_path.suffix}")
    partial_path.unlink(missing_ok=True)

    height, width = _DEMO_SIZE
    times = _demo_frame_times(duration, vfr)
    span = max(1e-9, times[-1] if times else duration)

    def frames() -> Iterator[tuple[np.ndarray, float]]:
        for index, seconds in enumerate(times):
            yield _demo_frame(index, height, width), seconds

    def report(elapsed: float) -> None:
        fraction = min(1.0, elapsed / span)
        current = progress_start + round(fraction * (progress_end - progress_start))
        progress(current, f"Generating {video_path.name}…")

    try:
        encode_video(
            partial_path,
            frames(),
            rate=_DEMO_RATE,
            time_base=_DEMO_TIME_BASE,
            progress=report,
            should_cancel=cancelled,
        )
    except TranscodeCancelled:
        partial_path.unlink(missing_ok=True)
        raise RuntimeError("Demo preparation was cancelled.") from None
    except Exception as error:
        partial_path.unlink(missing_ok=True)
        raise RuntimeError(f"Could not generate {video_path.name}: {error}") from error

    # Published only once complete, so a reader can never open a half-written
    # demo camera and treat its truncated timeline as the real one.
    partial_path.replace(video_path)


# The demo's shape, declared once. A release smoke test waits for exactly this
# many videos and channels before it accepts that the demo finished loading, so
# a change to the generated tables has to be visible here. Left as a hand-copied
# literal it becomes a target the demo can never reach, and the smoke test hangs
# until its timeout instead of failing.
DEMO_VIDEO_COUNT = 4
SENSOR_CHANNEL_NAMES = ("Accel_X", "Accel_Y", "Gyro_Z", "Steering_Angle")
EPHYS_CHANNEL_NAMES = ("Electrode_1", "TTL")
TRACKING_PART_NAMES = (
    "left_toe",
    "left_paw",
    "left_elbow",
    "left_shoulder",
    "head",
    "right_shoulder",
    "right_elbow",
    "right_paw",
    "right_toe",
)
# DeepLabCut-style tables carry these fields for every tracked part, and the
# tracking loader turns each one into its own channel.
TRACKING_PART_FIELDS = ("x", "y", "z", "likelihood")
SENSOR_HEADER = ",".join(("time", *SENSOR_CHANNEL_NAMES))
EPHYS_HEADER = ",".join(("time", *EPHYS_CHANNEL_NAMES))
TRACKING_COLUMN_COUNT = len(TRACKING_PART_NAMES) * len(TRACKING_PART_FIELDS)
TRACKING_HEADER = ",".join(["scorer"] + ["DLC"] * TRACKING_COLUMN_COUNT)
DEMO_CHANNEL_COUNT = len(SENSOR_CHANNEL_NAMES) + len(EPHYS_CHANNEL_NAMES) + TRACKING_COLUMN_COUNT


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
        header=SENSOR_HEADER,
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
        header=EPHYS_HEADER,
        comments="",
    )


def _write_tracking(path: Path) -> None:
    """Write a deterministic DLC-style tracking table with 3D coordinates.

    Simulates a 9-point skeleton (head, shoulders, elbows, paws, toes)
    of an animal walking in place on a wheel with antiphasic limb motion.
    Uses inverse kinematics to maintain constant bone lengths.
    """
    rng = np.random.default_rng(44)
    n_frames = 300
    frames = np.arange(n_frames)

    # Running in place (on a wheel)
    p_x, p_y = 320.0, 180.0
    f_x, f_y = 1.0, 0.0
    r_x, r_y = 0.0, 1.0

    walk_phase = 2 * np.pi * frames / 30
    phase_l = walk_phase
    phase_r = walk_phase + np.pi

    def local_to_global(
        f: np.ndarray | float, r: np.ndarray | float, u: np.ndarray | float
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        f_arr = np.asarray(f)
        r_arr = np.asarray(r)
        u_arr = np.asarray(u)
        x = p_x + f_arr * f_x + r_arr * r_x + rng.normal(0, 0.3, n_frames)
        y = p_y + f_arr * f_y + r_arr * r_y + rng.normal(0, 0.3, n_frames)
        z = u_arr + rng.normal(0, 0.3, n_frames)
        return x, y, z

    def compute_elbow(
        S_f: float, S_u: float, P_f: np.ndarray, P_u: np.ndarray, L1: float, L2: float
    ) -> tuple[np.ndarray, np.ndarray]:
        V_f = P_f - S_f
        V_u = P_u - S_u
        D = np.clip(np.sqrt(V_f**2 + V_u**2), 0.1, L1 + L2 - 0.001)
        uv_f, uv_u = V_f / D, V_u / D
        un_f, un_u = -uv_u, uv_f  # Normal pointing backwards
        d = (L1**2 - L2**2 + D**2) / (2 * D)
        h = np.sqrt(np.maximum(0, L1**2 - d**2))
        return S_f + uv_f * d + un_f * h, S_u + uv_u * d + un_u * h

    parts_data = {}

    # Head
    parts_data["head"] = local_to_global(25, 0, 50)

    # Left side IK
    L_shoulder_f, L_shoulder_u = 0.0, 50.0
    L_paw_f = 15 * np.cos(phase_l)
    L_paw_u = 5 + 10 * np.maximum(0, np.sin(phase_l))
    L_elbow_f, L_elbow_u = compute_elbow(L_shoulder_f, L_shoulder_u, L_paw_f, L_paw_u, 25.0, 25.0)

    parts_data["left_shoulder"] = local_to_global(L_shoulder_f, -15, L_shoulder_u)
    parts_data["left_elbow"] = local_to_global(L_elbow_f, -15, L_elbow_u)
    parts_data["left_paw"] = local_to_global(L_paw_f, -15, L_paw_u)
    parts_data["left_toe"] = local_to_global(L_paw_f + 6, -15, L_paw_u)

    # Right side IK
    R_shoulder_f, R_shoulder_u = 0.0, 50.0
    R_paw_f = 15 * np.cos(phase_r)
    R_paw_u = 5 + 10 * np.maximum(0, np.sin(phase_r))
    R_elbow_f, R_elbow_u = compute_elbow(R_shoulder_f, R_shoulder_u, R_paw_f, R_paw_u, 25.0, 25.0)

    parts_data["right_shoulder"] = local_to_global(R_shoulder_f, 15, R_shoulder_u)
    parts_data["right_elbow"] = local_to_global(R_elbow_f, 15, R_elbow_u)
    parts_data["right_paw"] = local_to_global(R_paw_f, 15, R_paw_u)
    parts_data["right_toe"] = local_to_global(R_paw_f + 6, 15, R_paw_u)

    columns = [frames.astype(float)]
    scorer_fields = ["scorer"]
    bodyparts_fields = ["bodyparts"]
    coords_fields = ["coords"]

    for name in TRACKING_PART_NAMES:
        x, y, z = parts_data[name]
        lk = rng.uniform(0.75, 1.0, n_frames)
        columns.extend([x, y, z, lk])
        scorer_fields.extend(["DLC"] * len(TRACKING_PART_FIELDS))
        bodyparts_fields.extend([name] * len(TRACKING_PART_FIELDS))
        coords_fields.extend(TRACKING_PART_FIELDS)

    data = np.column_stack(columns)
    headers = (
        ",".join(scorer_fields),
        ",".join(bodyparts_fields),
        ",".join(coords_fields),
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
    # camera_3 runs marginally longer on purpose: a session whose sources all
    # end on the same frame would never exercise the "outside this source's
    # coverage" path that every real multi-camera recording hits.
    video_specs = (
        (directory / "camera_1.mp4", DEMO_VIDEO_SECONDS, False),
        (directory / "camera_2.mp4", DEMO_VIDEO_SECONDS, False),
        (directory / "camera_3.mp4", DEMO_VIDEO_SECONDS + 0.01, False),
        (directory / "camera_vfr.mp4", DEMO_VIDEO_SECONDS, True),
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
        (sensors, _write_sensors, 80, "sensor trace", SENSOR_HEADER),
        (ephys, _write_ephys, 88, "ephys trace", EPHYS_HEADER),
        (tracking, _write_tracking, 96, "tracking data", TRACKING_HEADER),
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
    from avialsync.loaders.csv_loader import CSVLoader
    from avialsync.loaders.tracking_loader import TrackingLoader

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

    # Explicit skeleton for the demo's walking animal (D-041: never inferred).
    window.tracking_3d_pane.set_skeleton(
        [
            ("left_toe", "left_paw"),
            ("left_paw", "left_elbow"),
            ("left_elbow", "left_shoulder"),
            ("left_shoulder", "head"),
            ("head", "right_shoulder"),
            ("right_shoulder", "right_elbow"),
            ("right_elbow", "right_paw"),
            ("right_paw", "right_toe"),
        ]
    )


class DemoProgressDialog(QDialog):
    """Show demo generation progress and an inspectable activity log."""

    cancelled = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preparing AvialSync Demo")
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
        except (OSError, RuntimeError) as error:
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
        # No `self._thread.finished.connect(self._worker.deleteLater)`: that
        # signal is emitted in the worker thread and the worker lives there, so
        # the connection is direct and ~QObject would run inside the dying
        # thread — severing the progress dialog's connections while holding one
        # of Qt's pooled signal/slot mutexes and then taking the GIL, which
        # deadlocks against a GUI thread that holds the GIL and waits on a
        # colliding mutex from that pool (D-062). Python owns the worker and
        # destroys it with this object, on the GUI thread.
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
