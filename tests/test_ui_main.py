"""Main Window regression tests."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PySide6.QtCore import QMimeData, QObject, QPointF, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from kinochronix.core.session import SensorEntry, SessionState
from kinochronix.core.sync import SyncFit, SyncMatch, SyncProposal
from kinochronix.loaders.csv_loader import CSVLoader
from kinochronix.loaders.neo_loader import NeoLoader
from kinochronix.loaders.tracking_loader import TrackingLoader
from kinochronix.loaders.video_standard import VideoStandardLoader
from kinochronix.ui.main_window import MainWindow


@pytest.fixture
def main_window(qapp: QApplication) -> MainWindow:
    win = MainWindow()
    win.show()
    return win


# ── Bug a: _on_annotate_requested crash ──────────────────────────────


def test_annotate_no_attribute_error(main_window: MainWindow) -> None:
    """_on_annotate_requested must not raise with zero videos loaded."""
    main_window._on_annotate_requested()


def test_annotate_with_pane_present_no_error(main_window: MainWindow) -> None:
    """_on_annotate_requested must not raise when a pane is present.

    test_annotate_no_attribute_error missed this: with empty panes the for-loop
    body never runs. The crash lived inside the loop — pane.time_map.path raised
    AttributeError because TimeMap has no .path attribute.
    """
    from unittest.mock import MagicMock

    from kinochronix.core.timeline import TimeMap

    fake_pane = MagicMock()
    fake_pane.time_map = TimeMap()  # real TimeMap — to_source() works, no .path
    fake_pane._fps = 30.0

    main_window.video_grid.panes.append(fake_pane)
    main_window.video_grid._paths.append("/fake/video.mp4")

    # Before fix: AttributeError 'TimeMap' has no attribute 'path'
    main_window._on_annotate_requested()

    # One marker must have been added to the store
    assert len(main_window.annotation_store.markers) == 1


def test_accepted_sync_mapping_updates_video_and_session(main_window: MainWindow) -> None:
    """A user-accepted proposal changes only the target TimeMap and is persisted."""
    from unittest.mock import MagicMock

    from kinochronix.core.timeline import TimeMap

    pane = MagicMock()
    pane.time_map = TimeMap()
    main_window.video_grid.panes.append(pane)
    main_window.video_grid._paths.append("/fake/camera.mp4")
    proposal = SyncProposal(
        reference_id="sensor:ttl",
        target_id="/fake/camera.mp4",
        fit=SyncFit(1.25, 3.5, 0.0, 0.0, 4, 0),
        matches=(SyncMatch(0.0, 1.25, 0.0),),
        tolerance=0.01,
    )

    main_window._accept_sync_proposal("/fake/camera.mp4", proposal)

    assert pane.time_map.to_source(100.0) == pytest.approx(101.25035)
    state = main_window._build_session_state()
    assert state.videos[0].drift_ppm == pytest.approx(3.5)
    assert state.sync_provenance[0].target_id == "/fake/camera.mp4"


def test_programmatic_import_completion_needs_no_progress_dialog(
    main_window: MainWindow, tmp_path: Path
) -> None:
    """Demo/programmatic imports may finish without an interactive progress dialog."""
    from kinochronix.core.inspection import SourceInspection
    from kinochronix.core.pyramid import PyramidBuilder

    cache_dir = tmp_path / "demo.kcache"
    cache_dir.mkdir()
    PyramidBuilder(cache_dir, "ttl").build_and_save(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
    main_window._on_import_finished(
        "demo.csv",
        str(cache_dir),
        ["ttl"],
        (0.0, 1.0),
        SourceInspection(path="demo.csv"),
    )

    assert main_window.transport._status_label.text() == "Ready · imported demo.csv"


# ── Bug b: _start_csv_import → _start_data_import ────────────────────


def test_session_restore_calls_data_import(main_window: MainWindow) -> None:
    """Session restore with a sensor entry must call _start_data_import.

    Regression: _restore_session was calling self._start_csv_import() which
    does not exist — AttributeError on every session restore with sensors.
    """
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        csv_path = Path(f.name)
        f.write(b"t,x\n0.0,1.0\n1.0,2.0\n")

    state = SessionState(sensors=[SensorEntry(path=str(csv_path), channels=[])])

    with patch.object(main_window, "_start_data_import") as mock_import:
        main_window._restore_session(state)
        mock_import.assert_called_once_with(csv_path)


@pytest.mark.parametrize(
    ("suffix", "loader_class", "target"),
    [
        (".mp4", VideoStandardLoader, "video"),
        (".cine", VideoStandardLoader, "video"),
        (".csv", CSVLoader, "data"),
        (".tracking", TrackingLoader, "data"),
        (".nix", NeoLoader, "data"),
    ],
)
def test_drop_routing_uses_loader_capability(
    main_window: MainWindow,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    loader_class: type,
    target: str,
) -> None:
    """Dropped files route by registered source type, not a suffix allow-list."""
    path = tmp_path / f"recording{suffix}"
    path.touch()
    monkeypatch.setattr(
        "kinochronix.core.registry.LoaderRegistry.find_best_loader",
        lambda _registry, _path: loader_class,
    )
    video_paths: list[Path] = []
    data_calls: list[tuple[Path, type]] = []
    monkeypatch.setattr(main_window, "_load_video", video_paths.append)
    monkeypatch.setattr(
        main_window,
        "_start_data_import",
        lambda data_path, selected: data_calls.append((data_path, selected)),
    )

    main_window._route_dropped_path(path)

    if target == "video":
        assert video_paths == [path]
        assert data_calls == []
    else:
        assert video_paths == []
        assert data_calls == [(path, loader_class)]


def test_drop_directory_routes_each_supported_child(
    main_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generic directory falls back to capability-routing its direct children."""
    video = tmp_path / "camera.anyvideo"
    sensor = tmp_path / "sensor.anysensor"
    video.touch()
    sensor.touch()

    def find_loader(_registry, path: Path):
        return VideoStandardLoader if path == video else CSVLoader if path == sensor else None

    monkeypatch.setattr("kinochronix.core.registry.LoaderRegistry.find_best_loader", find_loader)
    video_paths: list[Path] = []
    data_calls: list[tuple[Path, type]] = []
    monkeypatch.setattr(main_window, "_load_video", video_paths.append)
    monkeypatch.setattr(
        main_window,
        "_start_data_import",
        lambda data_path, selected: data_calls.append((data_path, selected)),
    )

    main_window._route_dropped_path(tmp_path)

    assert video_paths == [video]
    assert data_calls == [(sensor, CSVLoader)]


