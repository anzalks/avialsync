"""Main window for KinoChronix."""

import dataclasses
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from kinochronix.core.inspection import SourceInspection
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
from kinochronix.ui.time_format import TimeDisplayMode
from kinochronix.ui.transport import Transport
from kinochronix.ui.video_grid import VideoGrid

_AUTOSAVE_INTERVAL_MS = 120_000  # 2 minutes


class MainWindow(QMainWindow):
    time_mode_changed = Signal(object)  # TimeDisplayMode

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("KinoChronix")
        self.resize(1280, 800)

        self._session_path: Path | None = None

        # fps of each loaded video (str(path) → fps); used for frame-indexed source resolution
        self._video_fps: dict[str, float] = {}
        # DLC/frame-indexed sources loaded without a video present (path, provisional_fps)
        self._frame_indexed_sources: list[tuple[Path, float]] = []
        # Inspection data keyed by str(path)
        self._inspections: dict[str, SourceInspection] = {}
        # Units dict keyed by channel_id; populated from import config or wizard
        self._channel_units: dict[str, str] = {}
        self._time_mode = TimeDisplayMode.RELATIVE

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
        self.sidebar.video_badge_clicked.connect(self._show_video_properties)
        self.sidebar.sensor_badge_clicked.connect(self._show_sensor_properties)
        self.sidebar.sensor_report_requested.connect(self._show_import_report)

        # Readout panel
        self.readout_panel = ReadoutPanel(self)
        self.plot_pane.sources_changed.connect(self._on_sources_changed)
        self.plot_pane.sources_changed.connect(self.video_grid.set_tracking_readers)
        self.plot_pane.measure_changed.connect(self._on_measure_changed)
        self.player._readout_panel = self.readout_panel

        # Annotation panel
        self.annotation_panel = AnnotationPanel(self.annotation_store, self)
        self.plot_pane.set_annotation_store(self.annotation_store)

        # Sidebar composite layout — vertical splitter so sections are user-resizable
        self._left_splitter = QSplitter(Qt.Orientation.Vertical)
        self._left_splitter.addWidget(self.sidebar)
        self._left_splitter.addWidget(self.readout_panel)
        self._left_splitter.addWidget(self.annotation_panel)
        self._left_splitter.setStretchFactor(0, 2)
        self._left_splitter.setStretchFactor(1, 1)
        self._left_splitter.setStretchFactor(2, 2)

        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        h_splitter.addWidget(self._left_splitter)
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

        # Transport signals (D-022)
        self.transport.ab_loop_changed.connect(self._on_ab_loop_changed)
        self.transport.annotate_requested.connect(self._on_annotate_requested)
        self.transport.snapshot_requested.connect(self._export_snapshot)
        self.transport.fullscreen_requested.connect(self._toggle_fullscreen)
        self.transport.jump_requested.connect(self._on_jump_requested)

        # Video pane right-click context menu (D-022)
        self.video_grid.pane_right_clicked.connect(self._on_pane_right_clicked)

        # Plot annotate-at (D-022)
        self.plot_pane.annotate_at_requested.connect(self._on_annotate_at_requested)

        # Autosave timer
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start(_AUTOSAVE_INTERVAL_MS)

        # Startup diagnostics (deferred so window shows first)
        QTimer.singleShot(500, self._run_diagnostics)

        # Start player tick
        self.player.start()

        # Setup global shortcuts (must come after _setup_menu so _all_actions exists)
        self._setup_shortcuts()

    # ── Sources / units ──────────────────────────────────────────────

    def _on_sources_changed(self, readers: list[Any]) -> None:
        """Forward to ReadoutPanel with accumulated units for known channels."""
        self.readout_panel.update_sources(readers, self._channel_units)

    # ── Inspection / properties dialogs ─────────────────────────────

    def _show_video_properties(self, path: str) -> None:
        """Show the VideoPropertiesPanel for a video (triggered by badge click)."""
        ins = self._inspections.get(path)
        if ins is None:
            return
        from kinochronix.ui.import_report import ImportReportDialog

        dlg = ImportReportDialog(ins, self)
        dlg.setWindowTitle(f"Video Properties — {Path(path).name}")
        dlg.exec()

    def _show_sensor_properties(self, path: str) -> None:
        """Show sensor properties for a data source."""
        ins = self._inspections.get(path)
        if ins is None:
            return
        from kinochronix.ui.import_report import ImportReportDialog

        dlg = ImportReportDialog(ins, self)
        dlg.setWindowTitle(f"Sensor Properties — {Path(path).name}")
        dlg.exec()

    def _show_import_report(self, path: str) -> None:
        """Show the full ImportReport dialog for a data source."""
        ins = self._inspections.get(path)
        if ins is None:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(self, "No Report", f"No import report for:\n{path}")
            return
        from kinochronix.ui.import_report import ImportReportDialog

        dlg = ImportReportDialog(ins, self)
        dlg.exec()

    # ── Measure delta ────────────────────────────────────────────────

    def _on_measure_changed(self, t_a: float, t_b: float) -> None:
        """Forward measure pins to ReadoutPanel with live camera states."""
        camera_states = []
        for pane in self.video_grid.panes:
            fps = getattr(pane, "_fps", 0.0) or 0.0
            t_pos = getattr(pane, "_t_pos", t_a)  # best-effort; fallback to t_a
            label = getattr(pane, "_label", "cam")
            camera_states.append((label, t_pos, fps))
        self.readout_panel.show_delta(t_a, t_b, camera_states or None)

    # ── Time display mode ────────────────────────────────────────────

    def _set_time_mode(self, mode: TimeDisplayMode) -> None:
        self._time_mode = mode
        self.transport.set_time_mode(mode)
        self.time_mode_changed.emit(mode)

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
        left_state = settings.value("splitter/left")
        if left_state:
            self._left_splitter.restoreState(left_state)

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
        settings.setValue("splitter/left", self._left_splitter.saveState())

    # ── Session save / load ──────────────────────────────────────────

    def _build_session_state(self) -> SessionState:
        """Snapshot current app state into a SessionState."""
        from kinochronix.ui.sidebar import SensorInfoWidget

        bounds = self.clock.state.bounds
        videos = []
        for p, pane in zip(self.video_grid._paths, self.video_grid.panes, strict=False):
            ins = self._inspections.get(p)
            videos.append(
                VideoEntry(
                    path=p,
                    offset=pane.time_map.offset,
                    integrity_flags=ins.integrity_flags.as_dict() if ins else {},
                    metadata=ins.import_config if ins else {},
                )
            )

        sensors: list[SensorEntry] = []
        for i in range(self.sidebar.sensors_layout.count()):
            item = self.sidebar.sensors_layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if isinstance(w, SensorInfoWidget):
                    ins = self._inspections.get(w.path)
                    sensors.append(
                        SensorEntry(
                            path=w.path,
                            channels=[],
                            loader_id=ins.loader_id if ins else "",
                            import_config=dict(ins.import_config) if ins else {},
                            import_report=(
                                ins.import_report.as_dict() if ins and ins.import_report else None
                            ),
                        )
                    )

        markers = [
            MarkerEntry(
                t_start=m.t_start,
                t_end=m.t_end,
                label=m.label,
                video_frames=[dataclasses.asdict(vf) for vf in m.video_frames],
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
                if ve.integrity_flags or ve.metadata:
                    from kinochronix.core.inspection import IntegrityFlags

                    ins = SourceInspection(
                        path=str(p),
                        integrity_flags=IntegrityFlags.from_dict(ve.integrity_flags),
                        import_config=ve.metadata,
                    )
                    self._inspections[str(p)] = ins

        for se in state.sensors:
            p = Path(relink_map.get(se.path, se.path))
            if p.exists():
                self._start_data_import(p)
                if se.loader_id or se.import_report:
                    from kinochronix.core.inspection import ImportReport

                    ins = SourceInspection(
                        path=str(p),
                        loader_id=se.loader_id,
                        import_config=dict(se.import_config),
                        import_report=(
                            ImportReport.from_dict(se.import_report) if se.import_report else None
                        ),
                    )
                    self._inspections[str(p)] = ins

        # Restore annotations
        from kinochronix.ui.annotations import VideoFrame

        for me in state.markers:
            vfs = [
                VideoFrame(
                    path=str(vf["path"]),
                    frame_index=int(vf["frame_index"]),
                    media_timestamp=float(vf["media_timestamp"]),
                )
                for vf in me.video_frames
            ]
            if me.t_end is not None:
                self.annotation_store.add_range(me.t_start, me.t_end, me.label, video_frames=vfs)
            else:
                self.annotation_store.add_point(me.t_start, me.label, video_frames=vfs)

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

    def _on_ab_loop_changed(self, t_in: float | None, t_out: float | None) -> None:
        if t_in is not None and t_out is not None:
            lo, hi = min(t_in, t_out), max(t_in, t_out)
            self.readout_panel.show_region_stats(lo, hi)
        else:
            self.readout_panel.clear_region_stats()

    # ── Annotations ──────────────────────────────────────────────────

    def _on_annotate_requested(self) -> None:
        """Record master time and per-video frame snapshot for all active videos."""
        from kinochronix.ui.annotations import VideoFrame

        t_master = self.clock.state.t
        video_frames = [
            VideoFrame(
                path=str(r["path"]),
                frame_index=int(r["frame_index"]),
                media_timestamp=float(r["media_timestamp"]),
            )
            for r in self.video_grid.frame_records_at(t_master)
        ]
        self.annotation_store.add_point(t_master, video_frames=video_frames)
        self.statusBar().showMessage(f"Marked frame at {t_master:.3f}s", 2000)

    def _export_annotations(self) -> None:
        """Export annotation markers to CSV — one row per (marker, video)."""
        if not self.annotation_store.markers:
            QMessageBox.information(self, "No Annotations", "There are no markers to export.")
            return
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Export Annotations", "annotations.csv", "CSV Files (*.csv)"
        )
        if not out_path:
            return
        try:
            self.annotation_store.export_csv(Path(out_path))
            QMessageBox.information(
                self,
                "Export Complete",
                f"Exported {len(self.annotation_store.markers)} markers to:\n{out_path}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Could not export annotations:\n{e}")

    # ── Keyboard shortcuts ───────────────────────────────────────────

    def _setup_shortcuts(self) -> None:
        """Register window-scoped QActions for all keyboard-only shortcuts (D-022).

        Rules (D-022.1):
        - Menu QActions already carry their shortcuts — no duplicate QShortcut.
        - Transport-button shortcuts emit the matching Transport signal.
        - Non-transport keyboard-only shortcuts (Home/End) may call the engine directly.
        """
        from collections.abc import Callable

        from PySide6.QtGui import QKeySequence

        _wsc = Qt.ShortcutContext.WindowShortcut

        def _act(text: str, category: str, handler: Callable[[], None], *keys: Any) -> QAction:
            a = QAction(text, self)
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.setShortcutContext(_wsc)
            a.triggered.connect(handler)
            a.setProperty("kc_category", category)
            self.addAction(a)
            self._all_actions.append(a)
            return a

        # ── Playback ──────────────────────────────────────────────────
        # Space: toggle play through transport signal (D-022.1 — duplicates Play button)
        _act(
            "Play / Pause",
            "Playback",
            lambda: self.transport.play_toggled.emit(not self.clock.state.playing),
            Qt.Key.Key_Space,
        )

        # Frame step: emit transport signal (D-022.1 — duplicates ◀/▶ buttons)
        _act(
            "Step back 1 frame",
            "Playback",
            lambda: self.transport.frame_step_requested.emit(-1),
            Qt.Key.Key_Left,
            Qt.Key.Key_Comma,
        )
        _act(
            "Step forward 1 frame",
            "Playback",
            lambda: self.transport.frame_step_requested.emit(1),
            Qt.Key.Key_Right,
            Qt.Key.Key_Period,
        )

        # Jump ±1 s: emit transport signal (D-022.1 — duplicates –1s/+1s buttons)
        _act(
            "Jump back 1 second",
            "Playback",
            lambda: self.transport.jump_requested.emit(-1.0),
            "Shift+Left",
            "J",
        )
        _act(
            "Jump forward 1 second",
            "Playback",
            lambda: self.transport.jump_requested.emit(1.0),
            "Shift+Right",
        )

        # J/K/L shuttle (D-022.4) — J already aliased above
        _act(
            "Pause",
            "Playback",
            lambda: self.transport.play_toggled.emit(False),
            "K",
        )
        _act(
            "Step up playback rate",
            "Playback",
            self.transport.step_rate_up,
            "L",
        )

        # Home/End: no transport button, call player directly
        _act(
            "Jump to start",
            "Playback",
            lambda: self.player.seek(self.clock.state.bounds[0]),
            Qt.Key.Key_Home,
        )
        _act(
            "Jump to end",
            "Playback",
            lambda: self.player.seek(self.clock.state.bounds[1]),
            Qt.Key.Key_End,
        )

        # ── Marking ───────────────────────────────────────────────────
        # A/B in/out: route through the same internal method as the transport buttons
        # (public API as required by D-022.1 — no direct call to engine privates)
        _act(
            "Set A/B in-point",
            "Marking",
            self.transport.ab_in,
            Qt.Key.Key_BracketLeft,
            "I",
        )
        _act(
            "Set A/B out-point",
            "Marking",
            self.transport.ab_out,
            Qt.Key.Key_BracketRight,
            "O",
        )
        _act(
            "Add marker at playhead",
            "Marking",
            self._on_annotate_requested,
            "M",
        )

        # ── View ──────────────────────────────────────────────────────
        # Ctrl+T: cycle theme (no menu item)
        _act("Cycle theme", "View", self._cycle_theme, "Ctrl+T")

        # Plot zoom in/out (D-022)
        _act("Plot zoom in", "View", self.plot_pane.zoom_in, "+")
        _act("Plot zoom out", "View", self.plot_pane.zoom_out, "-")

        # "?" as alias for F1 shortcuts dialog (StandardKey.HelpContents already on menu action)
        _act(
            "Keyboard shortcuts (alias)",
            "View",
            self._show_shortcuts,
            "?",
        )

    # ── Window close ─────────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_geometry()
        self._autosave()
        super().closeEvent(event)

    # ── Drag and Drop ────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
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
        from PySide6.QtGui import QActionGroup, QKeySequence

        # Collects every QAction with a shortcut — read by _show_shortcuts().
        self._all_actions: list[QAction] = []

        def _reg(act: QAction, category: str) -> QAction:
            """Tag an action with its shortcuts-dialog category."""
            act.setProperty("kc_category", category)
            if act.shortcuts():
                self._all_actions.append(act)
            return act

        menu = self.menuBar()

        # ── File ──────────────────────────────────────────────────────
        file_menu = menu.addMenu("File")

        # Ctrl+Shift+V (not Ctrl+V — system Paste collision, D-022.7 / Trap §18)
        act = file_menu.addAction("Open Video(s)…")
        act.setShortcut(QKeySequence("Ctrl+Shift+V"))
        act.triggered.connect(self._open_video)
        _reg(act, "File")

        # Ctrl+Shift+D (not Ctrl+D — bookmark/dock collision, D-022.7 / Trap §18)
        act = file_menu.addAction("Open Sensor/Ephys Data…")
        act.setShortcut(QKeySequence("Ctrl+Shift+D"))
        act.triggered.connect(self._open_data)
        _reg(act, "File")

        file_menu.addSeparator()

        act = file_menu.addAction("Save Session…")
        act.setShortcut(QKeySequence(QKeySequence.StandardKey.Save))
        act.triggered.connect(self._save_session)
        _reg(act, "File")

        act = file_menu.addAction("Open Session…")
        act.setShortcut(QKeySequence(QKeySequence.StandardKey.Open))
        act.triggered.connect(self._open_session)
        _reg(act, "File")

        file_menu.addSeparator()

        act = file_menu.addAction("Export Annotations (CSV)…")
        act.triggered.connect(self._export_annotations)

        self._recent_menu = file_menu.addMenu("Recent Sessions")
        self._rebuild_recent_menu()

        file_menu.addSeparator()

        # Export Snapshot — Ctrl+E is the single authority; no duplicate QShortcut
        self._act_snapshot = file_menu.addAction("Export Snapshot…")
        self._act_snapshot.setShortcut(QKeySequence("Ctrl+E"))
        self._act_snapshot.triggered.connect(self._export_snapshot)
        _reg(self._act_snapshot, "File")

        act = file_menu.addAction("Export Trimmed Video Clip…")
        act.triggered.connect(self._export_video_clip)

        act = file_menu.addAction("Export Data Slice…")
        act.triggered.connect(self._export_data_slice)

        act = file_menu.addAction("Generate Proxy…")
        act.triggered.connect(self._generate_proxy)

        file_menu.addSeparator()

        # Quit — macOS QuitRole moves this to the app menu (D-022.3)
        act = file_menu.addAction("Quit")
        act.setShortcut(QKeySequence(QKeySequence.StandardKey.Quit))
        act.setMenuRole(QAction.MenuRole.QuitRole)
        act.triggered.connect(self.close)
        _reg(act, "File")

        # ── View ──────────────────────────────────────────────────────
        view_menu = menu.addMenu("View")

        theme_menu = view_menu.addMenu("Theme")
        self._theme_group = QActionGroup(self)
        for label, key in [("System", "system"), ("Dark", "dark"), ("Light", "light")]:
            ta = theme_menu.addAction(label)
            ta.setCheckable(True)
            ta.setData(key)
            self._theme_group.addAction(ta)
        self._theme_group.triggered.connect(self._on_theme_selected)
        self._sync_theme_menu()

        time_menu = view_menu.addMenu("Time Display")
        self._time_mode_group = QActionGroup(self)
        for label, mode in [
            ("Relative (HH:MM:SS)", TimeDisplayMode.RELATIVE),
            ("UTC", TimeDisplayMode.UTC),
            ("Local time of day", TimeDisplayMode.LOCAL_TOD),
        ]:
            ta = time_menu.addAction(label)
            ta.setCheckable(True)
            ta.setData(mode)
            ta.setChecked(mode == TimeDisplayMode.RELATIVE)
            self._time_mode_group.addAction(ta)
        self._time_mode_group.triggered.connect(lambda a: self._set_time_mode(a.data()))

        view_menu.addSeparator()

        # Reset Plot Zoom — single authority (D-022.1); QShortcut removed from _setup_shortcuts
        self._act_reset_zoom = view_menu.addAction("Reset Plot Zoom")
        self._act_reset_zoom.setShortcut(QKeySequence("Ctrl+0"))
        self._act_reset_zoom.triggered.connect(self.plot_pane.reset_zoom)
        _reg(self._act_reset_zoom, "View")

        act = view_menu.addAction("Follow Playhead")
        act.setCheckable(True)
        act.toggled.connect(self.plot_pane.set_follow_playhead)

        # Fullscreen toggle — StandardKey.FullScreen = F11 / Ctrl+Cmd+F on macOS (D-022.2)
        self._act_fullscreen = view_menu.addAction("Toggle Pane Fullscreen")
        self._act_fullscreen.setShortcut(QKeySequence(QKeySequence.StandardKey.FullScreen))
        self._act_fullscreen.triggered.connect(self._toggle_fullscreen)
        _reg(self._act_fullscreen, "View")

        # Pass reset-zoom action to plot pane so the context menu uses the same object (D-022)
        self.plot_pane.set_context_actions([self._act_reset_zoom])

        # ── Help ──────────────────────────────────────────────────────
        help_menu = menu.addMenu("Help")

        # Shortcuts dialog: F1 primary (HelpContents); "?" alias added in _setup_shortcuts
        self._act_shortcuts = help_menu.addAction("Keyboard Shortcuts…")
        self._act_shortcuts.setShortcut(QKeySequence(QKeySequence.StandardKey.HelpContents))
        self._act_shortcuts.triggered.connect(self._show_shortcuts)
        _reg(self._act_shortcuts, "View")

        act = help_menu.addAction("Diagnostics…")
        act.triggered.connect(self._show_diagnostics)

        # About — macOS AboutRole moves this to the app menu (D-022.3)
        act = help_menu.addAction("About KinoChronix")
        act.setMenuRole(QAction.MenuRole.AboutRole)
        act.triggered.connect(self._show_about)

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

    def _on_theme_selected(self, action: QAction) -> None:
        from PySide6.QtWidgets import QApplication

        from kinochronix.ui.theme import apply_theme

        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, action.data())

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
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, new_pref)
        self._sync_theme_menu()

    # ── Fullscreen / jump / pane context menu ───────────────────────

    def _toggle_fullscreen(self) -> None:
        """Toggle fullscreen for the first (or only) pane (D-022)."""
        self.video_grid.toggle_fullscreen()

    def _on_jump_requested(self, delta: float) -> None:
        """Clamp and seek relative to the current playhead (D-022)."""
        t = self.clock.state.t + delta
        bounds = self.clock.state.bounds
        self.player.seek(max(bounds[0], min(bounds[1], t)), exact=True)

    def _on_pane_right_clicked(self, path: str, pos: Any) -> None:
        """Show a per-pane context menu on video right-click (D-022)."""
        from PySide6.QtWidgets import QApplication, QMenu

        menu = QMenu(self)

        act_fs = menu.addAction("Fullscreen this camera")
        act_snap = menu.addAction("Snapshot this camera")
        menu.addSeparator()
        act_props = menu.addAction("Properties…")
        act_copy = menu.addAction("Copy frame info")

        chosen = menu.exec(pos)
        if chosen == act_fs:
            self.video_grid.toggle_fullscreen(path)
        elif chosen == act_snap:
            self._export_snapshot_for_pane(path)
        elif chosen == act_props:
            self._show_video_properties(path)
        elif chosen == act_copy:
            records = self.video_grid.frame_records_at(self.clock.state.t)
            info_lines = []
            for r in records:
                if r["path"] == path:
                    info_lines.append(
                        f"path={r['path']}\n"
                        f"frame={r['frame_index']}\n"
                        f"media_t={r['media_timestamp']:.6f}"
                    )
            text = "\n".join(info_lines) if info_lines else f"path={path}"
            cb = QApplication.clipboard()
            if cb:
                cb.setText(text)

    def _export_snapshot_for_pane(self, path: str) -> None:
        """Export a snapshot of a single video pane."""
        try:
            idx = self.video_grid._paths.index(path)
        except ValueError:
            return
        pane = self.video_grid.panes[idx]
        from kinochronix.engine.export import snapshot_widget

        px = snapshot_widget(pane)
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Snapshot — {Path(path).name}",
            f"snapshot_{Path(path).stem}.png",
            "PNG Images (*.png)",
        )
        if not out_path:
            return
        from kinochronix.engine.export import save_snapshot

        try:
            save_snapshot(px, None, Path(out_path))
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _on_annotate_at_requested(self, t: float) -> None:
        """Add a point marker at the clicked time on the plot (D-022)."""
        from kinochronix.ui.annotations import VideoFrame

        video_frames = [
            VideoFrame(
                path=str(r["path"]),
                frame_index=int(r["frame_index"]),
                media_timestamp=float(r["media_timestamp"]),
            )
            for r in self.video_grid.frame_records_at(t)
        ]
        self.annotation_store.add_point(t, video_frames=video_frames)
        self.statusBar().showMessage(f"Marked frame at {t:.3f}s", 2000)

    # ── About dialog ─────────────────────────────────────────────────

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About KinoChronix",
            "KinoChronix — multi-camera video + time-series scrubber.\nApache-2.0 licence.",
        )

    # ── Shortcuts dialog ─────────────────────────────────────────────

    def _show_shortcuts(self) -> None:
        from kinochronix.ui.shortcuts_dialog import ShortcutsDialog

        # Group all registered QActions by category tag (D-022.6)
        groups: dict[str, list[QAction]] = {}
        for act in getattr(self, "_all_actions", []):
            if not act.shortcuts():
                continue
            cat = str(act.property("kc_category") or "Other")
            groups.setdefault(cat, []).append(act)

        dlg = ShortcutsDialog(groups, self)
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

        from pathlib import Path

        from kinochronix.engine.export import trim_video_clip

        if len(self.video_grid._paths) == 1:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Trimmed Video", "", "Video files (*.mp4 *.mkv *.mov *.avi)"
            )
            if not path:
                return
            success = trim_video_clip(self.video_grid._paths[0], t0, t1, Path(path))
            if success:
                QMessageBox.information(self, "Export Complete", "Video clip exported.")
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
                n_total = len(self.video_grid._paths)
                QMessageBox.warning(
                    self, "Export Incomplete", f"Exported {success_count} of {n_total} clips."
                )

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
        from kinochronix.loaders.video_standard import VideoStandardLoader

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
            self.sidebar.set_video_loader(str(path), vloader)
            # set_video_pane: pane is last added entry in video_grid.panes
            if self.video_grid.panes:
                self.sidebar.set_video_pane(str(path), self.video_grid.panes[-1])
            if offset != 0.0:
                self.video_grid.set_offset(str(path), offset)

            # Store fps for frame-indexed source resolution (D-019)
            self._video_fps[str(path)] = vloader._fps

            # When the first video is loaded, auto-rebind any provisional frame-indexed sources
            if self._frame_indexed_sources and len(self._video_fps) == 1:
                self._rebind_frame_indexed_sources(vloader._fps)
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

        cache_mgr = CacheManager(loader_version=3)
        cache_dir = cache_mgr.get_cache_dir(Path(path))
        self.plot_pane.remove_channels(cache_dir)
        self.sidebar.remove_sensor(path)

    def _on_channel_remove_requested(self, path: str, channel: str) -> None:
        self.plot_pane.remove_channel(channel)

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
            fps, ok = self._resolve_tracking_fps()
            if not ok:
                return
            config = {"fps": fps}
            # No video loaded yet — track as provisional so we can re-bind on first video add
            if not self._video_fps:
                self._frame_indexed_sources.append((path, fps))
        else:
            # NeoLoader and other headless loaders that don't need UI config
            config = {}

        self._enqueue_import(path, loader_cls, config)

    def _resolve_tracking_fps(self) -> tuple[float, bool]:
        """Return (fps, ok) for a frame-indexed source, using loaded video fps when possible."""
        from PySide6.QtWidgets import QInputDialog

        n = len(self._video_fps)
        if n == 1:
            fps = next(iter(self._video_fps.values()))
            _, ok = QInputDialog.getDouble(
                self,
                "Confirm Frame Rate",
                "Frame rate for this tracking data (pre-filled from loaded video):",
                fps,
                1.0,
                1000.0,
                2,
            )
            return fps, ok
        if n > 1:
            items = list(self._video_fps.keys())
            picked, ok = QInputDialog.getItem(
                self,
                "Select Video for Frame Rate",
                "Use frame rate from which video?",
                items,
                0,
                False,
            )
            return (self._video_fps[picked], ok) if ok else (30.0, False)
        # No videos loaded — ask user for nominal fps
        fps, ok = QInputDialog.getDouble(
            self,
            "Tracking Data FPS",
            "Enter the video frame rate for this tracking data:",
            30.0,
            1.0,
            1000.0,
            2,
        )
        return fps, ok

    def _enqueue_import(self, path: Path, loader_cls: type, config: dict[str, Any]) -> None:
        """Start a background ImportWorker for the given path/loader/config."""
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QProgressDialog

        from kinochronix.engine.importer import ImportWorker

        self._import_thread = QThread()
        self._import_worker = ImportWorker(path, config, loader_cls)
        self._import_worker.moveToThread(self._import_thread)

        self._progress_dialog = QProgressDialog("Importing…", "Cancel", 0, 100, self)
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

    def _rebind_frame_indexed_sources(self, fps: float) -> None:
        """Re-import all provisional frame-indexed sources using the video fps."""
        from kinochronix.core.cache import CacheManager
        from kinochronix.loaders.tracking_loader import TrackingLoader

        for dlc_path, _ in self._frame_indexed_sources:
            cache_dir = CacheManager(loader_version=3).get_cache_dir(dlc_path)
            self.plot_pane.remove_channels(cache_dir)
            self.sidebar.remove_sensor(str(dlc_path))
            self._enqueue_import(dlc_path, TrackingLoader, {"fps": fps})
        self._frame_indexed_sources.clear()

    def _on_import_finished(
        self,
        path: str,
        cache_dir: str,
        channels: list[str],
        bounds: tuple[float, float],
        inspection: object = None,
    ) -> None:
        self._progress_dialog.close()
        self.plot_pane.load_channels(Path(cache_dir), channels)
        self._update_bounds(bounds[0], bounds[1])
        self.sidebar.add_sensor(path, channels)

        if isinstance(inspection, SourceInspection):
            self._inspections[path] = inspection
            self.sidebar.set_sensor_inspection(path, inspection)
            # Extract per-channel units from import config ("units" key → dict or mapping)
            units_cfg = inspection.import_config.get("units", {})
            if isinstance(units_cfg, dict):
                self._channel_units.update(units_cfg)
            # Overlay gap markers on each channel from this source
            rep = inspection.import_report
            if rep and rep.gap_locations:
                gap_times = list(rep.gap_locations)
                for ch in channels:
                    self.plot_pane.set_gap_markers(ch, gap_times)

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
