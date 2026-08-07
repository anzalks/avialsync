"""Main window for AvialSync."""

import logging
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np
from PySide6.QtCore import QEvent, QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QKeyEvent,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.channel_reader import ChannelKey
from avialsync.core.inspection import SourceInspection
from avialsync.core.session import (
    SessionState,
    SyncProvenance,
)
from avialsync.core.source import TimeSeriesSource, VideoSource
from avialsync.core.timeline import MasterClock
from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.player import Player
from avialsync.ui.annotations import AnnotationPanel, AnnotationStore
from avialsync.ui.controllers import (
    drop_controller,
    export_controller,
    import_controller,
    session_controller,
    video_controller,
)
from avialsync.ui.job_manager import JobManager
from avialsync.ui.pane_proportions import PaneProportions
from avialsync.ui.plot_pane import PlotPane
from avialsync.ui.readout_panel import ReadoutPanel
from avialsync.ui.time_format import TimeDisplayMode
from avialsync.ui.tracking_3d_pane import Tracking3DPane
from avialsync.ui.transport import Transport
from avialsync.ui.ui_heartbeat import UiHeartbeat
from avialsync.ui.video_grid import VideoGrid

logger = logging.getLogger(__name__)

_AUTOSAVE_INTERVAL_MS = 120_000  # 2 minutes

#: How long to let window-resize events pile up before rescaling the panes.
#: A drag-resize delivers one event per pixel of mouse travel; at this interval
#: the panes still follow the edge continuously (~60 Hz) while the relayout runs
#: once per frame instead of once per pixel.
_PANE_RESIZE_COALESCE_MS = 16

#: Keys that drive the playhead and must reach it from anywhere in the window.
#: Qt offers each of these to the focused widget first, and text editors accept
#: them, which is how one click into a spin box used to disable playback control
#: (D-059).
_PLAYHEAD_KEYS = frozenset(
    {
        Qt.Key.Key_Space,
        Qt.Key.Key_Left,
        Qt.Key.Key_Right,
        Qt.Key.Key_Home,
        Qt.Key.Key_End,
        Qt.Key.Key_Comma,
        Qt.Key.Key_Period,
    }
)


def _is_mid_edit(widget: QWidget) -> bool:
    """Return whether *widget* is a text editor with an edit in progress.

    Only such a widget keeps the caret keys; an editor merely holding focus has
    no claim on them.
    """
    if isinstance(widget, QLineEdit):
        return bool(widget.isModified())
    if isinstance(widget, QAbstractSpinBox):
        line_edit = widget.lineEdit()
        return bool(line_edit is not None and line_edit.isModified())
    return False


#: Re-exported from the import controller, which owns the probe loop that
#: enforces it.  Kept here because this is the name the bound is known by.
_MAX_VIDEO_PROBES = video_controller.MAX_VIDEO_PROBES


