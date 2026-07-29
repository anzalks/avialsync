"""Main Window regression tests."""

import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PySide6.QtCore import QMimeData, QObject, QPointF, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QSplitter

from avialview.core.session import (
    SensorEntry,
    SessionState,
    SyncProvenance,
    VideoEntry,
)
from avialview.core.sync import SyncFit, SyncMatch, SyncProposal
from avialview.loaders.csv_loader import CSVLoader
from avialview.loaders.neo_loader import NeoLoader
from avialview.loaders.tracking_loader import TrackingLoader
from avialview.loaders.video_standard import VideoStandardLoader
from avialview.ui.main_window import MainWindow


@pytest.fixture
def main_window(qapp: QApplication) -> MainWindow:
    win = MainWindow()
    win.show()
    return win


# ── Bug a: _on_annotate_requested crash ──────────────────────────────


def test_annotate_no_attribute_error(main_window: MainWindow) -> None:
    """_on_annotate_requested must not raise with zero videos loaded."""
    main_window._on_annotate_requested()


def test_data_streams_uses_the_video_plot_native_splitter_style(
    main_window: MainWindow,
) -> None:
    """Plots and Data Streams share the same native vertical splitter treatment."""
    assert isinstance(main_window._content_splitter, QSplitter)
    assert main_window._content_splitter.widget(0) is main_window._v_splitter
    assert main_window._content_splitter.widget(1) is main_window.data_streams
    assert main_window._content_splitter.handle(1).isVisible()
    assert main_window.transport.parentWidget() is not main_window._content_splitter


def test_annotate_with_pane_present_no_error(main_window: MainWindow) -> None:
    """_on_annotate_requested must not raise when a pane is present.

    test_annotate_no_attribute_error missed this: with empty panes the for-loop
    body never runs. The crash lived inside the loop — pane.time_map.path raised
    AttributeError because TimeMap has no .path attribute.
    """
    from unittest.mock import MagicMock

    from avialview.core.timeline import TimeMap

    fake_pane = MagicMock()
    fake_pane.time_map = TimeMap()  # real TimeMap — to_source() works, no .path
    fake_pane.frame_record_at.return_value = (0, 0.0)

    main_window.video_grid.panes.append(fake_pane)
    main_window.video_grid._paths.append("/fake/video.mp4")

    # Before fix: AttributeError 'TimeMap' has no attribute 'path'
    main_window._on_annotate_requested()

    # One marker must have been added to the store
    assert len(main_window.annotation_store.markers) == 1


def test_accepted_sync_mapping_updates_video_and_session(main_window: MainWindow) -> None:
    """A user-accepted proposal changes only the target TimeMap and is persisted."""
    from unittest.mock import MagicMock

    from avialview.core.timeline import TimeMap

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