def test_video_load_keeps_worker_alive_until_thread_finishes(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Video workers need an explicit owner after being moved to a QThread."""

    class _IdleWorker(QObject):
        opened = Signal(str, object, str)
        error = Signal(str)
        cancelled = Signal()

        def __init__(self, path: Path) -> None:
            super().__init__()
            self.path = path

        @Slot()
        def run(self) -> None:
            return

    monkeypatch.setattr("kinochronix.engine.video_worker.VideoOpenWorker", _IdleWorker)

    main_window._load_video(Path("camera.mp4"))

    assert len(main_window._video_load_jobs) == 1
    for thread in main_window._video_load_jobs:
        thread.quit()
        assert thread.wait(1_000)


def test_drop_real_video_completes_async_open(
    main_window: MainWindow, qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dropped video must complete its real worker lifecycle without closing the app."""
    video = Path("tests/fixtures/videos/camera_1.mp4")
    assert video.exists()
    pane = MagicMock()
    widget_threads: list[bool] = []

    def add_pane(*args, **kwargs):
        widget_threads.append(QThread.currentThread() == QApplication.instance().thread())
        return pane

    monkeypatch.setattr(main_window.video_grid, "add_pane", add_pane)
    monkeypatch.setattr(main_window.sidebar, "add_video", lambda *args: None)
    monkeypatch.setattr(main_window.sidebar, "set_video_loader", lambda *args: None)
    monkeypatch.setattr(main_window.sidebar, "set_video_pane", lambda *args: None)
    monkeypatch.setattr(main_window.sidebar, "set_video_inspection", lambda *args: None)
    monkeypatch.setattr(main_window, "_update_bounds", lambda *args: None)

    main_window._route_dropped_path(video)

    qtbot.waitUntil(lambda: not main_window._video_load_jobs, timeout=10_000)
    assert str(video) in main_window._video_fps
    assert widget_threads == [True]
    pane.set_vfr.assert_called_once_with(False)


def test_real_drop_event_routes_sensor_file(
    main_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Qt delivery of a drop event must route a supported sensor without closing the window."""
    sensor = tmp_path / "sensor.csv"
    sensor.write_text("time,value\n0,1\n", encoding="utf-8")
    data_calls: list[tuple[Path, type]] = []
    monkeypatch.setattr(
        main_window,
        "_start_data_import",
        lambda path, loader: data_calls.append((path, loader)),
    )

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(sensor))])
    enter_event = QDragEnterEvent(
        QPointF(10, 10).toPoint(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(main_window, enter_event)
    assert enter_event.isAccepted()
    event = QDropEvent(
        QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.NoButton, Qt.NoModifier
    )

    QApplication.sendEvent(main_window, event)

    assert event.isAccepted()
    assert main_window.isVisible()
    assert data_calls == [(sensor, CSVLoader)]


def test_drop_over_video_grid_forwards_to_main_router(
    main_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A drop over the video grid reaches the same mixed-source router."""
    sensor = tmp_path / "sensor.csv"
    sensor.write_text("time,value\n0,1\n", encoding="utf-8")
    data_calls: list[tuple[Path, type]] = []
    monkeypatch.setattr(
        main_window,
        "_start_data_import",
        lambda path, loader: data_calls.append((path, loader)),
    )
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(sensor))])
    enter_event = QDragEnterEvent(
        QPointF(10, 10).toPoint(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(main_window.video_grid, enter_event)
    assert enter_event.isAccepted()
    drop_event = QDropEvent(
        QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.NoButton, Qt.NoModifier
    )

    QApplication.sendEvent(main_window.video_grid, drop_event)

    assert drop_event.isAccepted()
    assert main_window.isVisible()
    assert data_calls == [(sensor, CSVLoader)]
