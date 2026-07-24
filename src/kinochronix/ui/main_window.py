"""Main window for KinoChronix."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QSplitter,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from kinochronix.core.timeline import MasterClock
from kinochronix.engine.player import Player
from kinochronix.ui.plot_pane import PlotPane
from kinochronix.ui.transport import Transport
from kinochronix.ui.video_grid import VideoGrid


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("KinoChronix")
        self.resize(1024, 768)

        # Core
        self.clock = MasterClock()

        # UI Components
        self.video_grid = VideoGrid(self)
        self.plot_pane = PlotPane(self)
        self.transport = Transport(self)

        # Engine
        self.player = Player(self.clock, self.video_grid, self.plot_pane, self.transport, self)

        # Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QHBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        from kinochronix.ui.sidebar import SidebarPane
        self.sidebar = SidebarPane(self)
        self.sidebar.open_video_requested.connect(self._open_video)
        self.sidebar.open_sensor_requested.connect(self._open_csv)
        self.sidebar.video_offset_changed.connect(self._on_video_offset_changed)
        self.sidebar.video_remove_requested.connect(self._on_video_remove_requested)
        self.sidebar.sensor_remove_requested.connect(self._on_sensor_remove_requested)

        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        h_splitter.addWidget(self.sidebar)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.addWidget(self.video_grid)
        v_splitter.addWidget(self.plot_pane)
        v_splitter.setStretchFactor(0, 3)
        v_splitter.setStretchFactor(1, 1)

        right_layout.addWidget(v_splitter)
        right_layout.addWidget(self.transport)

        h_splitter.addWidget(right_widget)
        h_splitter.setStretchFactor(0, 0)
        h_splitter.setStretchFactor(1, 1)

        layout.addWidget(h_splitter)

        # Menu
        self._setup_menu()

        # Drag and Drop
        self.setAcceptDrops(True)

        # Start player tick
        self.player.start()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if not path.is_file():
                continue
            
            ext = path.suffix.lower()
            if ext in [".mp4", ".mov", ".avi", ".mkv"]:
                self._load_video(path)
            elif ext in [".csv", ".txt", ".tsv"]:
                self._start_csv_import(path)

    def _setup_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("File")

        open_video_action = file_menu.addAction("Open Video(s)...")
        open_video_action.triggered.connect(self._open_video)

        open_csv_action = file_menu.addAction("Open CSV...")
        open_csv_action.triggered.connect(self._open_csv)

    def _load_video(self, path: Path) -> None:
        self.video_grid.add_pane(str(path))
        from kinochronix.loaders.video_standard import VideoStandardLoader

        vloader = VideoStandardLoader()
        try:
            vloader.open(path, {})
            b = vloader.time_bounds()
            self._update_bounds(b[0], b[1])
            metadata = {
                "fps": vloader._fps,
                "codec": getattr(vloader, "_codec", "unknown"),
                "duration": vloader._duration
            }
            self.sidebar.add_video(str(path), metadata)
        except Exception:
            pass

    def _on_video_offset_changed(self, path: str, offset: float) -> None:
        self.video_grid.set_offset(path, offset)
        self.clock.play()  # Force an update/re-sync
        self.clock.pause()

    def _on_video_remove_requested(self, path: str) -> None:
        self.video_grid.remove_pane(path)
        self.sidebar.remove_video(path)

    def _on_sensor_remove_requested(self, path: str) -> None:
        from kinochronix.core.cache import CacheManager
        cache_mgr = CacheManager(loader_version=1)
        cache_dir = cache_mgr.get_temp_cache_dir(Path(path))
        self.plot_pane.remove_channels(cache_dir)
        self.sidebar.remove_sensor(path)

    def _open_video(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Open Video(s)")
        for path in paths:
            if path:
                self._load_video(Path(path))

    def _open_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open CSV")
        if path:
            self._start_csv_import(Path(path))

    def _start_csv_import(self, path: Path) -> None:
        from kinochronix.engine.importer import ImportWorker
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QProgressDialog

        # Hardcoded config for MVP
        config = {"time_col": "time", "time_unit": "s", "separator": ","}

        self._import_thread = QThread()
        self._import_worker = ImportWorker(path, config)
        self._import_worker.moveToThread(self._import_thread)

        self._progress_dialog = QProgressDialog("Importing CSV...", "Cancel", 0, 100, self)
        self._progress_dialog.setWindowTitle("Importing Data")
        self._progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress_dialog.setAutoClose(True)
        self._progress_dialog.setAutoReset(True)
        self._progress_dialog.setValue(0)

        # Connect signals
        self._import_thread.started.connect(self._import_worker.run)
        self._import_worker.progress.connect(self._progress_dialog.setValue)
        self._progress_dialog.canceled.connect(self._import_worker.cancel)

        self._import_worker.finished.connect(self._on_import_finished)
        self._import_worker.finished.connect(self._import_thread.quit)
        self._import_worker.finished.connect(self._import_worker.deleteLater)
        self._import_thread.finished.connect(self._import_thread.deleteLater)

        self._import_worker.error.connect(self._on_import_error)
        self._import_worker.error.connect(self._import_thread.quit)

        # Start
        self._progress_dialog.show()
        self._import_thread.start()

    def _on_import_finished(
        self, path: str, cache_dir: str, channels: list[str], bounds: tuple[float, float]
    ) -> None:
        print(f"DEBUG _on_import_finished called with path={path}, cache_dir={cache_dir}, channels={channels}")
        self._progress_dialog.close()
        self.plot_pane.load_channels(Path(cache_dir), channels)
        self._update_bounds(bounds[0], bounds[1])
        self.sidebar.add_sensor(path, channels)

    def _on_import_error(self, err_msg: str) -> None:
        self._progress_dialog.close()
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "Import Error", f"Failed to import CSV:\n{err_msg}")

    def _update_bounds(self, t0: float, t1: float) -> None:
        if self.clock.state.bounds == (0.0, 0.0):
            new_bounds = (t0, t1)
        else:
            curr_t0, curr_t1 = self.clock.state.bounds
            new_bounds = (min(curr_t0, t0), max(curr_t1, t1))
        
        self.clock.set_bounds(*new_bounds)
        self.transport.set_bounds(*new_bounds)
        self.transport.set_time(new_bounds[0])