def test_session_restore_queues_exact_mapping_for_async_video_open(
    main_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exact arrays survive the asynchronous gap between restore and pane creation."""
    video = tmp_path / "camera.mp4"
    video.touch()
    monkeypatch.setattr(main_window, "_load_video", lambda *_args, **_kwargs: None)
    state = SessionState(
        videos=[VideoEntry(path=str(video))],
        sync_provenance=[
            SyncProvenance(
                reference_id="trigger",
                target_id=str(video),
                offset=0.0,
                drift_ppm=0.0,
                rms_residual=0.0,
                max_residual=0.0,
                matched_count=3,
                rejected_count=0,
                tolerance=0.0,
                exact_master=[100.0, 101.0, 102.0],
                exact_source=[0.0, 1.0, 2.0],
            )
        ],
    )

    main_window._restore_session(state)

    master, source = main_window._pending_exact_mappings[str(video)]
    assert master.tolist() == [100.0, 101.0, 102.0]
    assert source.tolist() == [0.0, 1.0, 2.0]


def test_programmatic_import_completion_needs_no_progress_dialog(
    main_window: MainWindow, tmp_path: Path
) -> None:
    """Demo/programmatic imports may finish without an interactive progress dialog."""
    from avialview.core.inspection import SourceInspection
    from avialview.core.pyramid import PyramidBuilder

    cache_dir = tmp_path / "demo.avialcache"
    cache_dir.mkdir()
    PyramidBuilder(cache_dir, "ttl").build_and_save(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
    main_window._on_import_finished(
        "demo.csv",
        str(cache_dir),
        ["ttl"],
        (0.0, 1.0),
        SourceInspection(path="demo.csv"),
    )

    assert main_window.data_streams._status_label.text() == "Status: Ready · imported demo.csv"


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
        "avialview.core.registry.LoaderRegistry.find_best_loader",
        lambda _registry, _path: loader_class,
    )
    candidates = main_window._collect_drop_candidates(path)
    assert candidates == [(path, loader_class)]


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

    monkeypatch.setattr("avialview.core.registry.LoaderRegistry.find_best_loader", find_loader)
    candidates = main_window._collect_drop_candidates(tmp_path)
    assert set(candidates) == {(video, VideoStandardLoader), (sensor, CSVLoader)}


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

    monkeypatch.setattr("avialview.engine.video_worker.VideoOpenWorker", _IdleWorker)

    main_window._load_video(Path("camera.mp4"))

    assert len(main_window._video_load_jobs) == 1
    for thread in main_window._video_load_jobs:
        thread.quit()
        assert thread.wait(1_000)


def test_multiple_video_loads_are_serialized(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, qtbot
) -> None:
    """Burst loading must never initialize multiple native video panes at once."""
    started: list[Path] = []
    release_first = threading.Event()

    class _IdleWorker(QObject):
        opened = Signal(str, object, str)
        error = Signal(str, str)
        cancelled = Signal()

        def __init__(self, path: Path) -> None:
            super().__init__()
            self.path = path

        @Slot()
        def run(self) -> None:
            started.append(self.path)
            release_first.wait(timeout=2.0)
            self.cancelled.emit()

    monkeypatch.setattr("avialview.engine.video_worker.VideoOpenWorker", _IdleWorker)
    first = Path("camera_1.mp4")
    second = Path("camera_2.mp4")

    main_window._load_video(first)
    main_window._load_video(second)

    qtbot.waitUntil(lambda: started == [first], timeout=2_000)
    assert len(main_window._video_load_jobs) == 1
    assert list(main_window._pending_video_loads) == [(second, 0.0, 0.0)]

    release_first.set()

    qtbot.waitUntil(lambda: started == [first, second], timeout=2_000)
    qtbot.waitUntil(lambda: not main_window._video_load_jobs, timeout=2_000)
    assert not main_window._pending_video_loads


def test_multiple_data_imports_are_serialized(
    main_window: MainWindow, qtbot, tmp_path: Path
) -> None:
    """Demo sensor, ephys, and tracking imports must not replace one another's workers."""
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    first.write_text("time,value\n0,1\n1,2\n", encoding="utf-8")
    second.write_text("time,value\n0,3\n1,4\n", encoding="utf-8")
    config = {"time_col": "time", "time_unit": "s", "separator": ","}

    main_window._enqueue_import(first, CSVLoader, config)
    main_window._enqueue_import(second, CSVLoader, config)

    qtbot.waitUntil(
        lambda: main_window._import_thread is None and not main_window._pending_imports,
        timeout=10_000,
    )
    assert str(first) in main_window._inspections
    assert str(second) in main_window._inspections


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

    main_window._load_video(video)

    qtbot.waitUntil(lambda: not main_window._video_load_jobs, timeout=10_000)
    assert str(video) in main_window._video_fps
    assert widget_threads == [True]
    pane.set_vfr.assert_called_once_with(False)


def test_video_sidebar_summary_receives_probed_codec(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successfully probed video must not fall back to UNKNOWN in the sidebar."""
    from unittest.mock import MagicMock

    from avialview.loaders.video_standard import VideoStandardLoader

    loader = VideoStandardLoader()
    loader._codec = "h264"
    loader._duration = 10.0
    loader._fps = 30.0
    loader._file_size = 12_345_678
    pane = MagicMock()
    metadata: dict[str, object] = {}
    monkeypatch.setattr(main_window.video_grid, "add_pane", lambda *_args, **_kwargs: pane)
    monkeypatch.setattr(
        main_window.sidebar,
        "add_video",
        lambda _path, values: metadata.update(values),
    )
    monkeypatch.setattr(main_window.sidebar, "set_video_loader", lambda *_args: None)
    monkeypatch.setattr(main_window.sidebar, "set_video_pane", lambda *_args: None)
    monkeypatch.setattr(main_window.sidebar, "set_video_inspection", lambda *_args: None)
    monkeypatch.setattr(main_window, "_update_bounds", lambda *_args: None)
    synchronize_pane = MagicMock()
    monkeypatch.setattr(main_window.player, "seek", synchronize_pane)

    main_window._on_video_opened("camera.mp4", loader, "camera.mp4")

    assert metadata["codec"] == "h264"
    assert metadata["file_size_bytes"] == 12_345_678
    pane.set_video_metadata.assert_called_once_with(loader.video_metadata())
    synchronize_pane.assert_called_once_with(main_window.clock.state.t, exact=True)


def test_video_coverage_is_projected_onto_master_time(main_window: MainWindow, monkeypatch) -> None:
    """Evidence spans must reflect source offset/drift, never raw media time."""
    from unittest.mock import MagicMock

    coverage = MagicMock()
    monkeypatch.setattr(main_window.transport, "set_source_coverage", coverage)

    main_window._set_video_coverage("camera.mp4", (0.0, 10.0), offset=1.0, drift_ppm=0.0)

    coverage.assert_called_once_with("camera.mp4", -1.0, 9.0, "video")


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