def _quit_legacy_jobs(registry: "dict[QThread, object]") -> None:
    """Ask the pre-JobManager registries to stop, without blocking on them.

    These export/snapshot/clip jobs still keep their own dicts. Shutdown must not
    wait on any of them: the window closing is more important than a job
    finishing, and their outputs are written atomically.
    """
    for thread in list(registry):
        worker = registry.get(thread)
        cancel = getattr(worker, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except RuntimeError:
                pass
        thread.quit()
    registry.clear()


class _JobWorker(Protocol):
    """A QObject with a run() slot, moved to a QThread by _run_job."""

    def run(self) -> None: ...
    def moveToThread(self, thread: QThread, /) -> bool: ...


class MainWindow(QMainWindow):
    time_mode_changed = Signal(object)  # TimeDisplayMode

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AvialSync")
        self.resize(1280, 800)

        self._session_path: Path | None = None

        # fps of each loaded video (str(path) → fps); used for frame-indexed source resolution
        self._video_fps: dict[str, float] = {}
        # Settings the last session plugin reported for a dropped folder, if
        # any. Format-neutral: any SessionSource may declare them. Declared here
        # rather than created on first use, because they are read outside the
        # code that sets them and a window that never opened a session must
        # still answer for them.
        self._session_camera_fps: float = 0.0
        self._session_anchor_epoch: float = 0.0
        #: Per-item display labels the claiming session supplied, by path.
        self._session_item_labels: dict[str, str] = {}
        # Keep QObject workers alive until their QThread has finished. Moving an
        # object to a thread does not transfer Python ownership.
        self._video_load_jobs: dict[QThread, object] = {}
        self._video_load_offsets: dict[str, float] = {}
        self._video_load_drifts: dict[str, float] = {}
        self._pending_video_loads: deque[tuple[Path, float, float, dict[str, Any] | None]] = deque()
        self._video_pane_initializing: object | None = None
        # Probes run concurrently and finish out of order; panes are built in
        # request order, one at a time.
        self._video_request_order: list[str] = []
        self._probed_videos: dict[str, tuple[object, str]] = {}
        self._video_frame_times: dict[str, Any] = {}
        self._video_source_bounds: dict[str, tuple[float, float]] = {}
        self._video_time_mappings: dict[str, tuple[float, float]] = {}
        self._sync_provenance: list[SyncProvenance] = []
        self._pending_exact_mappings: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._overview_gaps: dict[float, str] = {}
        # DLC/frame-indexed sources loaded without a video present (path, provisional_fps)
        self._frame_indexed_sources: list[tuple[Path, type, dict[str, Any]]] = []
        self._pending_imports: deque[tuple[Path, type, dict[str, Any]]] = deque()
        self._import_thread: QThread | None = None
        # Held until the import thread has finished so the worker is destroyed
        # on this thread; see the wiring in the import starter for why.
        self._import_worker: QObject | None = None
        # Modal progress for the running import. Declared here rather than
        # created by the import starter: the finish and error handlers both
        # read it, and a window that has never imported must still answer.
        self._progress_dialog: QProgressDialog | None = None
        self._data_export_jobs: dict[QThread, object] = {}
        self._region_stats_jobs: dict[QThread, object] = {}
        self._video_clip_jobs: dict[QThread, object] = {}
        self._snapshot_jobs: dict[QThread, object] = {}
        # Owns worker/thread pairs started through _run_job (drop scan, session
        # save/load). See _run_job for why this reference must be kept.
        self._jobs: dict[QThread, _JobWorker] = {}
        # Pose sources are shown on the video overlay and in the 3D view rather
        # than as plot rows (D-046). Keyed by video path -> source path -> track.
        self._overlay_sources: dict[str, dict[str, dict[str, Any]]] = {}
        self._pose_3d_sources: dict[str, list[Any]] = {}
        self._plotted_readers: list[Any] = []
        self._region_stats_request = 0
        # Inspection data keyed by str(path)
        self._inspections: dict[str, SourceInspection] = {}
        # Units dict keyed by channel_id; populated from import config or wizard
        self._channel_units: dict[ChannelKey, str] = {}
        # Sensor source path → its sidecar cache dir, so an offset edit can find
        # the plot rows it owns without walking every channel.
        self._sensor_cache_dirs: dict[str, Path] = {}
        # Sources whose plot rows are still being built; their exact reader-derived
        # bounds are applied when PlotPane reports the load complete (D-060).
        self._pending_bounds_sources: dict[str, Path] = {}
        # Accepted mappings restored from a session, applied once their
        # asynchronous import reports back.
        self._pending_sensor_mappings: dict[str, tuple[float, float]] = {}
        self._time_mode = TimeDisplayMode.RELATIVE
        self._save_in_progress = False

        # One owner for background work: names it for the status bar, watches it
        # for stalls, and abandons it at shutdown so the window always closes.
        self._job_manager = JobManager(self)
        self._job_manager.jobs_changed.connect(self._on_jobs_changed)
        # Off-thread work is only half the guarantee; this notices when the UI
        # thread blocks anyway and says so instead of just feeling laggy.
        self._heartbeat = UiHeartbeat(self)
        self._heartbeat.stalled.connect(self._on_ui_stalled)
        self._heartbeat.start()

        # Core
        self.clock = MasterClock()

        # UI Components
        self.video_grid = VideoGrid(self)
        self.tracking_3d_pane = Tracking3DPane(self)
        self.plot_pane = PlotPane(self)
        self.transport = Transport(self)
        self.data_streams = self.transport.detach_data_streams()
        self.transport.reset_zoom_requested.connect(self.plot_pane.reset_zoom)
        self.plot_pane.view_window_changed.connect(self.transport.set_plot_viewport)

        # Engine
        from avialsync.core.registry import LoaderRegistry

        self._registry = LoaderRegistry()

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

        from avialsync.ui.sidebar import SidebarPane

        self.sidebar = SidebarPane(self)
        self.sidebar.open_video_requested.connect(self._open_video)
        self.sidebar.open_sensor_requested.connect(self._open_data)
        self.sidebar.video_offset_changed.connect(self._on_video_offset_changed)
        self.sidebar.video_remove_requested.connect(self._on_video_remove_requested)
        # Persist before a removed pane's media client is torn down: that
        # teardown can fault on Windows, and mid-session it would otherwise
        # cost everything since the last autosave.
        self.video_grid.pane_detached.connect(self._write_session_snapshot)
        self.sidebar.video_visibility_changed.connect(self.video_grid.set_pane_visible)
        self.sidebar.sensor_remove_requested.connect(self._on_sensor_remove_requested)
        self.sidebar.sensor_mapping_changed.connect(self._on_sensor_mapping_changed)
        self.sidebar.channel_remove_requested.connect(self._on_channel_remove_requested)
        self.sidebar.channel_visibility_changed.connect(self._on_channel_visibility_changed)
        self.plot_pane.channel_close_requested.connect(self._on_plot_channel_close_requested)
        self.sidebar.grid_mode_changed.connect(self.video_grid.set_grid_mode)
        self.sidebar.video_badge_clicked.connect(self._show_video_properties)
        self.sidebar.sensor_badge_clicked.connect(self._show_sensor_properties)
        self.sidebar.sensor_report_requested.connect(self._show_import_report)

        # Readout panel
        self.readout_panel = ReadoutPanel(self)
        self.plot_pane.channels_loaded.connect(self._refine_source_bounds)
        self.plot_pane.rows_pending.connect(self._on_rows_pending)
        self.plot_pane.sources_changed.connect(self._on_sources_changed)
        self.plot_pane.sources_changed.connect(self.video_grid.set_tracking_readers)
        self.plot_pane.measure_changed.connect(self._on_measure_changed)
        self.player._readout_panel = self.readout_panel

        # Annotation panel
        self.annotation_panel = AnnotationPanel(self.annotation_store, self)
        self.plot_pane.set_annotation_store(self.annotation_store)

        # One compact inspector keeps source management, values, and annotations available
        # without permanently consuming three stacked panes of workspace height.
        self._left_tabs = QTabWidget(self)
        self._left_tabs.setAccessibleName("Inspector")
        self._left_tabs.addTab(self.sidebar, "Sources")
        self._left_tabs.addTab(self.readout_panel, "Values")
        self._left_tabs.addTab(self.annotation_panel, "Annotations")

        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        h_splitter.addWidget(self._left_tabs)
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
        # The 3D pane only earns workspace once a source actually has XYZ
        # triplets; otherwise an empty pane holds width the video needs.
        self.tracking_3d_pane.setVisible(False)

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

        # Stretch factors alone let Qt hand a pane zero pixels when the sibling's
        # size hint already fills the splitter — that is how the plot area came up
        # fully collapsed.  Seed explicit proportions and forbid a drag from
        # collapsing a pane to nothing: a zero-height plot area or zero-width
        # video area has no handle affordance left to bring it back.
        # Resizing the window must rescale the panes, not hand the whole change
        # to whichever pane happens not to be sitting on its minimum. The
        # inspector column is deliberately left out: a source list that widens
        # with the monitor wastes the width the media panes want.
        self._pane_proportions = PaneProportions(self)
        self._pane_proportions.track(
            self._content_splitter,
            self._v_splitter,
            self._media_splitter,
        )
        self._pane_resize_timer = QTimer(self)
        self._pane_resize_timer.setSingleShot(True)
        self._pane_resize_timer.setInterval(_PANE_RESIZE_COALESCE_MS)
        self._pane_resize_timer.timeout.connect(self._pane_proportions.reapply)

        self._enforce_splitter_policy()
        self._apply_default_splitter_sizes()

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

        # Qt delivers ShortcutOverride to whichever widget has focus, not to the
        # window, so reserving the playhead keys needs an application-wide
        # filter. `_reserve_playhead_key` scopes every decision back to this
        # window, so dialogs keep their own editing keys (D-059).
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.installEventFilter(self)

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

    # ── Background job lifetime ──────────────────────────────────────

    def _run_job(
        self,
        worker: _JobWorker,
        label: str = "Working",
        configure: Callable[[QThread], None] | None = None,
    ) -> QThread:
        """Own a worker/thread pair for the whole life of a background job.

        Delegates to :class:`JobManager`, which additionally names the job for
        the status bar, watches it for stalls, and can abandon it at shutdown so
        the window always closes.

        Connect result signals in *configure*, never after this returns: the
        thread is already running by then, and a worker that finishes first
        emits into nothing (D-062, and the no-op drops this file's tests pin).
        """
        return self._job_manager.start(label, worker, configure=configure)

    def _on_jobs_changed(self) -> None:
        """Mirror background-job state into the transport status area."""
        text = self._job_manager.status_text()
        if not text:
            self.transport.set_status("Ready")
            return
        kind = "error" if self._job_manager.stalled_jobs() else "busy"
        self.transport.set_status(text, kind)

    def _on_ui_stalled(self, milliseconds: float) -> None:
        """Tell the user when the UI thread itself was blocked."""
        self.transport.set_status(f"Interface stalled for {milliseconds / 1000:.1f} s", "error")

    # ── Sources / units ──────────────────────────────────────────────

    def _splitters(self) -> tuple[QSplitter, ...]:
        return (
            self._h_splitter,
            self._content_splitter,
            self._v_splitter,
            self._media_splitter,
        )

    def _enforce_splitter_policy(self) -> None:
        """Forbid collapsing a pane to nothing.

        Must be re-applied after ``restoreState``: ``QSplitter.saveState`` stores
        the collapsible flag, so a session arranged before this policy existed
        would otherwise restore the old permissive behaviour.
        """
        for splitter in self._splitters():
            splitter.setChildrenCollapsible(False)

    def _repair_collapsed_panes(self) -> None:
        """Re-seed any splitter a previously-saved state left with a zero pane.

        A zero-height plot area or zero-width video area has no handle affordance
        left to drag it back, so a stale saved layout must not be honoured.
        """
        for splitter in self._splitters():
            sizes = splitter.sizes()
            visible = [
                index
                for index in range(splitter.count())
                if (child := splitter.widget(index)) is not None and child.isVisible()
            ]
            if any(sizes[index] <= 0 for index in visible):
                self._apply_default_splitter_sizes()
                return

    def _apply_default_splitter_sizes(self) -> None:
        """Seed the first-run pane layout, as sizes now and as shares thereafter.

        Called before any saved state is restored; ``_restore_geometry`` still
        wins when the user has arranged the window before.

        These pixel counts have only ever described a *ratio*: the first window
        resize redistributes them by stretch factor and minimum size, so what a
        new profile actually got was decided by whichever pane had the largest
        minimum — for the vertical split, an empty drop-target placeholder.
        Handing the same ratios to the proportion store is what makes the
        intent below the thing the user sees.
        """
        defaults = (
            (self._h_splitter, (280, 1000)),
            (self._content_splitter, (620, 160)),
            (self._v_splitter, (380, 240)),
            (self._media_splitter, (700, 300)),
        )
        for splitter, sizes in defaults:
            splitter.setSizes(list(sizes))
        # The inspector column is skipped: it is not proportion-managed, because
        # a source list that widens with the monitor only steals media width.
        for splitter, sizes in defaults[1:]:
            self._pane_proportions.set_fractions(splitter, sizes)

    def _refine_source_bounds(self) -> None:
        """Apply exact reader-derived bounds once every queued row exists.

        Rows are built across several event-loop turns so a large selection does
        not freeze the window (D-060). Until they exist, `_on_import_finished`
        uses the import worker's bounds; this replaces them with the mapped span
        the readers actually cover, which differs whenever a source carries an
        offset or drift.
        """
        for path, cache_dir in list(self._pending_bounds_sources.items()):
            span = self.plot_pane.source_bounds(cache_dir)
            if span is None:
                continue
            self._pending_bounds_sources.pop(path, None)
            self._update_bounds(span[0], span[1])
            self.transport.set_source_coverage(path, span[0], span[1], "data")

    def _on_rows_pending(self, remaining: int) -> None:
        """Say that rows are still appearing, so a partial plot is not read as all of it."""
        if remaining:
            self.transport.set_status(f"Building plot rows… {remaining} left")

    def _on_sources_changed(self, readers: list[Any]) -> None:
        """Forward to ReadoutPanel with accumulated units for known channels."""
        self.readout_panel.update_sources(readers, self._channel_units)
        # Plotted XYZ channels still feed the 3D view, but they are no longer its
        # only feed: pose sources register themselves without being plotted.
        self._plotted_readers = list(readers)
        self._refresh_pose_3d()

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
        from avialsync.ui.import_report import ImportReportDialog

        dlg = ImportReportDialog(ins, self)
        dlg.setWindowTitle(f"Video Properties — {Path(path).name}")
        dlg.exec()

    def _show_sensor_properties(self, path: str) -> None:
        """Show sensor properties for a data source."""
        ins = self._inspections.get(path)
        if ins is None:
            return
        from avialsync.ui.import_report import ImportReportDialog

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
        from avialsync.ui.import_report import ImportReportDialog

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
        self.plot_pane.set_time_mode(mode)
        self.transport.set_time(self.clock.state.t)
        self.time_mode_changed.emit(mode)

    # ── Diagnostics ──────────────────────────────────────────────────

    def _run_diagnostics(self) -> None:
        from avialsync.ui.diagnostics import run_startup_diagnostics

        self._diag = run_startup_diagnostics(self)

    # ── Geometry persistence ─────────────────────────────────────────

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Rescale the panes with the window instead of letting one absorb it all.

        Coalesced: a drag-resize delivers an event per pixel of travel, and
        every reallocation costs a full workspace relayout (mpv surfaces, the
        pyqtgraph stack, the overview strip). Running one per frame keeps the
        panes visibly tracking the window edge without putting a relayout storm
        on the UI thread.
        """
        super().resizeEvent(event)
        self._pane_resize_timer.start()

    def _restore_geometry(self) -> None:
        session_controller.restore_geometry(self)

    def _save_geometry(self) -> None:
        session_controller.save_geometry(self)

    # ── Session save / load ────────────────────────────

    def _build_session_state(self) -> SessionState:
        return session_controller.build_session_state(self)

    def _save_session(self) -> None:
        session_controller.save_session(self)

    def _start_session_save(self, path: Path, is_autosave: bool = False) -> None:
        session_controller.start_session_save(self, path, is_autosave)

    def _open_session(self) -> None:
        session_controller.open_session(self)

    def _start_session_load(self, path: Path) -> None:
        session_controller.start_session_load(self, path)

    def _on_session_load_error(self, error: str) -> None:
        session_controller.on_session_load_error(self, error)

    def _restore_session(self, state: SessionState) -> None:
        session_controller.restore_session(self, state)

    def _autosave(self) -> None:
        session_controller.autosave(self)

    def _autosave_before_close(self) -> None:
        session_controller.autosave_before_close(self)

    def _write_session_snapshot(self, _path: str = "") -> None:
        session_controller.write_session_snapshot(self)

    # ── A/B loop stats ───────────────────────────────────────────────

    def _on_ab_loop_changed(self, t_in: float | None, t_out: float | None) -> None:
        if t_in is not None and t_out is not None:
            lo, hi = min(t_in, t_out), max(t_in, t_out)
            self._start_region_stats(lo, hi)
        else:
            self._region_stats_request += 1
            self.readout_panel.clear_region_stats()

    def _reader_references(self) -> list[ReaderReference]:
        return export_controller.reader_references(self)

    def _start_region_stats(self, t0: float, t1: float) -> None:
        export_controller.start_region_stats(self, t0, t1)

    @Slot(int, object)
    def _on_region_stats_finished(self, request_id: int, stats: object) -> None:
        export_controller.on_region_stats_finished(self, request_id, stats)

    @Slot(int, str)
    def _on_region_stats_error(self, request_id: int, error: str) -> None:
        export_controller.on_region_stats_error(self, request_id, error)

    @Slot()
    def _on_region_stats_thread_finished(self) -> None:
        export_controller.on_region_stats_thread_finished(self)

    # ── Annotations ──────────────────────────────────────────────────

    def _on_annotate_requested(self) -> None:
        """Record master time and per-video frame snapshot for all active videos."""
        from avialsync.ui.annotations import VideoFrame

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
        export_controller.export_annotations(self)

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
        """Always close.

        This used to ``event.ignore()`` while any background job was running, so
        a wedged ffprobe on a network share left the user in an application they
        could not quit. Jobs are asked to cancel and given a bounded moment;
        whatever has not stopped is abandoned and named in the log. Cache
        commits are atomic, so an abandoned job leaves the previous valid
        sidecar rather than a half-written one.
        """

        def _quit_all_legacy_jobs() -> None:
            for registry in (
                self._video_load_jobs,
                self._data_export_jobs,
                self._region_stats_jobs,
                self._video_clip_jobs,
                self._snapshot_jobs,
            ):
                _quit_legacy_jobs(registry)

        # Ordering matters twice over.
        #
        # State is captured before anything is torn down: `_build_session_state`
        # reads `video_grid.panes`, and `video_grid.shutdown()` clears them, so
        # running the autosave afterwards wrote a session with zero videos and
        # silently discarded the user's video list on every close (D-059).
        #
        # libmpv teardown goes last, and every step is isolated. Each pane owns
        # an event thread that outlives its widget, so a step that raises must
        # not skip the ones after it: that leaves those threads running and the
        # process never exits, which is the "window won't close" the user sees.
        self._close_step("releasing the application event filter", self._remove_app_event_filter)
        self._close_step("cancelling queued plot rows", self.plot_pane.cancel_pending_rows)
        self._close_step("stopping the heartbeat", self._heartbeat.stop)
        self._close_step("stopping playback", self.player.stop)
        self._close_step("saving window geometry", self._save_geometry)
        self._close_step("writing the final autosave", self._autosave_before_close)
        self._close_step("stopping background jobs", self._job_manager.shutdown)
        self._close_step("stopping legacy jobs", _quit_all_legacy_jobs)
        self._close_step("shutting down video panes", self.video_grid.shutdown)
        super().closeEvent(event)

    def _remove_app_event_filter(self) -> None:
        """Detach from the application before this window is destroyed.

        A filter installed on the QApplication outlives the widget that
        installed it. Leaving a destroyed window in that chain means the next
        key event calls into a deleted C++ object, which aborts the process.
        """
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.removeEventFilter(self)

    @staticmethod
    def _close_step(description: str, step: Callable[[], object]) -> None:
        """Run one shutdown step; log and continue if it fails.

        Closing is the one path with no later chance to recover. A raised
        exception here used to abandon every remaining step.
        """
        try:
            step()
        except Exception:
            logger.exception("Ignoring a failure while %s during shutdown", description)

    # ── Drag and Drop ────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Forward drops over child panes, and keep the playhead keys reserved."""
        event_type = event.type()
        if event_type == QEvent.Type.ShortcutOverride and self._reserve_playhead_key(event):
            # Ignoring a ShortcutOverride is what lets the window QAction run.
            event.ignore()
            return True
        if event_type == QEvent.Type.DragEnter:
            self.dragEnterEvent(cast(QDragEnterEvent, event))
            return event.isAccepted()
        if event_type == QEvent.Type.Drop:
            self.dropEvent(cast(QDropEvent, event))
            return event.isAccepted()
        return super().eventFilter(watched, event)

    def _reserve_playhead_key(self, event: QEvent) -> bool:
        """Return whether this key belongs to the playhead rather than the focus widget.

        Qt offers every key to the focused widget as a ShortcutOverride before
        running a window shortcut. ``QLineEdit`` and ``QAbstractSpinBox`` accept
        that offer for Space, the arrows, Home and End, so one click into the
        transport's time field or the sweep-length spin box silently killed
        every playhead binding until focus moved elsewhere (D-059).

        Those keys are given back to the playhead, with one exception: a text
        editor the user is part-way through typing into keeps its caret keys, so
        correcting a half-entered timecode still works. Space is never returned
        to the editor — neither a timecode nor a number contains one.
        """
        if not isinstance(event, QKeyEvent):
            return False
        key = event.key()
        if key not in _PLAYHEAD_KEYS:
            return False

        app = QApplication.instance()
        focus = app.focusWidget() if isinstance(app, QApplication) else None
        if focus is None:
            return False
        # Never reach into a dialog: its own editors own their keys, and the
        # window shortcuts are not active for it anyway.
        if focus.window() is not self:
            return False

        if key != Qt.Key.Key_Space and _is_mid_edit(focus):
            return False
        return True

    def dropEvent(self, event: QDropEvent) -> None:
        drop_controller.drop_event(self, event)

    def open_path(self, path: Path) -> None:
        """Open a session file or a folder of recordings.

        Routes through the same scan a drag-and-drop performs, so
        ``avialsync open <path>`` and dropping that path on the window cannot
        drift apart: the scanner already recognises ``.avv`` files, folders
        containing them, and loose recordings.
        """
        self._start_drop_scan([path])

    def _start_drop_scan(self, paths: list[Path]) -> None:
        drop_controller.start_drop_scan(self, paths)

    def _on_drop_session_found(self, path: str) -> None:
        drop_controller.on_drop_session_found(self, path)

    def _on_drop_scan_error(self, error_msg: str) -> None:
        drop_controller.on_drop_scan_error(self, error_msg)

    def _on_drop_scan_finished(
        self,
        candidates: list[tuple[Path, type | None, dict | None]],
        layout: object = None,
    ) -> None:
        drop_controller.on_drop_scan_finished(self, candidates, layout)

    def _route_import_candidate(
        self,
        path: Path,
        loader_cls: type[TimeSeriesSource | VideoSource],
        config: dict | None = None,
    ) -> None:
        drop_controller.route_import_candidate(self, path, loader_cls, config)

    def _process_drop_candidates(
        self, candidates: list[tuple[Path, type | None, dict | None]]
    ) -> None:
        drop_controller.process_drop_candidates(self, candidates)

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
        act = help_menu.addAction("About AvialSync")
        act.setMenuRole(QAction.MenuRole.AboutRole)
        act.triggered.connect(self._show_about)

    def _rebuild_recent_menu(self) -> None:
        session_controller.rebuild_recent_menu(self)

    def _open_recent(self, path: str) -> None:
        session_controller.open_recent(self, path)

    # ── Theme selection ─────────────────────────────────────────────

    def _on_theme_selected(self, action: QAction) -> None:
        from PySide6.QtWidgets import QApplication

        from avialsync.ui.theme import apply_theme

        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, action.data())

    def _sync_theme_menu(self) -> None:
        from avialsync.ui.theme import current_preference

        pref = current_preference()
        for act in self._theme_group.actions():
            if act.data() == pref:
                act.setChecked(True)
                break

    def _cycle_theme(self) -> None:
        from PySide6.QtWidgets import QApplication

        from avialsync.ui.theme import apply_theme, current_preference

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

        from avialsync.ui.theme import apply_font_size

        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_font_size(app, action.data())

    def _sync_font_size_menu(self) -> None:
        from avialsync.ui.theme import current_font_preference

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
        export_controller.export_snapshot_for_pane(self, path)

    def _on_annotate_at_requested(self, t: float) -> None:
        """Add a point marker at the clicked time on the plot (D-022)."""
        from avialsync.ui.annotations import VideoFrame

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
            "About AvialSync",
            "AvialSync — The Advanced Video and Instrument Alignment Library.\n"
            "Multi-camera video and time-series inspection.\n"
            "Free software under the GNU AGPL v3 or later.",
        )

    # ── Shortcuts dialog ─────────────────────────────────────────────

    def _show_shortcuts(self) -> None:
        from avialsync.ui.shortcuts_dialog import ShortcutsDialog

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
        from avialsync.ui.diagnostics import format_diagnostics

        diag = dict(getattr(self, "_diag", {}))
        # Read at display time, not at probe time: the registry finishes
        # discovery during window construction, after the startup probe starts.
        diag["plugin_errors"] = self._registry.plugin_errors
        text = format_diagnostics(diag)

        msg = QMessageBox(self)
        msg.setWindowTitle("Diagnostics")
        msg.setText(text)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        msg.exec()

    # ── Snapshot export ──────────────────────────────────────────────

    def _export_snapshot(self) -> None:
        export_controller.export_snapshot(self)

    def _start_snapshot_export(
        self, video_image: QImage | None, plot_image: QImage | None, path: Path
    ) -> None:
        export_controller.start_snapshot_export(self, video_image, plot_image, path)

    @Slot(str)
    def _on_snapshot_finished(self, path: str) -> None:
        export_controller.on_snapshot_finished(self, path)

    @Slot(str)
    def _on_snapshot_error(self, error: str) -> None:
        export_controller.on_snapshot_error(self, error)

    @Slot()
    def _on_snapshot_thread_finished(self) -> None:
        export_controller.on_snapshot_thread_finished(self)

    # ── Data slice export ────────────────────────────────

    def _export_data_slice(self) -> None:
        export_controller.export_data_slice(self)

    def _start_data_export(self, t0: float, t1: float, path: Path) -> None:
        export_controller.start_data_export(self, t0, t1, path)

    @Slot(str)
    def _on_data_export_finished(self, path: str) -> None:
        export_controller.on_data_export_finished(self, path)

    @Slot(str)
    def _on_data_export_error(self, error: str) -> None:
        export_controller.on_data_export_error(self, error)

    @Slot()
    def _on_data_export_thread_finished(self) -> None:
        export_controller.on_data_export_thread_finished(self)

    def _export_video_clip(self) -> None:
        export_controller.export_video_clip(self)

    def _start_video_clip_export(self, clips: list[tuple[str, float, float, Path]]) -> None:
        export_controller.start_video_clip_export(self, clips)

    @Slot(int, int)
    def _on_video_clip_finished(self, successful: int, total: int) -> None:
        export_controller.on_video_clip_finished(self, successful, total)

    @Slot(str)
    def _on_video_clip_error(self, error: str) -> None:
        export_controller.on_video_clip_error(self, error)

    @Slot()
    def _on_video_clip_thread_finished(self) -> None:
        export_controller.on_video_clip_thread_finished(self)

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

        from avialsync.engine.proxy import ProxyWorker

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

    def _load_video(
        self,
        path: Path,
        offset: float = 0.0,
        drift_ppm: float = 0.0,
        config: dict[str, Any] | None = None,
    ) -> None:
        video_controller.load_video(self, path, offset, drift_ppm, config)

    def _start_next_video_load(self) -> None:
        video_controller.start_next_video_load(self)

    def _start_one_video_probe(self) -> None:
        video_controller.start_one_video_probe(self)

    def _set_video_coverage(
        self,
        path: str,
        source_bounds: tuple[float, float],
        offset: float,
        drift_ppm: float,
        exact_master: np.ndarray | None = None,
        exact_source: np.ndarray | None = None,
    ) -> None:
        video_controller.set_video_coverage(
            self, path, source_bounds, offset, drift_ppm, exact_master, exact_source
        )

    @Slot(str, object, str)
    def _on_video_opened(self, original_path: str, loader: object, media_path: str) -> None:
        video_controller.on_video_opened(self, original_path, loader, media_path)

    def _build_next_video_pane(self) -> None:
        video_controller.build_next_video_pane(self)

    def _create_video_pane(self, original_path: str, loader: object, media_path: str) -> None:
        video_controller.create_video_pane(self, original_path, loader, media_path)

    @Slot(str, str)
    def _on_video_open_error(self, path: str, error: str) -> None:
        video_controller.on_video_open_error(self, path, error)

    @Slot()
    def _on_video_thread_finished(self) -> None:
        video_controller.on_video_thread_finished(self)

    @Slot()
    def _on_video_pane_ready(self) -> None:
        video_controller.on_video_pane_ready(self)

    def _on_video_offset_changed(self, path: str, offset: float) -> None:
        self.video_grid.set_offset(path, offset)
        if path in self._video_source_bounds:
            _, drift_ppm = self._video_time_mappings.get(path, (0.0, 0.0))
            self._set_video_coverage(path, self._video_source_bounds[path], offset, drift_ppm)
        self.clock.play()
        self.clock.pause()

    def _open_sync_wizard(self) -> None:
        """Open evidence-based TTL/frame-event alignment for loaded sources."""
        from avialsync.engine.sync_worker import EventEvidenceSpec, SignalEvidenceSpec
        from avialsync.ui.sync_wizard import SyncWizard

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
        from avialsync.core.sync import SyncProposal

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
                np.asarray(exact_master, dtype=np.float64).copy()
                if exact_master is not None
                else []
            ),
            exact_source=(
                np.asarray(exact_source, dtype=np.float64).copy()
                if exact_source is not None
                else []
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
        # Everything this window knows about the source is dropped before the
        # grid tears the pane down, because `remove_pane` writes the session on
        # the way past and that snapshot must describe the session the user
        # just asked for, not the one with this video still in it.
        self.sidebar.remove_video(path)
        self._video_frame_times.pop(path, None)
        self._sync_provenance = [
            entry for entry in self._sync_provenance if entry.target_id != path
        ]
        self.video_grid.remove_pane(path)

    def _on_sensor_remove_requested(self, path: str) -> None:
        cache_dir = self._sensor_cache_dirs.pop(path, None)
        if cache_dir is None:
            # Pre-import removal: fall back to the manager's derived location.
            from avialsync.core.cache import CacheManager

            cache_dir = CacheManager(loader_version=3).get_cache_dir(Path(path))
        self.plot_pane.remove_channels(cache_dir)
        self.sidebar.remove_sensor(path)
        self.transport.set_source_coverage(path, 0.0, 0.0, "data")

    def _on_sensor_mapping_changed(self, path: str, offset: float, drift_ppm: float) -> None:
        """Re-align one time-series source against the master clock.

        This only changes the source's ``TimeMap`` — cached samples are never
        rewritten and no channel is re-imported (P3.5, mirrors video offsets).
        """
        cache_dir = self._sensor_cache_dirs.get(path)
        if cache_dir is None:
            return
        self.plot_pane.set_source_mapping(cache_dir, offset, drift_ppm)
        bounds = self.plot_pane.source_bounds(cache_dir)
        if bounds is not None:
            self.transport.set_source_coverage(path, bounds[0], bounds[1], "data")
            self._update_bounds(bounds[0], bounds[1])
        self.readout_panel.set_cursor(self.clock.state.t)

    def _on_channel_remove_requested(self, path: str, channel: str) -> None:
        """Remove only this source's row — another file may use the same name."""
        self.plot_pane.remove_channel(ChannelKey(path, channel))

    def _on_channel_visibility_changed(self, path: str, channel: str, is_visible: bool) -> None:
        self.plot_pane.set_channel_visible(ChannelKey(path, channel), is_visible)

    def _on_plot_channel_close_requested(self, source_id: str, channel: str) -> None:
        """Route a plot-row close through the owning source's visibility checkbox."""
        self.sidebar.set_channel_visible(channel, False, source_id)

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
        self,
        path: Path,
        loader_cls: type[TimeSeriesSource] | None = None,
        pre_config: dict | None = None,
    ) -> None:
        import_controller.start_data_import(self, path, loader_cls, pre_config)

    def _resolve_tracking_fps(self) -> tuple[float, bool]:
        return import_controller.resolve_tracking_fps(self)

    def _enqueue_import(self, path: Path, loader_cls: type, config: dict[str, Any]) -> None:
        import_controller.enqueue_import(self, path, loader_cls, config)

    def _start_import(self, path: Path, loader_cls: type, config: dict[str, Any]) -> None:
        import_controller.start_import(self, path, loader_cls, config)

    @Slot()
    def _on_import_thread_finished(self) -> None:
        import_controller.on_import_thread_finished(self)

    def _rebind_frame_indexed_sources(self, fps: float) -> None:
        import_controller.rebind_frame_indexed_sources(self, fps)

    def _on_import_finished(
        self,
        path: str,
        cache_dir: str,
        channels: list[str],
        bounds: tuple[float, float],
        inspection: object = None,
    ) -> None:
        import_controller.on_import_finished(self, path, cache_dir, channels, bounds, inspection)

    # ── Pose sources (overlay + 3D view, never plotted) ────

    def _register_tracking_source(
        self,
        path: str,
        cache_dir: Path,
        channels: list[str],
        role: str,
        inspection: object,
        offset: float = 0.0,
        drift_ppm: float = 0.0,
    ) -> None:
        import_controller.register_tracking_source(
            self, path, cache_dir, channels, role, inspection, offset, drift_ppm
        )

    def _refresh_pose_3d(self) -> None:
        import_controller.refresh_pose_3d(self)

    def _update_tracking_pane_visibility(self) -> None:
        import_controller.update_tracking_pane_visibility(self)

    def _refresh_overlays(self, video: str) -> None:
        import_controller.refresh_overlays(self, video)

    def _on_import_error(self, err_msg: str) -> None:
        import_controller.on_import_error(self, err_msg)

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
