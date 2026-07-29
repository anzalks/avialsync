"""Main window for AvialView."""

import dataclasses
import logging
from collections import deque
from pathlib import Path
from typing import Any, cast

import numpy as np
from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QThread, QTimer, Signal, Slot
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

from avialview.core.inspection import SourceInspection
from avialview.core.session import (
    MarkerEntry,
    SensorEntry,
    SessionState,
    SyncProvenance,
    VideoEntry,
    add_recent,
    get_recent,
)
from avialview.core.source import TimeSeriesSource, VideoSource
from avialview.core.timeline import MasterClock, TimeMap
from avialview.engine.player import Player
from avialview.ui.annotations import AnnotationPanel, AnnotationStore
from avialview.ui.plot_pane import PlotPane
from avialview.ui.readout_panel import ReadoutPanel
from avialview.ui.time_format import TimeDisplayMode
from avialview.ui.tracking_3d_pane import Tracking3DPane
from avialview.ui.transport import Transport
from avialview.ui.video_grid import VideoGrid

logger = logging.getLogger(__name__)

_AUTOSAVE_INTERVAL_MS = 120_000  # 2 minutes


class MainWindow(QMainWindow):
    time_mode_changed = Signal(object)  # TimeDisplayMode

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AvialView")
        self.resize(1280, 800)

        self._session_path: Path | None = None

        # fps of each loaded video (str(path) → fps); used for frame-indexed source resolution
        self._video_fps: dict[str, float] = {}
        # Keep QObject workers alive until their QThread has finished. Moving an
        # object to a thread does not transfer Python ownership.
        self._video_load_jobs: dict[QThread, object] = {}
        self._video_load_offsets: dict[str, float] = {}
        self._video_load_drifts: dict[str, float] = {}
        self._pending_video_loads: deque[tuple[Path, float, float]] = deque()
        self._video_pane_initializing: object | None = None
        self._video_frame_times: dict[str, Any] = {}
        self._video_source_bounds: dict[str, tuple[float, float]] = {}
        self._video_time_mappings: dict[str, tuple[float, float]] = {}
        self._sync_provenance: list[SyncProvenance] = []
        self._pending_exact_mappings: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._overview_gaps: dict[float, str] = {}
        # DLC/frame-indexed sources loaded without a video present (path, provisional_fps)
        self._frame_indexed_sources: list[tuple[Path, float]] = []
        self._pending_imports: deque[tuple[Path, type, dict[str, Any]]] = deque()
        self._import_thread: QThread | None = None
        # Inspection data keyed by str(path)
        self._inspections: dict[str, SourceInspection] = {}
        # Units dict keyed by channel_id; populated from import config or wizard
        self._channel_units: dict[str, str] = {}
        self._time_mode = TimeDisplayMode.RELATIVE

        # Core
        self.clock = MasterClock()

        # UI Components
        self.video_grid = VideoGrid(self)
        self.tracking_3d_pane = Tracking3DPane(self)
        self.plot_pane = PlotPane(self)
        self.transport = Transport(self)
        self.data_streams = self.transport.detach_data_streams()
        self.transport.reset_zoom_requested.connect(self.plot_pane.reset_zoom)

        # Engine
        self.player = Player(
            self.clock,
            self.video_grid,
            self.plot_pane,
            self.transport,
            self,
            tracking_3d_pane=self.tracking_3d_pane,
        )

        # Annotations
        self.annotation_store = AnnotationStore(self)
        self.annotation_store.changed.connect(self._update_timeline_annotations)

        # Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QHBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        from avialview.ui.sidebar import SidebarPane

        self.sidebar = SidebarPane(self)
        self.sidebar.open_video_requested.connect(self._open_video)
        self.sidebar.open_sensor_requested.connect(self._open_data)
        self.sidebar.video_offset_changed.connect(self._on_video_offset_changed)
        self.sidebar.video_remove_requested.connect(self._on_video_remove_requested)
        self.sidebar.video_visibility_changed.connect(self.video_grid.set_pane_visible)
        self.sidebar.sensor_remove_requested.connect(self._on_sensor_remove_requested)
        self.sidebar.channel_remove_requested.connect(self._on_channel_remove_requested)
        self.sidebar.channel_visibility_changed.connect(self._on_channel_visibility_changed)
        self.plot_pane.channel_close_requested.connect(self._on_plot_channel_close_requested)
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

        self._media_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._media_splitter.setAccessibleName("Video and 3D tracking splitter")
        self._media_splitter.addWidget(self.video_grid)
        self._media_splitter.addWidget(self.tracking_3d_pane)
        self._media_splitter.setStretchFactor(0, 2)
        self._media_splitter.setStretchFactor(1, 1)

        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.addWidget(self._media_splitter)
        v_splitter.addWidget(self.plot_pane)
        v_splitter.setStretchFactor(0, 3)
        v_splitter.setStretchFactor(1, 1)
        self._v_splitter = v_splitter

        self._content_splitter = QSplitter(Qt.Orientation.Vertical)
        self._content_splitter.setAccessibleName("Video, plots, and Data Streams splitter")
        self._content_splitter.addWidget(v_splitter)
        self._content_splitter.addWidget(self.data_streams)
        self._content_splitter.setStretchFactor(0, 4)
        self._content_splitter.setStretchFactor(1, 1)
        right_layout.addWidget(self._content_splitter)
        right_layout.addWidget(self.transport)

        h_splitter.addWidget(right_widget)
        h_splitter.setStretchFactor(0, 0)
        h_splitter.setStretchFactor(1, 1)

        layout.addWidget(h_splitter)

        # Child widgets receive drag events before QMainWindow. Forward those
        # events to the single capability-routing implementation below.
        for drop_target in (
            central_widget,
            right_widget,
            self.video_grid,
            self.tracking_3d_pane,
            self.plot_pane,
        ):
            drop_target.setAcceptDrops(True)
            drop_target.installEventFilter(self)

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
        self.tracking_3d_pane.set_readers(readers)
        self.tracking_3d_pane.set_cursor(self.clock.state.t)

    def _update_timeline_annotations(self) -> None:
        """Mirror annotations to the overview without adding another time model."""
        self.transport.set_annotation_markers(
            [
                (marker.t_start, marker.t_end, marker.color)
                for marker in self.annotation_store.markers
            ]
        )

    # ── Inspection / properties dialogs ─────────────────────────────

    def _show_video_properties(self, path: str) -> None:
        """Show the VideoPropertiesPanel for a video (triggered by badge click)."""
        ins = self._inspections.get(path)
        if ins is None:
            return
        from avialview.ui.import_report import ImportReportDialog

        dlg = ImportReportDialog(ins, self)
        dlg.setWindowTitle(f"Video Properties — {Path(path).name}")
        dlg.exec()

    def _show_sensor_properties(self, path: str) -> None:
        """Show sensor properties for a data source."""
        ins = self._inspections.get(path)
        if ins is None:
            return
        from avialview.ui.import_report import ImportReportDialog

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
        from avialview.ui.import_report import ImportReportDialog

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
        self.transport.set_time(self.clock.state.t)
        self.time_mode_changed.emit(mode)

    # ── Diagnostics ──────────────────────────────────────────────────

    def _run_diagnostics(self) -> None:
        from avialview.ui.diagnostics import run_startup_diagnostics

        self._diag = run_startup_diagnostics(self)

    # ── Geometry persistence ─────────────────────────────────────────

    def _restore_geometry(self) -> None:
        settings = QSettings("AvialView", "AvialView")
        geom = settings.value("window/geometry")
        if geom:
            self.restoreGeometry(geom)
        h_state = settings.value("splitter/horizontal")
        if h_state:
            self._h_splitter.restoreState(h_state)
        v_state = settings.value("splitter/vertical")
        if v_state:
            self._v_splitter.restoreState(v_state)
        media_state = settings.value("splitter/media")
        if media_state:
            self._media_splitter.restoreState(media_state)
        content_state = settings.value("splitter/content")
        if content_state:
            self._content_splitter.restoreState(content_state)
        left_state = settings.value("splitter/left")
        if left_state:
            self._left_splitter.restoreState(left_state)

    def _save_geometry(self) -> None:
        settings = QSettings("AvialView", "AvialView")
        settings.setValue("window/geometry", self.saveGeometry())
        settings.setValue(
            "splitter/horizontal",
            self._h_splitter.saveState(),
        )
        settings.setValue(
            "splitter/vertical",
            self._v_splitter.saveState(),
        )
        settings.setValue("splitter/content", self._content_splitter.saveState())
        settings.setValue("splitter/media", self._media_splitter.saveState())
        settings.setValue("splitter/left", self._left_splitter.saveState())

    # ── Session save / load ──────────────────────────────────────────

    def _build_session_state(self) -> SessionState:
        """Snapshot current app state into a SessionState."""
        from avialview.ui.sidebar import SensorInfoWidget

        bounds = self.clock.state.bounds
        videos = []
        for p, pane in zip(self.video_grid._paths, self.video_grid.panes, strict=False):
            ins = self._inspections.get(p)
            videos.append(
                VideoEntry(
                    path=p,
                    offset=pane.time_map.offset,
                    drift_ppm=pane.time_map.drift_ppm,
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

        # The fixed sweep always displays 0..window_duration.
        plot_x0 = 0.0 if self.plot_pane.channels else None
        plot_x1 = self.plot_pane.window_duration if self.plot_pane.channels else None

        return SessionState(
            videos=videos,
            sensors=sensors,
            markers=markers,
            sync_provenance=list(self._sync_provenance),
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
            "AvialView Session (*.avv)",
        )
        if not path:
            return
        if not path.endswith(".avv"):
            path += ".avv"

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
            "AvialView Session (*.avv)",
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
            from avialview.ui.relink_dialog import RelinkDialog

            dlg = RelinkDialog(missing, kind_labels, self)
            if dlg.exec() == RelinkDialog.DialogCode.Rejected:
                return
            relink_map = dlg.resolved_mapping()

        self._sync_provenance = list(state.sync_provenance)
        self._pending_exact_mappings.clear()
        for provenance in state.sync_provenance:
            if provenance.exact_master and provenance.exact_source:
                target = relink_map.get(provenance.target_id, provenance.target_id)
                self._pending_exact_mappings[target] = (
                    np.asarray(provenance.exact_master, dtype=np.float64),
                    np.asarray(provenance.exact_source, dtype=np.float64),
                )

        for ve in state.videos:
            p = Path(relink_map.get(ve.path, ve.path))
            if p.exists():
                self._load_video(p, offset=ve.offset, drift_ppm=ve.drift_ppm)
                if ve.integrity_flags or ve.metadata:
                    from avialview.core.inspection import IntegrityFlags

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
                    from avialview.core.inspection import ImportReport

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
        from avialview.ui.annotations import VideoFrame

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

        # Restore the shared fixed-window duration even while sources load asynchronously.
        if state.plot_x0 is not None and state.plot_x1 is not None:
            self.plot_pane.set_window_duration(state.plot_x1 - state.plot_x0)

    def _autosave(self) -> None:
        """Silently autosave if a session path is set."""
        if self._session_path is None:
            return
        try:
            state = self._build_session_state()
            state.save(self._session_path)
        except Exception:
            logger.exception("Autosave failed for %s", self._session_path)

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
        from avialview.ui.annotations import VideoFrame

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
            a.setProperty("av_category", category)
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
        if self._video_load_jobs:
            event.ignore()
            return
        self.video_grid.shutdown()
        self._save_geometry()
        self._autosave()
        super().closeEvent(event)

    # ── Drag and Drop ────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Forward drops over child panes to the main-window source router."""
        if event.type() == QEvent.Type.DragEnter:
            self.dragEnterEvent(cast(QDragEnterEvent, event))
            return event.isAccepted()
        if event.type() == QEvent.Type.Drop:
            self.dropEvent(cast(QDropEvent, event))
            return event.isAccepted()
        return super().eventFilter(watched, event)

    def dropEvent(self, event: QDropEvent) -> None:
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        event.acceptProposedAction()

        candidates = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if not path.exists():
                continue
            candidates.extend(self._collect_drop_candidates(path))

        if not candidates:
            return

        if len(candidates) == 1:
            path, loader_cls = candidates[0]
            if loader_cls is not None:
                self._route_import_candidate(path, loader_cls)
                return

        # Defer dialogs to avoid blocking the macOS drag-and-drop OS loop (prevents beachball)
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, lambda: self._process_drop_candidates(candidates))

    def _route_import_candidate(
        self, path: Path, loader_cls: type[TimeSeriesSource | VideoSource]
    ) -> None:
        """Route one capability-resolved source through its normal loader path."""
        if issubclass(loader_cls, VideoSource):
            self._load_video(path)
        else:
            self._start_data_import(path, loader_cls)

    def _process_drop_candidates(self, candidates: list[tuple[Path, type | None]]) -> None:
        """Present the batch import dialog and route accepted items."""
        from PySide6.QtWidgets import QDialog

        from avialview.ui.batch_import_dialog import BatchImportDialog

        dialog = BatchImportDialog(candidates, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selections = dialog.get_selections()
            for path, loader_cls in selections:
                self._route_import_candidate(path, loader_cls)

    def _collect_drop_candidates(
        self, path: Path, registry: Any = None
    ) -> list[tuple[Path, type | None]]:
        """Collect paths and their best-guess loaders recursively, avoiding session files."""
        if path.suffix.lower() == ".avv":
            try:
                self._restore_session(SessionState.load(path))
            except (OSError, ValueError) as error:
                QMessageBox.critical(self, "Session Error", str(error))
            return []

        if registry is None:
            from avialview.core.registry import LoaderRegistry

            registry = LoaderRegistry()

        loader_class = registry.find_best_loader(path)

        if loader_class is not None:
            return [(path, loader_class)]

        candidates = []
        if path.is_dir():
            session_files = list(path.glob("*.avv"))
            if session_files:
                return self._collect_drop_candidates(session_files[0], registry=registry)
            for child in path.iterdir():
                if not child.name.startswith("."):
                    candidates.extend(self._collect_drop_candidates(child, registry=registry))
        else:
            candidates.append((path, None))

        return candidates

    # ── Menu ─────────────────────────────────────────────────────────

    def _setup_menu(self) -> None:
        from PySide6.QtGui import QActionGroup, QKeySequence

        # Collects every QAction with a shortcut — read by _show_shortcuts().
        self._all_actions: list[QAction] = []

        def _reg(act: QAction, category: str) -> QAction:
            """Tag an action with its shortcuts-dialog category."""
            act.setProperty("av_category", category)
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

        act = file_menu.addAction("Synchronize TTL / events…")
        act.triggered.connect(self._open_sync_wizard)

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

        font_menu = view_menu.addMenu("Font Size")
        self._font_size_group = QActionGroup(self)
        for label, key in [
            ("System", "system"),
            ("Small", "small"),
            ("Medium", "medium"),
            ("Large", "large"),
        ]:
            fa = font_menu.addAction(label)
            fa.setCheckable(True)
            fa.setData(key)
            self._font_size_group.addAction(fa)
        self._font_size_group.triggered.connect(self._on_font_size_selected)
        self._sync_font_size_menu()

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
        act = help_menu.addAction("About AvialView")
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

        from avialview.ui.theme import apply_theme

        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, action.data())

    def _sync_theme_menu(self) -> None:
        from avialview.ui.theme import current_preference

        pref = current_preference()
        for act in self._theme_group.actions():
            if act.data() == pref:
                act.setChecked(True)
                break

    def _cycle_theme(self) -> None:
        from PySide6.QtWidgets import QApplication

        from avialview.ui.theme import apply_theme, current_preference

        order = ["system", "dark", "light"]
        pref = current_preference()
        idx = order.index(pref) if pref in order else 0
        new_pref = order[(idx + 1) % len(order)]
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, new_pref)
        self._sync_theme_menu()

    def _on_font_size_selected(self, action: QAction) -> None:
        """Apply the selected system-relative application font scale."""
        from PySide6.QtWidgets import QApplication

        from avialview.ui.theme import apply_font_size

        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_font_size(app, action.data())

    def _sync_font_size_menu(self) -> None:
        from avialview.ui.theme import current_font_preference

        pref = current_font_preference()
        for act in self._font_size_group.actions():
            if act.data() == pref:
                act.setChecked(True)
                break

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
        from avialview.engine.export import snapshot_widget

        px = snapshot_widget(pane)
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Snapshot — {Path(path).name}",
            f"snapshot_{Path(path).stem}.png",
            "PNG Images (*.png)",
        )
        if not out_path:
            return
        from avialview.engine.export import save_snapshot

        try:
            save_snapshot(px, None, Path(out_path))
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _on_annotate_at_requested(self, t: float) -> None:
        """Add a point marker at the clicked time on the plot (D-022)."""
        from avialview.ui.annotations import VideoFrame

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
            "About AvialView",
            "AvialView — The Advanced Video and Instrument Alignment Library.\n"
            "Multi-camera video and time-series inspection.\nApache-2.0 licence.",
        )

    # ── Shortcuts dialog ─────────────────────────────────────────────

    def _show_shortcuts(self) -> None:
        from avialview.ui.shortcuts_dialog import ShortcutsDialog

        # Group all registered QActions by category tag (D-022.6)
        groups: dict[str, list[QAction]] = {}
        for act in getattr(self, "_all_actions", []):
            if not act.shortcuts():
                continue
            cat = str(act.property("av_category") or "Other")
            groups.setdefault(cat, []).append(act)

        dlg = ShortcutsDialog(groups, self)
        dlg.exec()

    # ── Diagnostics dialog ───────────────────────────────────────────

    def _show_diagnostics(self) -> None:
        from avialview.ui.diagnostics import format_diagnostics

        diag = getattr(self, "_diag", {})
        text = format_diagnostics(diag)

        msg = QMessageBox(self)
        msg.setWindowTitle("Diagnostics")
        msg.setText(text)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        msg.exec()

    # ── Snapshot export ──────────────────────────────────────────────

    def _export_snapshot(self) -> None:
        from avialview.engine.export import (
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

        video_px = snapshot_widget(self._media_splitter)
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

        from avialview.engine.export import (
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

        from avialview.engine.export import trim_video_clip

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

        from avialview.engine.proxy import ProxyWorker

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

    def _load_video(self, path: Path, offset: float = 0.0, drift_ppm: float = 0.0) -> None:
        """Queue a video source so native render panes are initialized one at a time."""
        self._pending_video_loads.append((path, offset, drift_ppm))
        self._start_next_video_load()

    def _start_next_video_load(self) -> None:
        """Start one asynchronous probe, preserving a bounded native-render lifecycle."""
        if (
            self._video_load_jobs
            or self._video_pane_initializing is not None
            or not self._pending_video_loads
        ):
            return

        from avialview.engine.video_worker import VideoOpenWorker

        path, offset, drift_ppm = self._pending_video_loads.popleft()
        thread = QThread(self)
        worker = VideoOpenWorker(path)
        self._video_load_jobs[thread] = worker
        self._video_load_offsets[str(path)] = offset
        self._video_load_drifts[str(path)] = drift_ppm
        remaining = len(self._pending_video_loads)
        suffix = f" ({remaining} queued)" if remaining else ""
        self.transport.set_status(f"Loading video: {path.name}{suffix}", "busy")
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # These QObject slots are queued onto MainWindow's UI thread.  Do not
        # replace them with lambdas: a lambda runs in the emitting worker thread
        # and would create widgets off-thread.
        worker.opened.connect(self._on_video_opened)
        worker.error.connect(self._on_video_open_error)
        worker.opened.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_video_thread_finished)
        thread.start()

    def _set_video_coverage(
        self,
        path: str,
        source_bounds: tuple[float, float],
        offset: float,
        drift_ppm: float,
        exact_master: np.ndarray | None = None,
        exact_source: np.ndarray | None = None,
    ) -> None:
        """Project media bounds through its TimeMap before drawing master-time coverage."""
        if exact_master is not None and exact_source is not None and len(exact_master) >= 2:
            master_bounds = (float(exact_master[0]), float(exact_master[-1]))
        else:
            mapping = TimeMap(offset, drift_ppm)
            master_bounds = (
                mapping.to_master(source_bounds[0]),
                mapping.to_master(source_bounds[1]),
            )
        self._video_source_bounds[path] = source_bounds
        self._video_time_mappings[path] = (offset, drift_ppm)
        self._update_bounds(*master_bounds)
        self.transport.set_source_coverage(path, *master_bounds, "video")

    @Slot(str, object, str)
    def _on_video_opened(self, original_path: str, loader: object, media_path: str) -> None:
        """Create UI state only after asynchronous source opening succeeds."""
        offset = self._video_load_offsets.pop(original_path, 0.0)
        drift_ppm = self._video_load_drifts.pop(original_path, 0.0)
        exact_mapping = self._pending_exact_mappings.pop(original_path, None)
        exact_master = exact_mapping[0] if exact_mapping is not None else None
        exact_source = exact_mapping[1] if exact_mapping is not None else None
        if not isinstance(loader, VideoSource):
            self._on_video_open_error(original_path, "Selected loader is not a VideoSource.")
            return
        bounds = loader.time_bounds()
        self._set_video_coverage(
            original_path,
            bounds,
            offset,
            drift_ppm,
            exact_master,
            exact_source,
        )
        self._video_pane_initializing = original_path
        pane = self.video_grid.add_pane(
            original_path,
            media_path=media_path,
            on_file_loaded=self._on_video_pane_ready,
        )
        video_metadata = loader.video_metadata()
        metadata = {
            "codec": video_metadata.codec,
            "fps": video_metadata.nominal_fps,
            "measured_fps": video_metadata.measured_fps,
            "is_vfr": video_metadata.is_vfr,
            "duration": video_metadata.duration,
            "file_size_bytes": video_metadata.file_size_bytes,
        }
        self.sidebar.add_video(original_path, metadata)
        self.sidebar.set_video_loader(original_path, loader)
        self.sidebar.set_video_pane(original_path, pane)
        if offset or drift_ppm or exact_mapping is not None:
            self.video_grid.set_sync_mapping(
                original_path,
                offset,
                drift_ppm,
                exact_master,
                exact_source,
            )
        self._video_fps[original_path] = loader.fps()
        frame_times = loader.frame_times()
        pane.set_frame_times(frame_times)
        pane.set_video_metadata(video_metadata)
        pane.set_source_bounds(bounds)
        is_vfr = video_metadata.is_vfr
        pane.set_vfr(is_vfr)
        # The pane is added asynchronously, after the current master-time seek
        # may already have run. Synchronize it now so paused media decodes its
        # first visible frame and availability reflects the active timeline.
        self.player.seek(self.clock.state.t, exact=True)
        from avialview.core.inspection import IntegrityFlags

        inspection = SourceInspection(
            path=original_path,
            loader_id=type(loader).__name__,
            integrity_flags=IntegrityFlags(is_vfr=is_vfr, drift_nonzero=bool(drift_ppm)),
        )
        self._inspections[original_path] = inspection
        self.sidebar.set_video_inspection(original_path, inspection)
        if frame_times is not None:
            self._video_frame_times[original_path] = frame_times
        if self._frame_indexed_sources and len(self._video_fps) == 1:
            self._rebind_frame_indexed_sources(loader.fps())
        self.transport.set_status(f"Ready · loaded {Path(original_path).name}")

    @Slot(str, str)
    def _on_video_open_error(self, path: str, error: str) -> None:
        """Show a source-open error without leaving a partially-created pane."""
        self._video_load_offsets.pop(path, None)
        self._video_load_drifts.pop(path, None)
        self.transport.set_status(f"Video failed: {Path(path).name}", "error")
        QMessageBox.critical(self, "Video Error", f"Could not open video:\n{path}\n\n{error}")

    @Slot()
    def _on_video_thread_finished(self) -> None:
        """Release the worker ownership after its thread has stopped on the UI thread."""
        thread = self.sender()
        if isinstance(thread, QThread):
            self._video_load_jobs.pop(thread, None)
            thread.deleteLater()
            QTimer.singleShot(0, self._start_next_video_load)

    @Slot()
    def _on_video_pane_ready(self) -> None:
        """Advance the queue only after the native pane accepts media commands."""
        self._video_pane_initializing = None
        self._start_next_video_load()

    def _on_video_offset_changed(self, path: str, offset: float) -> None:
        self.video_grid.set_offset(path, offset)
        if path in self._video_source_bounds:
            _, drift_ppm = self._video_time_mappings.get(path, (0.0, 0.0))
            self._set_video_coverage(path, self._video_source_bounds[path], offset, drift_ppm)
        self.clock.play()
        self.clock.pause()

    def _open_sync_wizard(self) -> None:
        """Open evidence-based TTL/frame-event alignment for loaded sources."""
        from avialview.engine.sync_worker import EventEvidenceSpec, SignalEvidenceSpec
        from avialview.ui.sync_wizard import SyncWizard

        references = [
            SignalEvidenceSpec(
                source_id=(
                    f"{channel.reader.cache_dir.name.removesuffix('.avialcache')} : "
                    f"{channel.reader.channel_id}"
                ),
                cache_dir=channel.reader.cache_dir,
                channel_id=channel.reader.channel_id,
            )
            for channel in self.plot_pane.channels
        ]
        targets = [
            EventEvidenceSpec(path, frame_times)
            for path, frame_times in self._video_frame_times.items()
            if len(frame_times) >= 3
        ]
        if not references or not targets:
            QMessageBox.information(
                self,
                "Synchronization evidence",
                "Load a TTL-bearing sensor channel and a video with frame timestamps first.",
            )
            return

        wizard = SyncWizard(references, targets, self)
        if wizard.exec() == wizard.DialogCode.Accepted and wizard.proposal is not None:
            self._accept_sync_proposal(wizard.target_id, wizard.proposal)

    def _accept_sync_proposal(self, target_path: str, proposal: object) -> None:
        """Apply an explicitly accepted proposal and retain reproducible provenance."""
        from avialview.core.sync import SyncProposal

        if not isinstance(proposal, SyncProposal) or not proposal.acceptable:
            raise ValueError("Only an acceptable synchronization proposal can be applied.")
        if target_path not in self.video_grid.pane_paths():
            raise ValueError(f"Synchronization target is not a loaded video: {target_path}")

        fit = proposal.fit

        exact_master = getattr(fit, "exact_master", None)
        exact_source = getattr(fit, "exact_source", None)

        self.video_grid.set_sync_mapping(
            target_path, fit.offset, fit.drift_ppm, exact_master, exact_source
        )
        if target_path in self._video_source_bounds:
            self._set_video_coverage(
                target_path,
                self._video_source_bounds[target_path],
                fit.offset,
                fit.drift_ppm,
                exact_master,
                exact_source,
            )
        provenance = SyncProvenance(
            reference_id=proposal.reference_id,
            target_id=target_path,
            offset=fit.offset,
            drift_ppm=fit.drift_ppm,
            rms_residual=fit.rms_residual,
            max_residual=fit.max_residual,
            matched_count=fit.matched_count,
            rejected_count=fit.rejected_count,
            tolerance=proposal.tolerance,
            matches=[
                {
                    "reference_time": match.reference_time,
                    "target_time": match.target_time,
                    "residual": match.residual,
                }
                for match in proposal.matches[:500]
            ],
            exact_master=(
                [float(value) for value in exact_master] if exact_master is not None else []
            ),
            exact_source=(
                [float(value) for value in exact_source] if exact_source is not None else []
            ),
        )
        self._sync_provenance = [
            item for item in self._sync_provenance if item.target_id != target_path
        ]
        self._sync_provenance.append(provenance)
        self.transport.set_status(
            f"TTL aligned · {fit.max_residual * 1000:.3f} ms residual", "info"
        )
        self.transport.set_ttl_events(
            [
                (
                    match.reference_time,
                    f"Target: {Path(target_path).name} · residual: {match.residual * 1000:.3f} ms",
                )
                for match in proposal.matches
            ]
        )

        # Merge missing video frames into the global overview gaps dictionary
        self._overview_gaps.update(
            {time: "Missing video frame" for time in getattr(proposal, "unmatched_references", ())}
        )
        self.transport.set_gap_events(sorted(self._overview_gaps.items()))
        self.player.seek(self.clock.state.t, exact=True)

        self.statusBar().showMessage(
            f"Accepted TTL/event alignment for {Path(target_path).name}: "
            f"{fit.max_residual * 1000:.3f} ms maximum residual.",
            5000,
        )

    def _on_video_remove_requested(self, path: str) -> None:
        self.video_grid.remove_pane(path)
        self.sidebar.remove_video(path)
        self._video_frame_times.pop(path, None)
        self._sync_provenance = [
            entry for entry in self._sync_provenance if entry.target_id != path
        ]

    def _on_sensor_remove_requested(self, path: str) -> None:
        from avialview.core.cache import CacheManager

        cache_mgr = CacheManager(loader_version=3)
        cache_dir = cache_mgr.get_cache_dir(Path(path))
        self.plot_pane.remove_channels(cache_dir)
        self.sidebar.remove_sensor(path)

    def _on_channel_remove_requested(self, path: str, channel: str) -> None:
        self.plot_pane.remove_channel(channel)

    def _on_channel_visibility_changed(self, path: str, channel: str, is_visible: bool) -> None:
        self.plot_pane.set_channel_visible(channel, is_visible)

    def _on_plot_channel_close_requested(self, channel: str) -> None:
        """Route a plot-row close through the existing sidebar visibility checkbox."""
        self.sidebar.set_channel_visible(channel, False)

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

    def _start_data_import(
        self, path: Path, loader_cls: type[TimeSeriesSource] | None = None
    ) -> None:
        """Start a registry-selected time-series import for one path."""
        from avialview.core.registry import LoaderRegistry

        if loader_cls is None:
            discovered_loader = LoaderRegistry().find_best_loader(path)
            if discovered_loader is None:
                QMessageBox.warning(
                    self, "Unsupported File", "No suitable loader found for this file."
                )
                return
            if not issubclass(discovered_loader, TimeSeriesSource):
                QMessageBox.warning(
                    self, "Unsupported File", "The selected loader is not time-series data."
                )
                return
            loader_cls = discovered_loader
        if loader_cls is None:
            QMessageBox.warning(self, "Unsupported File", "No suitable loader found for this file.")
            return

        from avialview.loaders.csv_loader import CSVLoader
        from avialview.loaders.tracking_loader import TrackingLoader

        if loader_cls is CSVLoader:
            from avialview.ui.import_wizard import ImportWizard

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
        """Queue a source import so only one worker owns the import UI at a time."""
        if self._import_thread is not None:
            self._pending_imports.append((path, loader_cls, config))
            return
        self._start_import(path, loader_cls, config)

    def _start_import(self, path: Path, loader_cls: type, config: dict[str, Any]) -> None:
        """Start the next queued background import."""
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QProgressDialog

        from avialview.engine.importer import ImportWorker

        self._import_thread = QThread()
        self.transport.set_status(f"Importing data: {path.name}", "busy")
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
        self._import_thread.finished.connect(self._on_import_thread_finished)

        self._import_worker.error.connect(self._on_import_error)
        self._import_worker.error.connect(self._import_thread.quit)

        self._progress_dialog.show()
        self._import_thread.start()

    @Slot()
    def _on_import_thread_finished(self) -> None:
        """Release the completed import and begin the next queued source."""
        self._import_thread = None
        if not self._pending_imports:
            return
        path, loader_cls, config = self._pending_imports.popleft()
        QTimer.singleShot(0, lambda: self._start_import(path, loader_cls, config))

    def _rebind_frame_indexed_sources(self, fps: float) -> None:
        """Re-import all provisional frame-indexed sources using the video fps."""
        from avialview.core.cache import CacheManager
        from avialview.loaders.tracking_loader import TrackingLoader

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
        progress_dialog = getattr(self, "_progress_dialog", None)
        if progress_dialog is not None:
            progress_dialog.close()
        self.plot_pane.load_channels(Path(cache_dir), channels)
        self._update_bounds(bounds[0], bounds[1])
        self.transport.set_source_coverage(path, bounds[0], bounds[1], "data")
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
                self._overview_gaps.update(
                    {time: f"Source: {Path(path).name}" for time in gap_times}
                )
                self.transport.set_gap_events(sorted(self._overview_gaps.items()))
                for ch in channels:
                    self.plot_pane.set_gap_markers(ch, gap_times)
        self.transport.set_status(f"Ready · imported {Path(path).name}")

    def _on_import_error(self, err_msg: str) -> None:
        progress_dialog = getattr(self, "_progress_dialog", None)
        if progress_dialog is not None:
            progress_dialog.close()
        self.transport.set_status("Data import failed", "error")
        QMessageBox.critical(
            self,
            "Import Error",
            f"Failed to import CSV:\n{err_msg}",
        )

    def _update_bounds(self, t0: float, t1: float) -> None:
        if self.clock.state.bounds == (0.0, 0.0):
            new_bounds = (t0, t1)
        else:
            curr_t0, curr_t1 = self.clock.state.bounds
            new_bounds = (
                min(curr_t0, t0),
                max(curr_t1, t1),
            )

        self.clock.set_bounds(*new_bounds)
        self.plot_pane.set_timeline_bounds(*new_bounds)
        self.transport.set_bounds(*new_bounds)
        self.transport.set_time(new_bounds[0])
