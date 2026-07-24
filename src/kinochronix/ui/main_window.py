"""Main window for KinoChronix."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QSplitter,
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
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.video_grid)
        splitter.addWidget(self.plot_pane)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)
        layout.addWidget(self.transport)

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
        except Exception:
            pass

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
        self, cache_dir: Path, channels: list[str], bounds: tuple[float, float]
    ) -> None:
        self._progress_dialog.close()
        self.plot_pane.load_channels(cache_dir, channels)
        self._update_bounds(bounds[0], bounds[1])

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
