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

        # Start player tick
        self.player.start()

    def _setup_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("File")

        open_video_action = file_menu.addAction("Open Video...")
        open_video_action.triggered.connect(self._open_video)

        open_csv_action = file_menu.addAction("Open CSV...")
        open_csv_action.triggered.connect(self._open_csv)

    def _open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Video")
        if path:
            self.video_grid.add_pane(path)
            from kinochronix.loaders.video_standard import VideoStandardLoader

            vloader = VideoStandardLoader()
            try:
                vloader.open(Path(path), {})
                b = vloader.time_bounds()
                self._update_bounds(b[0], b[1])
            except Exception:
                pass

    def _open_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open CSV")
        if path:
            from kinochronix.core.cache import CacheManager
            from kinochronix.core.pyramid import PyramidBuilder
            from kinochronix.loaders.csv_loader import CSVLoader

            loader = CSVLoader()
            # Hardcoded config for MVP
            config = {"time_col": "time", "time_unit": "s", "separator": ","}
            try:
                loader.open(Path(path), config)
            except Exception as e:
                print(f"Error opening CSV: {e}")
                return

            cache_mgr = CacheManager(loader_version=1)
            temp_dir = cache_mgr.get_temp_cache_dir(Path(path))

            channels = loader.channels()
            if not channels:
                return
            ch_name = channels[0].name

            # Synchronous read for MVP demo
            all_chunks = list(loader.read_chunks(ch_name))
            import numpy as np

            full_t = np.concatenate([c[0] for c in all_chunks])
            full_v = np.concatenate([c[1] for c in all_chunks])

            builder = PyramidBuilder(temp_dir, ch_name)
            builder.build_and_save(full_t, full_v)
            cache_mgr.commit_cache(Path(path), temp_dir)

            cache_dir = cache_mgr.get_cache_dir(Path(path))
            self.plot_pane.load_source(cache_dir, ch_name)

            self._update_bounds(float(full_t[0]), float(full_t[-1]))

    def _update_bounds(self, t0: float, t1: float) -> None:
        self.clock.bounds = (t0, t1)
        self.transport.set_bounds(t0, t1)
        self.transport.set_time(t0)
