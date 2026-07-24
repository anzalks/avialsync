"""Main window for KinoChronix."""

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from kinochronix.core.session import (
    MarkerEntry,
    SensorEntry,
    SessionState,
    VideoEntry,
    add_recent,
    get_recent,
)
from kinochronix.core.timeline import MasterClock
from kinochronix.engine.player import Player
from kinochronix.ui.annotations import AnnotationPanel, AnnotationStore
from kinochronix.ui.plot_pane import PlotPane
from kinochronix.ui.readout_panel import ReadoutPanel
from kinochronix.ui.transport import Transport
from kinochronix.ui.video_grid import VideoGrid

_AUTOSAVE_INTERVAL_MS = 120_000  # 2 minutes


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("KinoChronix")
        self.resize(1280, 800)

        self._session_path: Path | None = None

        # Core
        self.clock = MasterClock()

        # UI Components
        self.video_grid = VideoGrid(self)
        self.plot_pane = PlotPane(self)
        self.transport = Transport(self)

        # Engine
        self.player = Player(
            self.clock,
            self.video_grid,
            self.plot_pane,
            self.transport,
            self,
        )

        # Annotations
        self.annotation_store = AnnotationStore(self)

        # Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QHBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        from kinochronix.ui.sidebar import SidebarPane

        self.sidebar = SidebarPane(self)
        self.sidebar.open_video_requested.connect(self._open_video)
        self.sidebar.open_sensor_requested.connect(self._open_data)
        self.sidebar.video_offset_changed.connect(self._on_video_offset_changed)
        self.sidebar.video_remove_requested.connect(self._on_video_remove_requested)
        self.sidebar.video_visibility_changed.connect(self.video_grid.set_pane_visible)
        self.sidebar.sensor_remove_requested.connect(self._on_sensor_remove_requested)
        self.sidebar.channel_remove_requested.connect(self._on_channel_remove_requested)
        self.sidebar.channel_visibility_changed.connect(self._on_channel_visibility_changed)
        self.sidebar.grid_mode_changed.connect(self.video_grid.set_grid_mode)

        # Readout panel
        self.readout_panel = ReadoutPanel(self)
        self.plot_pane.sources_changed.connect(self.readout_panel.update_sources)
        self.plot_pane.sources_changed.connect(self.video_grid.set_tracking_readers)
        self.player._readout_panel = self.readout_panel

        # Annotation panel
        self.annotation_panel = AnnotationPanel(self.annotation_store, self)
        self.plot_pane.set_annotation_store(self.annotation_store)

        # Sidebar composite layout
        sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        sidebar_layout.addWidget(self.sidebar, stretch=2)
        sidebar_layout.addWidget(self.readout_panel, stretch=1)
        sidebar_layout.addWidget(self.annotation_panel, stretch=2)

        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        h_splitter.addWidget(sidebar_widget)
        self._h_splitter = h_splitter

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.addWidget(self.video_grid)
        v_splitter.addWidget(self.plot_pane)
        v_splitter.setStretchFactor(0, 3)
        v_splitter.setStretchFactor(1, 1)
        self._v_splitter = v_splitter

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

        # Restore geometry
        self._restore_geometry()

        # A/B loop → region stats
        self.transport.ab_loop_changed.connect(self._on_ab_loop_changed)
        
        # Annotations tracking
        self._annotations: list[dict[str, Any]] = []
        self.transport.annotate_requested.connect(self._on_annotate_requested)

        # Autosave timer
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start(_AUTOSAVE_INTERVAL_MS)

        # Startup diagnostics (deferred so window shows first)
        QTimer.singleShot(500, self._run_diagnostics)

        # Start player tick
        self.player.start()
        
        # Setup global shortcuts
        self._setup_shortcuts()

    # ── Diagnostics ──────────────────────────────────────────────────

    def _run_diagnostics(self) -> None:
        from kinochronix.ui.diagnostics import run_startup_diagnostics

        self._diag = run_startup_diagnostics(self)

    # ── Geometry persistence ─────────────────────────────────────────

    def _restore_geometry(self) -> None:
        settings = QSettings("KinoChronix", "KinoChronix")
        geom = settings.value("window/geometry")
        if geom:
            self.restoreGeometry(geom)
        h_state = settings.value("splitter/horizontal")
        if h_state:
            self._h_splitter.restoreState(h_state)
        v_state = settings.value("splitter/vertical")
        if v_state:
            self._v_splitter.restoreState(v_state)

    def _save_geometry(self) -> None:
        settings = QSettings("KinoChronix", "KinoChronix")
        settings.setValue("window/geometry", self.saveGeometry())
        settings.setValue(
            "splitter/horizontal",
            self._h_splitter.saveState(),
        )
        settings.setValue(
            "splitter/vertical",
            self._v_splitter.saveState(),
        )

    # ── Session save / load ──────────────────────────────────────────

    def _build_session_state(self) -> SessionState:
        """Snapshot current app state into a SessionState."""
        from kinochronix.ui.sidebar import SensorInfoWidget

        bounds = self.clock.state.bounds
        videos = [
            VideoEntry(path=p, offset=pane.time_map.offset)
            for p, pane in zip(
                self.video_grid._paths,
                self.video_grid.panes,
                strict=False,
            )
        ]

        sensors: list[SensorEntry] = []
        for i in range(self.sidebar.sensors_layout.count()):
            item = self.sidebar.sensors_layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if isinstance(w, SensorInfoWidget):
                    sensors.append(SensorEntry(path=w.path, channels=[]))

        markers = [
            MarkerEntry(
                t_start=m.t_start,
                t_end=m.t_end,
                label=m.label,
            )
            for m in self.annotation_store.markers
        ]

        # Capture plot zoom
        plot_x0, plot_x1 = None, None
        if self.plot_pane._master_plot:
            vr = self.plot_pane._master_plot.viewRange()
            plot_x0, plot_x1 = vr[0][0], vr[0][1]

        return SessionState(
            videos=videos,
            sensors=sensors,
            markers=markers,
            t_start=bounds[0],
            t_end=bounds[1],
            plot_x0=plot_x0,
            plot_x1=plot_x1,
        )

    def _save_session(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Session",
            "",
            "KinoChronix Session (*.kcx)",
        )
        if not path:
            return
        if not path.endswith(".kcx"):
            path += ".kcx"

        state = self._build_session_state()
        try:
            state.save(Path(path))
            self._session_path = Path(path)
            add_recent(path)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Save Error",
                f"Could not save session:\n{e}",
            )

    def _open_session(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Session",
            "",
            "KinoChronix Session (*.kcx)",
        )
        if not path:
            return

        try:
            state = SessionState.load(Path(path))
        except Exception as e:
            QMessageBox.critical(
                self,
                "Session Error",
                f"Could not load session:\n{e}",
            )
            return

        self._session_path = Path(path)
        add_recent(path)
        self._restore_session(state)

    def _restore_session(self, state: SessionState) -> None:
        """Load all sources from a SessionState object."""
        # Collect missing files for relink
        missing: list[str] = []
        kind_labels: dict[str, str] = {}

        for ve in state.videos:
            if not Path(ve.path).exists():
                missing.append(ve.path)
                kind_labels[ve.path] = "video"

        for se in state.sensors:
            if not Path(se.path).exists():
                missing.append(se.path)
                kind_labels[se.path] = "sensor"

        relink_map: dict[str, str] = {}
        if missing:
            from kinochronix.ui.relink_dialog import RelinkDialog

            dlg = RelinkDialog(missing, kind_labels, self)
            if dlg.exec() == RelinkDialog.DialogCode.Rejected:
                return
            relink_map = dlg.resolved_mapping()

        for ve in state.videos:
            p = Path(relink_map.get(ve.path, ve.path))
            if p.exists():
                self._load_video(p, offset=ve.offset)

        for se in state.sensors:
            p = Path(relink_map.get(se.path, se.path))
            if p.exists():
                self._start_csv_import(p)

        # Restore annotations
        for me in state.markers:
            if me.t_end is not None:
                self.annotation_store.add_range(me.t_start, me.t_end, me.label)
            else:
                self.annotation_store.add_point(me.t_start, me.label)

        # Restore plot zoom
        if state.plot_x0 is not None and state.plot_x1 is not None and self.plot_pane._master_plot:
            self.plot_pane._master_plot.setXRange(state.plot_x0, state.plot_x1, padding=0)

    def _autosave(self) -> None:
        """Silently autosave if a session path is set."""
        if self._session_path is None:
            return
        try:
            state = self._build_session_state()
            state.save(self._session_path)
        except Exception:
            pass

    # ── A/B loop stats ───────────────────────────────────────────────

    def _on_ab_loop_changed(
        self, t_in: float | None, t_out: float | None
    ) -> None:
        if t_in is not None and t_out is not None:
            lo, hi = min(t_in, t_out), max(t_in, t_out)
            self.readout_panel.show_region_stats(lo, hi)
        else:
            self.readout_panel.clear_region_stats()

    # ── Annotations ──────────────────────────────────────────────────

    def _on_annotate_requested(self) -> None:
        """Record the master time and estimated frame number for all active videos."""
        t_master = self.clock.state.t
        record = {"master_time": round(t_master, 4)}
        
        for pane in self.video_grid._panes:
            if hasattr(pane, "time_map") and pane.time_map.path is not None:
                video_name = pane.time_map.path.name
                t_video = pane.time_map.master_to_source(t_master, pane.time_map.path)
                
                # Dynamically calculate frame number using fps
                fps = 30.0
                if hasattr(pane, "mpv") and pane.mpv is not None:
                    fps = getattr(pane.mpv, 'estimated_vf_fps', 0.0) or 30.0
                    
                frame_number = max(0, round(t_video * fps))
                record[f"{video_name}_frame"] = frame_number
                
        self._annotations.append(record)
        self.statusBar().showMessage(f"Marked frame at {t_master:.3f}s", 2000)

    def _export_annotations(self) -> None:
        """Export accumulated annotations to a CSV file."""
        if not self._annotations:
            QMessageBox.information(self, "No Annotations", "There are no frame markers to export.")
            return
            
        from PySide6.QtWidgets import QFileDialog
        import csv
        
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Export Annotations", "annotations.csv", "CSV Files (*.csv)"
        )
        if not out_path:
            return
            
        fieldnames = set()
        for rec in self._annotations:
            fieldnames.update(rec.keys())
            
        fields = ["master_time"] + sorted([f for f in fieldnames if f != "master_time"])
        
        try:
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(self._annotations)
                
            QMessageBox.information(self, "Export Complete", f"Exported {len(self._annotations)} annotations to:\n{out_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Could not export annotations:\n{str(e)}")

    # ── Keyboard shortcuts ───────────────────────────────────────────

    def _setup_shortcuts(self) -> None:
        from PySide6.QtGui import QKeySequence, QShortcut
        from PySide6.QtCore import Qt
        
        def _toggle_play():
            self.player.set_playing(not self.clock.state.playing)
            
        def _seek_rel(delta: float):
            t = self.clock.state.t + delta
            bounds = self.clock.state.bounds
            self.player.seek(max(bounds[0], min(bounds[1], t)))

        # Play/Pause
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, _toggle_play, context=Qt.ShortcutContext.WindowShortcut)
        
        # Frame Stepping
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, lambda: self.player.step_frame(-1), context=Qt.ShortcutContext.WindowShortcut)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, lambda: self.player.step_frame(1), context=Qt.ShortcutContext.WindowShortcut)
        
        # 1-second jumps
        QShortcut(QKeySequence("Shift+Left"), self, lambda: _seek_rel(-1.0), context=Qt.ShortcutContext.WindowShortcut)
        QShortcut(QKeySequence("Shift+Right"), self, lambda: _seek_rel(1.0), context=Qt.ShortcutContext.WindowShortcut)
        
        # Home/End
        QShortcut(QKeySequence(Qt.Key.Key_Home), self, lambda: self.player.seek(self.clock.state.bounds[0]), context=Qt.ShortcutContext.WindowShortcut)
        QShortcut(QKeySequence(Qt.Key.Key_End), self, lambda: self.player.seek(self.clock.state.bounds[1]), context=Qt.ShortcutContext.WindowShortcut)
        
        # A/B Loop
        QShortcut(QKeySequence(Qt.Key.Key_BracketLeft), self, self.transport._on_ab_in, context=Qt.ShortcutContext.WindowShortcut)
        QShortcut(QKeySequence(Qt.Key.Key_BracketRight), self, self.transport._on_ab_out, context=Qt.ShortcutContext.WindowShortcut)
        
        # Annotation
        QShortcut(QKeySequence(Qt.Key.Key_M), self, self._on_annotate_requested, context=Qt.ShortcutContext.WindowShortcut)
        
        # App actions (Save/Open are already handled by menu shortcuts, but we can bind the others)
        QShortcut(QKeySequence("Ctrl+E"), self, self._export_snapshot, context=Qt.ShortcutContext.WindowShortcut)
        QShortcut(QKeySequence("Ctrl+T"), self, self._cycle_theme, context=Qt.ShortcutContext.WindowShortcut)
        QShortcut(QKeySequence("?"), self, self._show_shortcuts, context=Qt.ShortcutContext.WindowShortcut)

    # ── Window close ─────────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_geometry()
        self._autosave()
        super().closeEvent(event)

    # ── Drag and Drop ────────────────────────────────────────────────

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if not path.exists():
                continue

            if path.is_dir():
                # 1. Check for KCX first
                kcx_files = list(path.glob("*.kcx"))
                if kcx_files:
                    try:
                        state = SessionState.load(kcx_files[0])
                        self._restore_session(state)
                    except Exception as e:
                        QMessageBox.critical(self, "Session Error", str(e))
                    continue
                
                # 2. Load any immediate video files
                for child in path.iterdir():
                    if child.is_file() and child.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv"):
                        self._load_video(child)
                
                # 3. Attempt to load directory as data bundle
                self._start_data_import(path)
            else:
                ext = path.suffix.lower()
                if ext in (".mp4", ".mov", ".avi", ".mkv"):
                    self._load_video(path)
                elif ext == ".kcx":
                    try:
                        state = SessionState.load(path)
                        self._restore_session(state)
                    except Exception as e:
                        QMessageBox.critical(self, "Session Error", str(e))
                else:
                    self._start_data_import(path)

    # ── Menu ─────────────────────────────────────────────────────────

    def _setup_menu(self) -> None:
        menu = self.menuBar()

        # ── File ──
        file_menu = menu.addMenu("File")

        act = file_menu.addAction("Open Video(s)…")
        act.setShortcut("Ctrl+V")
        act.triggered.connect(self._open_video)

        act = file_menu.addAction("Open Sensor/Ephys Data…")
        act.setShortcut("Ctrl+D")
        act.triggered.connect(self._open_data)

        file_menu.addSeparator()

        act = file_menu.addAction("Save Session…")
        act.setShortcut("Ctrl+S")
        act.triggered.connect(self._save_session)

        act = file_menu.addAction("Open Session…")
        act.setShortcut("Ctrl+O")
        act.triggered.connect(self._open_session)

        file_menu.addSeparator()

        act = file_menu.addAction("Export Annotations (CSV)…")
        act.triggered.connect(self._export_annotations)

        # Recent files submenu
        self._recent_menu = file_menu.addMenu("Recent Sessions")
        self._rebuild_recent_menu()

        file_menu.addSeparator()

        act = file_menu.addAction("Export Snapshot…")
        act.setShortcut("Ctrl+E")
        act.triggered.connect(self._export_snapshot)

        act = file_menu.addAction("Export Trimmed Video Clip…")
        act.triggered.connect(self._export_video_clip)

        act = file_menu.addAction("Export Data Slice…")
        act.triggered.connect(self._export_data_slice)

        act = file_menu.addAction("Generate Proxy…")
        act.triggered.connect(self._generate_proxy)

        # ── View ──
        view_menu = menu.addMenu("View")

        theme_menu = view_menu.addMenu("Theme")
        from PySide6.QtGui import QActionGroup

        self._theme_group = QActionGroup(self)
        for label, key in [
            ("System", "system"),
            ("Dark", "dark"),
            ("Light", "light"),
        ]:
            act = theme_menu.addAction(label)
            act.setCheckable(True)
            act.setData(key)
            self._theme_group.addAction(act)
        self._theme_group.triggered.connect(self._on_theme_selected)
        self._sync_theme_menu()

        act = view_menu.addAction("Follow Playhead")
        act.setCheckable(True)
        act.toggled.connect(self.plot_pane.set_follow_playhead)

        # ── Help ──
        help_menu = menu.addMenu("Help")

        act = help_menu.addAction("Keyboard Shortcuts…")
        act.triggered.connect(self._show_shortcuts)

        act = help_menu.addAction("Diagnostics…")
        act.triggered.connect(self._show_diagnostics)

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        recent = get_recent()
        if not recent:
            act = self._recent_menu.addAction("(no recent files)")
            act.setEnabled(False)
            return
        for rpath in recent:
            act = self._recent_menu.addAction(Path(rpath).name)
            act.setToolTip(rpath)
            act.triggered.connect(lambda _checked, p=rpath: self._open_recent(p))

    def _open_recent(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            QMessageBox.warning(
                self,
                "File Not Found",
                f"Session file no longer exists:\n{path}",
            )
            return
        try:
            state = SessionState.load(p)
            self._session_path = p
            self._restore_session(state)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Session Error",
                f"Could not load session:\n{e}",
            )

    # ── Theme selection ─────────────────────────────────────────────

    def _on_theme_selected(self, action) -> None:
        from PySide6.QtWidgets import QApplication

        from kinochronix.ui.theme import apply_theme

        apply_theme(QApplication.instance(), action.data())

    def _sync_theme_menu(self) -> None:
        from kinochronix.ui.theme import current_preference

        pref = current_preference()
        for act in self._theme_group.actions():
            if act.data() == pref:
                act.setChecked(True)
                break

    def _cycle_theme(self) -> None:
        from PySide6.QtWidgets import QApplication

        from kinochronix.ui.theme import apply_theme, current_preference

        order = ["system", "dark", "light"]
        pref = current_preference()
        idx = order.index(pref) if pref in order else 0
        new_pref = order[(idx + 1) % len(order)]
        apply_theme(QApplication.instance(), new_pref)
        self._sync_theme_menu()

    # ── Shortcuts dialog ─────────────────────────────────────────────

    def _show_shortcuts(self) -> None:
        from kinochronix.ui.shortcuts_dialog import ShortcutsDialog

        dlg = ShortcutsDialog(self)
        dlg.exec()

    # ── Diagnostics dialog ───────────────────────────────────────────

    def _show_diagnostics(self) -> None:
        from kinochronix.ui.diagnostics import format_diagnostics

        diag = getattr(self, "_diag", {})
        text = format_diagnostics(diag)

        msg = QMessageBox(self)
        msg.setWindowTitle("Diagnostics")
        msg.setText(text)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        msg.exec()

    # ── Snapshot export ──────────────────────────────────────────────

    def _export_snapshot(self) -> None:
        from kinochronix.engine.export import (
            save_snapshot,
            snapshot_widget,
        )

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Snapshot",
            "snapshot.png",
            "PNG Images (*.png)",
        )
        if not path:
            return

        video_px = snapshot_widget(self.video_grid)
        plot_px = snapshot_widget(self.plot_pane)
        try:
            save_snapshot(video_px, plot_px, Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    # ── Data slice export ────────────────────────────────────────────

    def _export_data_slice(self) -> None:
        if not self.plot_pane.channels:
            QMessageBox.information(
                self,
                "No Data",
                "Load sensor data before exporting.",
            )
            return

        # Use A/B loop region if set, else full bounds
        t0, t1 = self.clock.state.bounds
        if self.player._ab_in is not None and self.player._ab_out is not None:
            t0 = min(self.player._ab_in, self.player._ab_out)
            t1 = max(self.player._ab_in, self.player._ab_out)

        path, filt = QFileDialog.getSaveFileName(
            self,
            "Export Data Slice",
            "data_export.csv",
            "CSV files (*.csv);;Parquet files (*.parquet)",
        )
        if not path:
            return

        from kinochronix.engine.export import (
            export_data_slice_csv,
            export_data_slice_parquet,
        )

        readers = [ch.reader for ch in self.plot_pane.channels]
        try:
            if path.endswith(".parquet"):
                export_data_slice_parquet(readers, t0, t1, Path(path))
            else:
                export_data_slice_csv(readers, t0, t1, Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _export_video_clip(self) -> None:
        """Export a trimmed video clip for all loaded videos based on A/B loop."""
        if not self.video_grid._paths:
            QMessageBox.warning(self, "Export", "No videos are loaded.")
            return

        t0 = self.transport._ab_in_t
        t1 = self.transport._ab_out_t
        if t0 is None or t1 is None:
            QMessageBox.warning(
                self, "Export Error", "Please set an A/B loop first ([ and ] buttons)."
            )
            return

        if t0 > t1:
            t0, t1 = t1, t0

        from kinochronix.engine.export import trim_video_clip
        from pathlib import Path

        if len(self.video_grid._paths) == 1:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Trimmed Video", "", "Video files (*.mp4 *.mkv *.mov *.avi)"
            )
            if not path:
                return
            success = trim_video_clip(self.video_grid._paths[0], t0, t1, Path(path))
            if success:
                QMessageBox.information(self, "Export Complete", "Video clip exported successfully.")
            else:
                QMessageBox.critical(self, "Export Failed", "ffmpeg failed to trim the video.")
        else:
            dir_path = QFileDialog.getExistingDirectory(self, "Select Directory for Trimmed Clips")
            if not dir_path:
                return
            
            out_dir = Path(dir_path)
            success_count = 0
            for orig_path in self.video_grid._paths:
                p = Path(orig_path)
                out_path = out_dir / f"{p.stem}_trim{p.suffix}"
                if trim_video_clip(orig_path, t0, t1, out_path):
                    success_count += 1
            
            if success_count == len(self.video_grid._paths):
                QMessageBox.information(self, "Export Complete", f"Exported {success_count} clips.")
            else:
                QMessageBox.warning(self, "Export Incomplete", f"Exported {success_count} of {len(self.video_grid._paths)} clips.")

    # ── Proxy generation ─────────────────────────────────────────────

    def _generate_proxy(self) -> None:
        if not self.video_grid._paths:
            QMessageBox.information(
                self,
                "No Videos",
                "Load a video before generating proxies.",
            )
            return

        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QProgressDialog

        from kinochronix.engine.proxy import ProxyWorker

        # Proxy the first video for now
        video_path = Path(self.video_grid._paths[0])

        self._proxy_thread = QThread()
        self._proxy_worker = ProxyWorker(video_path)
        self._proxy_worker.moveToThread(self._proxy_thread)

        dlg = QProgressDialog(
            f"Generating proxy for {video_path.name}…",
            "Cancel",
            0,
            100,
            self,
        )
        dlg.setWindowTitle("Proxy Generation")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        self._proxy_dlg = dlg

        self._proxy_thread.started.connect(self._proxy_worker.run)
        self._proxy_worker.progress.connect(dlg.setValue)
        dlg.canceled.connect(self._proxy_worker.cancel)

        self._proxy_worker.finished.connect(self._on_proxy_finished)
        self._proxy_worker.finished.connect(self._proxy_thread.quit)
        self._proxy_worker.error.connect(self._on_proxy_error)
        self._proxy_worker.error.connect(self._proxy_thread.quit)
        self._proxy_thread.finished.connect(self._proxy_thread.deleteLater)

        dlg.show()
        self._proxy_thread.start()

    def _on_proxy_finished(self, orig: str, proxy: str) -> None:
        self._proxy_dlg.close()
        QMessageBox.information(
            self,
            "Proxy Ready",
            f"Proxy saved:\n{proxy}",
        )

    def _on_proxy_error(self, err: str) -> None:
        self._proxy_dlg.close()
        QMessageBox.critical(self, "Proxy Error", err)

    # ── Source loading ───────────────────────────────────────────────

    def _load_video(self, path: Path, offset: float = 0.0) -> None:
        self.video_grid.add_pane(str(path))
        from kinochronix.loaders.video_standard import (
            VideoStandardLoader,
        )

        vloader = VideoStandardLoader()
        try:
            vloader.open(path, {})
            b = vloader.time_bounds()
            self._update_bounds(b[0], b[1])
            metadata = {
                "fps": vloader._fps,
                "codec": getattr(vloader, "_codec", "unknown"),
                "duration": vloader._duration,
            }
            self.sidebar.add_video(str(path), metadata)
            if offset != 0.0:
                self.video_grid.set_offset(str(path), offset)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Video Error",
                f"Could not open video:\n{path}\n\n{e}",
            )

    def _on_video_offset_changed(self, path: str, offset: float) -> None:
        self.video_grid.set_offset(path, offset)
        self.clock.play()
        self.clock.pause()

    def _on_video_remove_requested(self, path: str) -> None:
        self.video_grid.remove_pane(path)
        self.sidebar.remove_video(path)

    def _on_sensor_remove_requested(self, path: str) -> None:
        from kinochronix.core.cache import CacheManager

        cache_mgr = CacheManager(loader_version=1)
        cache_dir = cache_mgr.get_cache_dir(Path(path))
        self.plot_pane.remove_channels(cache_dir)
        self.sidebar.remove_sensor(path)

    def _on_channel_remove_requested(self, path: str, channel: str) -> None:
        self.plot_pane.remove_channel(channel)
        self._update_window_title()

    def _on_channel_visibility_changed(self, path: str, channel: str, is_visible: bool) -> None:
        self.plot_pane.set_channel_visible(channel, is_visible)

    def _on_video_visibility_changed(self, path: str, is_visible: bool) -> None:
        self.video_grid.set_pane_visible(path, is_visible)

    def _open_video(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Open Video(s)")
        for path in paths:
            if path:
                self._load_video(Path(path))

    def _open_data(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Sensor/Ephys Data")
        if path:
            self._start_data_import(Path(path))

    def _start_data_import(self, path: Path) -> None:
        from kinochronix.core.registry import LoaderRegistry
        registry = LoaderRegistry()
        loader_cls = registry.find_best_loader(path)
        if not loader_cls:
            QMessageBox.warning(self, "Unsupported File", "No suitable loader found for this file.")
            return
            
        from kinochronix.loaders.csv_loader import CSVLoader
        from kinochronix.loaders.tracking_loader import TrackingLoader
        if loader_cls is CSVLoader:
            from kinochronix.ui.import_wizard import ImportWizard
            wizard = ImportWizard(path, self)
            if wizard.exec() != ImportWizard.DialogCode.Accepted:
                return
            config = wizard.config()
        elif loader_cls is TrackingLoader:
            from PySide6.QtWidgets import QInputDialog
            fps, ok = QInputDialog.getDouble(
                self, "Tracking Data FPS", 
                "Enter the video frame rate for this tracking data:", 
                30.0, 1.0, 1000.0, 2
            )
            if not ok:
                return
            config = {"fps": fps}
        else:
            # NeoLoader and other headless loaders that don't need UI config
            config = {}

        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QProgressDialog

        from kinochronix.engine.importer import ImportWorker

        self._import_thread = QThread()
        self._import_worker = ImportWorker(path, config, loader_cls)
        self._import_worker.moveToThread(self._import_thread)

        self._progress_dialog = QProgressDialog("Importing CSV…", "Cancel", 0, 100, self)
        self._progress_dialog.setWindowTitle("Importing Data")
        self._progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress_dialog.setAutoClose(True)
        self._progress_dialog.setAutoReset(True)
        self._progress_dialog.setValue(0)

        self._import_thread.started.connect(self._import_worker.run)
        self._import_worker.progress.connect(self._progress_dialog.setValue)
        self._progress_dialog.canceled.connect(self._import_worker.cancel)

        self._import_worker.finished.connect(self._on_import_finished)
        self._import_worker.finished.connect(self._import_thread.quit)
        self._import_worker.finished.connect(self._import_worker.deleteLater)
        self._import_thread.finished.connect(self._import_thread.deleteLater)

        self._import_worker.error.connect(self._on_import_error)
        self._import_worker.error.connect(self._import_thread.quit)

        self._progress_dialog.show()
        self._import_thread.start()

    def _on_import_finished(
        self,
        path: str,
        cache_dir: str,
        channels: list[str],
        bounds: tuple[float, float],
    ) -> None:
        self._progress_dialog.close()
        self.plot_pane.load_channels(Path(cache_dir), channels)
        self._update_bounds(bounds[0], bounds[1])
        self.sidebar.add_sensor(path, channels)

    def _on_import_error(self, err_msg: str) -> None:
        self._progress_dialog.close()
        QMessageBox.critical(
            self,
            "Import Error",
            f"Failed to import CSV:\n{err_msg}",
        )

    def _update_bounds(self, t0: float, t1: float) -> None:
        if self.clock.state.bounds == (0.0, 0.0):
            new_bounds = (t0, t1)
            self.plot_pane.set_x_range(t0, t1)
        else:
            curr_t0, curr_t1 = self.clock.state.bounds
            new_bounds = (
                min(curr_t0, t0),
                max(curr_t1, t1),
            )

        self.clock.set_bounds(*new_bounds)
        self.transport.set_bounds(*new_bounds)
        self.transport.set_time(new_bounds[0])
