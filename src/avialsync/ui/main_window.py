"""Main window for AvialSync."""

import dataclasses
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
    QKeyEvent,
    QResizeEvent,
    QValidator,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.channel_reader import ChannelKey
from avialsync.core.commands import (
    AcceptSyncCommand,
    AddMarkerCommand,
    AddSourceCommand,
    RelabelMarkerCommand,
    RemoveMarkerCommand,
    RemoveSourceCommand,
    ResetSessionCommand,
    SetChannelGroupVisibleCommand,
    SetChannelVisibleCommand,
    SetOverlayVisibleCommand,
    SetSourceMappingCommand,
    SetSourceVisibleCommand,
    SetTrackedPointCommand,
)
from avialsync.core.document import Document, SourceRecord
from avialsync.core.inspection import SourceInspection
from avialsync.core.point_edits import PointEditStore, PointKey, PointMove
from avialsync.core.session import (
    SessionState,
    SyncProvenance,
)
from avialsync.core.session_time import reference_epoch
from avialsync.core.source import TimeSeriesSource, VideoSource
from avialsync.core.timeline import MasterClock, TimeMap
from avialsync.engine.display_pipeline import DisplayLevels, SourceFormat
from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.player import Player
from avialsync.engine.snapshot import SnapshotFigure
from avialsync.ui.about import citation_text, project_urls, version_report
from avialsync.ui.accessibility import apply_accessibility, install_show_time_sweep
from avialsync.ui.annotations import AnnotationStore, Marker
from avialsync.ui.changes_panel import ChangeRow, ChangesPanel
from avialsync.ui.controllers import (
    changes_export_controller,
    corrections_controller,
    drop_controller,
    export_controller,
    import_controller,
    session_controller,
    video_controller,
)
from avialsync.ui.coverage_lanes import SourceCoverage
from avialsync.ui.empty_state import EmptyState
from avialsync.ui.feedback import ActivityBar, JobsPanel, NotificationStrip
from avialsync.ui.feedback.error_presenter import present
from avialsync.ui.feedback.text_dialog import show_text
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import JobManager
from avialsync.ui.levels_panel import LevelsPanel
from avialsync.ui.mutation_target import WindowMutationTarget, marker_record
from avialsync.ui.overlay_registry import OVERLAY_LAYERS, OverlayState, layer_for
from avialsync.ui.pane_proportions import PaneProportions
from avialsync.ui.plot_pane import PlotPane
from avialsync.ui.readout_panel import ReadoutPanel
from avialsync.ui.shortcut_overrides import apply_overrides
from avialsync.ui.splitter import PaneSplitter
from avialsync.ui.time_format import TimeDisplayMode
from avialsync.ui.tracking_3d_pane import Tracking3DPane
from avialsync.ui.transport import Transport
from avialsync.ui.ui_heartbeat import UiHeartbeat
from avialsync.ui.video_grid import VideoGrid

logger = logging.getLogger(__name__)

_AUTOSAVE_INTERVAL_MS = 120_000  # 2 minutes
#: How long the revisit ring stays on a point the Changes panel navigated to.
#: Long enough to find it, short enough not to be mistaken for a state the
#: correction is in.
_HIGHLIGHT_MS = 4000

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


def _validates_as_invalid(result: object) -> bool:
    """Return whether a Qt validator refused the text outright.

    ``QValidator.validate`` is typed as returning ``object`` by the PySide6
    stubs; it is really the state, or a tuple beginning with it, depending on
    the validator. Both shapes are read here rather than assumed, because
    guessing wrong would silently make every letter look acceptable and quietly
    undo the reservation this feeds.
    """
    state = result[0] if isinstance(result, tuple) and result else result
    return state == QValidator.State.Invalid


def _editor_rejects_text(widget: QWidget, text: str) -> bool:
    """Return whether *widget* would refuse *text* as typed input.

    A numeric field cannot hold a letter, so a letter arriving there is not
    editing — it is a shortcut the field happens to be swallowing. Asking the
    widget's own validator is what keeps this honest: a field that really does
    accept letters (an annotation label) keeps them, and only a field that would
    discard the character gives it up.
    """
    if len(text) != 1 or not text.isprintable():
        return False
    if isinstance(widget, QAbstractSpinBox):
        line_edit = widget.lineEdit()
        current = line_edit.text() if line_edit is not None else ""
        position = line_edit.cursorPosition() if line_edit is not None else len(current)
        candidate = current[:position] + text + current[position:]
        return _validates_as_invalid(widget.validate(candidate, position + 1))
    if isinstance(widget, QLineEdit):
        validator = widget.validator()
        if validator is None:
            # No validator means the field accepts arbitrary text, so a letter
            # typed into it is editing and belongs to the field.
            return False
        current = widget.text()
        position = widget.cursorPosition()
        candidate = current[:position] + text + current[position:]
        return _validates_as_invalid(validator.validate(candidate, position + 1))
    return False


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
        self.resize(1280, 800)

        self._session_path: Path | None = None
        self._session_generation = 0

        # The one place that knows whether this session has unsaved changes
        # (D-087). Dirty state, undo, and the autosave trigger all derive from
        # its log rather than being tracked separately -- which is why the
        # title was a constant string and closing preserved nothing before it.
        self.document = Document()
        self.document.observe_dirty(self._on_dirty_changed)
        # Held down while undo/redo drives the widgets, so replaying a command
        # does not record itself as a fresh edit and leave the stack unable to
        # unwind. Set before `_mutations`, which reads it.
        self._recording_suspended = False
        self._mutations = WindowMutationTarget(self)
        #: Last mapping recorded per source, so an offset command knows what to
        #: return to. The signal carries only the new value.
        self._recorded_mappings: dict[str, tuple[float, float]] = {}
        #: True while a saved session is being restored. Sources land
        #: asynchronously, so their arrival looks exactly like the user opening
        #: them; without this a freshly-loaded session would come up dirty and
        #: undo would offer to unload what the file said to load.
        self._session_restoring = False
        #: The camera the user last touched, so an action with no explicit
        #: target acts on the one they meant rather than on the first pane.
        self._selected_video_path: str | None = None
        #: Which overlay layers show, globally and per camera (D-090). Law 2:
        #: nothing is drawn over a frame that the user cannot turn off.
        self.overlay_state = OverlayState()
        #: Hand corrections to tracked points (D-099). Sparse, and written
        #: beside each pose file the moment they are made; the pose files
        #: themselves and their caches are never written.
        self.point_edits = PointEditStore()
        self.point_edits.observe(self._on_point_edits_changed)
        #: Where each source's corrections went. "session" only ever means
        #: writing beside the pose file failed, never a preference.
        self._point_edit_storage: dict[str, str] = {}
        #: What a restored session said each source should have, checked as that
        #: source imports so a missing sidecar is reported rather than silent.
        self._expected_correction_counts: dict[str, int] = {}
        #: Sources whose storage has already been reported, so a read-only
        #: volume does not raise the same strip on every drag.
        self._announced_correction_files: set[str] = set()

        # The feedback surface (D-091). JobManager already knew all of this;
        # none of it reached the user.
        self.activity_bar = ActivityBar(self)
        self.activity_bar.cancel_requested.connect(self._cancel_active_task)
        self.notifications = NotificationStrip(self)
        self.notifications.details_requested.connect(self._show_task_details)
        self.jobs_panel = JobsPanel(self)

        # Display levels, offered only for footage that has range to choose
        # from -- the panel asks the decoder what the recording actually is
        # rather than assuming a depth (D-093).
        self.levels_panel = LevelsPanel(self)
        self.levels_panel.levels_changed.connect(self._on_display_levels_changed)
        self.levels_panel.auto_requested.connect(self._on_auto_levels_requested)
        #: Per-source display window, keyed by path.
        self._display_levels: dict[str, DisplayLevels] = {}

        self._update_window_title()

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
        #: Per-item data kinds the claiming session declared, by path.
        self._session_item_kinds: dict[str, str] = {}
        #: Shared Data Streams lane names the claiming session asked for, by
        #: path. Only a session knows which of its files cover the same span.
        self._session_coverage_groups: dict[str, str] = {}
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
        #: Unix epoch of master-clock zero, after NWB's `session_start_time`.
        #: 0.0 until a source carrying wall-clock time declares it; see
        #: `core/session_time.py`.
        self._session_start_time: float = 0.0
        #: Trigger trains the user has loaded and typed, by file path. Evidence
        #: for the alignment wizard, not data: nothing here is ever plotted.
        self._trigger_trains: dict[str, list[Any]] = {}
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
        #: Cancel callback for whatever the activity bar is currently showing.
        #: Legacy workers are not registered with JobManager, so the bar needs
        #: its own handle to stop them (D-091).
        self._active_cancel: Callable[[], None] | None = None
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
        self.video_grid.set_point_edits(self.point_edits)
        self.video_grid.point_moved.connect(self._on_tracked_point_moved)
        self.tracking_3d_pane = Tracking3DPane(self)
        self.plot_pane = PlotPane(self)
        self.transport = Transport(self)
        self.data_streams = self.transport.detach_data_streams()
        self.transport.reset_zoom_requested.connect(self.plot_pane.reset_zoom)
        self.plot_pane.view_window_changed.connect(self.transport.set_plot_viewport)
        self.plot_pane.seek_requested.connect(self._on_plot_seek_requested)

        # Engine
        from avialsync.core.registry import LoaderRegistry

        self._registry = LoaderRegistry()
        # Discover plugins on a background thread rather than here. Constructing
        # the registry used to import every built-in loader inline -- `neo`
        # pulling in scipy and quantities, the AOL loader pulling in h5py --
        # which is ~470 ms of module IO on the UI thread warm, and was measured
        # at over four seconds cold behind on-access virus scanning, all of it
        # before the window appeared. Nothing in this constructor needs a
        # loader; the first file open does, and it waits on the same lock.
        self._registry.start_warmup()

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
        # Export Changes is available exactly when one of these has something
        # in it, so both drive the availability pass (D-107).
        self.annotation_store.changed.connect(self._refresh_action_availability)
        self.annotation_store.marker_added.connect(self._record_marker_added)
        self.annotation_store.marker_removed.connect(self._record_marker_removed)
        self.annotation_store.marker_relabelled.connect(self._record_marker_relabelled)

        # Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QHBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        from avialsync.ui.sidebar import SidebarPane

        self.sidebar = SidebarPane(self)
        self.sidebar.open_video_requested.connect(self._open_video)
        self.sidebar.open_sensor_requested.connect(self._open_data)
        self.sidebar.reset_session_requested.connect(self._reset_session)
        self.sidebar.video_offset_changed.connect(self._select_video)
        self.sidebar.video_offset_changed.connect(self._on_video_offset_changed)
        self.sidebar.video_mapping_changed.connect(self._on_video_mapping_changed)
        self.sidebar.video_badge_clicked.connect(self._select_video)
        self.sidebar.video_remove_requested.connect(self._on_video_remove_requested)
        # Persist before a removed pane's media client is torn down: that
        # teardown can fault on Windows, and mid-session it would otherwise
        # cost everything since the last autosave.
        self.video_grid.pane_detached.connect(self._write_session_snapshot)
        self.sidebar.video_visibility_changed.connect(self._on_video_visibility_changed)
        self.sidebar.sensor_remove_requested.connect(self._on_sensor_remove_requested)
        self.sidebar.sensor_mapping_changed.connect(self._on_sensor_mapping_changed)
        self.sidebar.channel_remove_requested.connect(self._on_channel_remove_requested)
        self.sidebar.channel_visibility_changed.connect(self._on_channel_visibility_changed)
        self.sidebar.channel_group_visibility_changed.connect(
            self._on_channel_group_visibility_changed
        )
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
        self.changes_panel = ChangesPanel(self.annotation_store, self.point_edits, self)
        self.changes_panel.set_correction_resolver(self._locate_correction)
        self.changes_panel.revisit_requested.connect(self._revisit_change)
        self.changes_panel.delete_correction_requested.connect(self._restore_predicted_point)
        self.plot_pane.set_annotation_store(self.annotation_store)

        # Messages the acquisition system recorded. A separate store from
        # annotations on purpose: these belong to the source file and must stay
        # read-only, while annotations are the user's own editable, exported work.
        from avialsync.ui.message_panel import MessagePanel, MessageStore

        self.message_store = MessageStore(self)
        self.message_store.changed.connect(self._update_timeline_messages)
        self.message_panel = MessagePanel(self.message_store, self)
        self.message_panel.seek_requested.connect(self._on_message_seek_requested)

        # One compact inspector keeps source management, values, messages, and
        # annotations available without permanently consuming four stacked panes
        # of workspace height. Messages sit beside annotations because they
        # answer the same question — what happened here — from the rig's side.
        self._left_tabs = QTabWidget(self)
        self._left_tabs.setAccessibleName(tr("Inspector"))
        self._left_tabs.addTab(self.sidebar, tr("Sources"))
        self._left_tabs.addTab(self.readout_panel, tr("Values"))
        self._left_tabs.addTab(self.message_panel, tr("Messages"))
        self._left_tabs.addTab(self.changes_panel, tr("Changes"))
        # Last tab: consulted when something is taking longer than expected,
        # which is not most of the time.
        self._left_tabs.addTab(self.jobs_panel, tr("Tasks"))
        # Display levels live under Sources, beside the camera they act on.
        # Hidden until a recording that has range to choose from is opened.
        self.sidebar.content_layout.addWidget(self.levels_panel)

        h_splitter = PaneSplitter(Qt.Orientation.Horizontal)
        h_splitter.addWidget(self._left_tabs)
        self._h_splitter = h_splitter

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._media_splitter = PaneSplitter(Qt.Orientation.Horizontal)
        self._media_splitter.setAccessibleName(tr("Video and 3D tracking splitter"))
        self._media_splitter.addWidget(self.video_grid)
        self._media_splitter.addWidget(self.tracking_3d_pane)
        self._media_splitter.setStretchFactor(0, 2)
        self._media_splitter.setStretchFactor(1, 1)
        # The 3D pane only earns workspace once a source actually has XYZ
        # triplets; otherwise an empty pane holds width the video needs.
        self.tracking_3d_pane.setVisible(False)

        v_splitter = PaneSplitter(Qt.Orientation.Vertical)
        v_splitter.addWidget(self._media_splitter)
        v_splitter.addWidget(self.plot_pane)
        v_splitter.setStretchFactor(0, 3)
        v_splitter.setStretchFactor(1, 1)
        self._v_splitter = v_splitter

        self._content_splitter = PaneSplitter(Qt.Orientation.Vertical)
        self._content_splitter.setAccessibleName(tr("Video, plots, and Data Streams splitter"))
        self._content_splitter.addWidget(v_splitter)
        self._content_splitter.addWidget(self.data_streams)
        self._content_splitter.setStretchFactor(0, 4)
        self._content_splitter.setStretchFactor(1, 1)
        right_layout.addWidget(self._content_splitter)
        # Above the transport, inside the layout rather than floating: a
        # notification must never cover the data it is reporting on.
        right_layout.addWidget(self.notifications)
        right_layout.addWidget(self.transport)

        h_splitter.addWidget(right_widget)
        h_splitter.setStretchFactor(0, 0)
        h_splitter.setStretchFactor(1, 1)

        # Every workspace surface may shrink horizontally in a compact viewport.
        # QSplitter then distributes constrained width by the remembered
        # proportions instead of letting a child size hint enlarge the window
        # beyond the display. Vertical size policies stay intact: they preserve
        # the established video/plot/Data Streams height allocation.
        for pane in (
            self._left_tabs,
            self.video_grid,
            self.tracking_3d_pane,
            self.plot_pane,
            self.data_streams,
            self.transport,
        ):
            pane.setSizePolicy(QSizePolicy.Policy.Ignored, pane.sizePolicy().verticalPolicy())

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

        # Feedback surface: activity in the status bar, outcomes in the strip.
        self._install_feedback_surface()

        # Empty state, over the video area until a recording is opened.
        self._install_empty_state()

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
        self.video_grid.pane_right_clicked.connect(lambda path, _pos: self._select_video(path))
        self.video_grid.pane_right_clicked.connect(self._on_pane_right_clicked)

        # Plot annotate-at (D-022)
        self.plot_pane.annotate_at_requested.connect(self._on_annotate_at_requested)

        # One window-owned timer clears the revisit ring. Owned here, not by a
        # pane: a timer that outlives the widget it repaints is a SIGSEGV with
        # no traceback (HANDOUT.md), and the window outlives every pane.
        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.timeout.connect(self._clear_point_highlight)

        # Autosave timer
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start(_AUTOSAVE_INTERVAL_MS)

        # Startup diagnostics (deferred so window shows first)
        QTimer.singleShot(500, self._run_diagnostics)

        # Unsaved work from a previous run, offered rather than imposed. Posting
        # is cheap -- one line in the notification strip; the restore itself
        # only happens if the user asks for it (D-089).
        session_controller.offer_pending_recovery(self)

        # Start player tick
        self.player.start()

        # Setup global shortcuts (must come after _setup_menu so _all_actions exists)
        self._setup_shortcuts()

        # User rebindings, layered over the defaults just established. Applied
        # last so a stored choice wins, and after the defaults are recorded so
        # Reset has something to restore (WP-3).
        apply_overrides(list(self._all_actions))

        # Name anything interactive that has not named itself. A sweep rather
        # than ninety manual calls, because the ninety-first widget is the one
        # that gets added without one (WP-12).
        #
        # This pass covers the chrome only: the application starts empty, so
        # there are no video panes, plot rows, source entries or quality badges
        # here to name yet. `_sweep_accessibility` runs again as those appear,
        # and `install_show_time_sweep` catches every dialog when it is shown
        # (D-107).
        apply_accessibility(self)
        app = QApplication.instance()
        if app is not None:
            #: Kept as an attribute, not a local: an event filter with no live
            #: Python reference is collected while Qt still holds a pointer to
            #: it.
            self._show_time_sweeper = install_show_time_sweep(app)

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

    def _install_empty_state(self) -> None:
        """Put the empty state over the video area until something is loaded."""
        self.empty_state = EmptyState(self)
        self.empty_state.open_videos_requested.connect(self._open_video)
        self.empty_state.open_data_requested.connect(self._open_data)
        self.empty_state.demo_requested.connect(self._launch_demo)
        grid_layout = self.video_grid.layout()
        if grid_layout is not None:
            grid_layout.addWidget(self.empty_state)
        self._refresh_empty_state()

    # ── Action availability (D-107) ──────────────────────────────────

    def _anything_loaded(self) -> bool:
        """Whether the workspace holds any recording at all."""
        return bool(self.video_grid.pane_paths()) or bool(self._sensor_cache_dirs)

    def _has_alignment_evidence(self) -> bool:
        """Whether both halves of a TTL/event fit are present.

        The same two conditions the wizard opener checks before it builds its
        specs, so the menu item and the command agree about availability rather
        than the command discovering it a click later.
        """
        if self._trigger_trains:
            # A trigger file the user has typed is evidence on its own terms;
            # it does not need a video to be worth fitting against.
            return True
        timed_videos = sum(1 for times in self._video_frame_times.values() if len(times) >= 3)
        if not timed_videos:
            return False
        # Either a sensor channel to fit against, or a second camera -- two
        # cameras carrying frame timestamps are evidence about each other.
        return bool(self.plot_pane.channels) or timed_videos >= 2

    def _require(self, action: QAction, precondition: Callable[[], bool], reason: str) -> QAction:
        """Register *action* as available only while *precondition* holds.

        Enablement was the one thing the action layer never derived from the
        live ``QAction``. Of the forty-six actions this window owns, two called
        ``setEnabled`` -- a menu placeholder and a locked overlay -- and the
        rest stayed live whatever was loaded, answering a click they could not
        honour with a modal saying so: "Load sensor data before exporting",
        "No videos are loaded", "Please set an A/B loop first". That is the
        state told after the gesture instead of before it.

        Undo and Redo already did this properly, following the document's own
        history (``ui/undo_adapter.py``); this is that pattern for the rest.
        The *reason* becomes the tooltip while the action is unavailable, so a
        greyed item still says what would make it available -- greying alone
        just moves the dead end earlier.
        """
        self._action_preconditions.append((action, precondition, reason, action.toolTip()))
        return action

    def _refresh_action_availability(self) -> None:
        """Re-answer every registered precondition.

        Cheap by construction: each precondition is a container check against
        state the window already holds, and there are a couple of dozen of
        them. It runs on the events that change what is loaded rather than on a
        timer, plus whenever a menu is about to be shown, so a command reached
        by shortcut or through the palette is as correctly enabled as one
        reached by opening the menu it lives in.
        """
        for action, precondition, reason, original_tip in self._action_preconditions:
            try:
                available = bool(precondition())
            except (AttributeError, RuntimeError):
                # A pane or reader torn down mid-refresh answers nothing; an
                # action that cannot prove it is available is not.
                available = False
            action.setEnabled(available)
            action.setToolTip(original_tip if available else reason)

    def _sweep_accessibility(self) -> None:
        """Name the widgets that were built after the window was (D-107).

        Video panes, plot rows, sidebar source entries and quality badges are
        all created as recordings load, long after the constructor's sweep.
        Idempotent, so calling it on every source change costs a walk and
        renames nothing that already has a name.
        """
        apply_accessibility(self)

    def _refresh_empty_state(self) -> None:
        """Show it only with nothing open, and never over real data."""
        self._refresh_action_availability()
        self._sweep_accessibility()
        empty_state = getattr(self, "empty_state", None)
        if empty_state is None:
            return
        nothing_loaded = not self.video_grid.pane_paths() and not self._sensor_cache_dirs
        empty_state.setVisible(nothing_loaded)
        # The grid's floor stays where `VideoGrid` set it, in every state. It
        # was raised to the empty state's own minimum here for one commit, so
        # five stacked controls would stop drawing as 2 px slivers; that made
        # the whole window unable to shrink below ~505 px tall and took the
        # 640x480 workspace guarantee with it. `EmptyState` scrolls instead, so
        # it survives a short video area without dictating a window minimum.

    def _launch_demo(self) -> None:
        """Generate and open the sample session.

        The generator already exists and is what `avialsync demo` runs; it was
        simply unreachable from inside the application. It writes files and
        encodes video, so it goes through the activity bar like any other long
        job rather than blocking the window (D-091).
        """
        from avialsync.demo import DemoLaunch

        try:
            # DemoLaunch carries its own non-modal progress window with an
            # activity log, which is more use here than a one-line status bar:
            # generation encodes four videos and the log says which one.
            self._demo_launch = DemoLaunch(self)
            self._demo_launch.start()
        except Exception as error:  # noqa: BLE001 - reported, not swallowed
            self.report_failure(error, doing="The demo session could not be generated")

    def _install_feedback_surface(self) -> None:
        """Put the activity bar in the status bar and the strip above the transport.

        The status bar is where a user already looks for "what is it doing";
        the strip sits in the layout rather than floating so it never covers
        the data it is reporting on.
        """
        self.statusBar().addPermanentWidget(self.activity_bar)

    def _cancel_active_task(self) -> None:
        """Stop whatever the activity bar is showing.

        Two registries, because the legacy import and proxy workers predate
        JobManager and are not registered with it. Both are asked; whichever
        owns the running work responds.
        """
        cancel = self._active_cancel
        if cancel is not None:
            try:
                cancel()
            except RuntimeError:
                # The worker's C++ side is already gone; nothing left to stop.
                pass
        self._job_manager.cancel_all()
        self.activity_bar.end()
        self._active_cancel = None

    def _show_task_details(self, details: str) -> None:
        """Show the full text behind a failure, on request only.

        A scrolling, copyable dialog rather than a message box: this text is a
        traceback or a worker's stderr, which has no length limit and is only
        useful if it can be pasted into a report (D-107).
        """
        show_text(self, tr("Details"), details)

    def report_failure(self, error: BaseException, *, doing: str = "") -> None:
        """Present a failure without taking the session away (AGENTS rule 12).

        The single route for anything that goes wrong on a load or save path.
        It replaces the shape this codebase used in forty places -- an exception
        string in a modal box with an OK button -- with a title in the user's
        terms, a plain-language cause, and the raw text behind Show details.

        Non-modal by design: whatever else is open still loaded and is still
        usable, and Law 1 says the application informs rather than blocks.
        """
        presented = present(error, doing=doing)
        message = f"{presented.title}. {presented.cause}"
        if presented.recoverable:
            self.notifications.show_error(message, details=presented.details)
        else:  # pragma: no cover - no unrecoverable presenter exists yet
            # The one failure that has earned an interruption. It still shows
            # its detail in the same scrolling, copyable dialog as everything
            # else rather than a message box (D-107).
            show_text(self, presented.title, presented.details, lead=message)

    def _refresh_jobs_panel(self) -> None:
        running = [(job.label, job.state.value, job.elapsed) for job in self._job_manager.jobs()]
        self.jobs_panel.refresh(running)

    def _on_jobs_changed(self) -> None:
        """Mirror background-job state into the transport status area.

        The panel is refreshed on *both* branches. It used to be refreshed only
        when a job was running, because the "nothing running" branch returned
        first — so the last job to finish stayed listed in the Tasks panel until
        some later job happened to start, and an idle application showed work
        in progress that had finished minutes ago (D-107).
        """
        text = self._job_manager.status_text()
        if not text:
            self.transport.set_status("Ready")
            self._refresh_jobs_panel()
            return
        kind = "error" if self._job_manager.stalled_jobs() else "busy"
        self.transport.set_status(text, kind)
        self._refresh_jobs_panel()

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
            # With three video columns, a quarter-width 3D pane is no wider
            # than one video column in the documented session layout.
            (self._media_splitter, (750, 250)),
        )
        for splitter, sizes in defaults:
            splitter.setSizes(list(sizes))
        # The inspector column is skipped: it is not proportion-managed, because
        # a source list that widens with the monitor only steals media width.
        for splitter, sizes in defaults[1:]:
            self._pane_proportions.set_fractions(splitter, sizes)

    def coverage_group_for(self, path: str) -> str:
        """Return the shared Data Streams lane *path* belongs in, if any.

        Empty for anything the current session did not group, which is every
        ordinary drop: a file with a span of its own keeps a lane of its own.
        """
        return self._session_coverage_groups.get(path, "")

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
            self.transport.set_source_coverage(
                path, span[0], span[1], "data", self.coverage_group_for(path)
            )

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

    def _update_timeline_messages(self) -> None:
        """Mirror recorded messages to the overview lane, text and all.

        Untimed notes are excluded rather than parked at zero: the lane is a
        map of when things happened, and a file header did not happen anywhere.
        The Messages tab still shows them.
        """
        self.transport.set_message_events(
            [
                (float(message.time), f"{Path(message.source_id).name}: {message.text}")
                for message in self.message_store.messages()
                if message.time is not None
            ]
        )

    def _on_message_seek_requested(self, t: float) -> None:
        """Seek to a message's timestamp, clamped to the loaded bounds."""
        bounds = self.clock.state.bounds
        self.player.seek(max(bounds[0], min(bounds[1], t)), exact=True)

    def _on_plot_seek_requested(self, t: float) -> None:
        """Seek the shared master clock to a time selected in a plot row."""
        bounds = self.clock.state.bounds
        self.player.seek(max(bounds[0], min(bounds[1], t)), exact=True)

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
            self.notifications.show_warning(
                tr("No import report was kept for {name}.").format(name=Path(path).name)
            )
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

    @property
    def session_start_time(self) -> float:
        """Unix epoch of master-clock zero, or 0.0 when the session has no wall clock."""
        return self._session_start_time

    def adopt_session_start(self, source_start: float) -> float:
        """Declare the session's zero from a source, if it has not been declared.

        Declared once and then kept (NWB): a reference that moved whenever an
        earlier source arrived would renumber every timestamp the user had
        already written down. Returns the reference in force afterwards.
        """
        reference = reference_epoch(self._session_start_time, source_start)
        if reference == self._session_start_time:
            return reference
        self._session_start_time = reference
        self._publish_session_epoch()
        return reference

    def _publish_session_epoch(self) -> None:
        """Give every time-displaying surface the epoch of master zero.

        `format_time` has always taken this and falls back to elapsed time when
        it is zero. Nothing ever passed one, so the UTC and local time-of-day
        display modes silently could not work -- two of three options on a menu
        that has been there since D-020.
        """
        epoch = self._session_start_time
        self.transport.set_t_epoch(epoch)
        self.plot_pane.set_time_mode(self._time_mode, epoch)
        self.message_panel.set_time_mode(self._time_mode, epoch)
        self.changes_panel.set_time_mode(self._time_mode, epoch)

    def _set_time_mode(self, mode: TimeDisplayMode) -> None:
        self._time_mode = mode
        self.transport.set_time_mode(mode)
        # Through the one place that knows the epoch, so a mode change cannot
        # reset a surface to elapsed time by passing the default.
        self._publish_session_epoch()
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
        every reallocation costs a full workspace relayout (video surfaces, the
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

    def _reset_session(self) -> None:
        """Clear the workspace, reversibly.

        Reset is one sidebar click that drops every pane, annotation, and
        recorded message. It is the one command allowed a bulk snapshot,
        because there is no compact way to describe "everything that was open"
        (D-087) -- so it is captured here, before the clear.
        """
        if not self._recording_suspended:
            try:
                command = ResetSessionCommand()
                command.snapshot = self._mutations.capture_workspace()
            except Exception:
                # Reset is the escape hatch: it is what a user reaches for when
                # the workspace is already in a state they want gone, which is
                # exactly when a snapshot is most likely to fail. Losing undo is
                # an acceptable degradation; refusing to clear is not.
                logger.exception("Could not capture the workspace; resetting without undo")
            else:
                self._record(command)
        session_controller.reset_session(self)

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
        # Export Trimmed Video Clip needs a loop, so its availability changes
        # here and nowhere else (D-107).
        self._refresh_action_availability()
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

    def _export_changes(self) -> None:
        changes_export_controller.export_changes(self)

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

        def _act(
            text: str,
            category: str,
            handler: Callable[[], None],
            *keys: Any,
            repeatable: bool = False,
        ) -> QAction:
            a = QAction(text, self)
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.setShortcutContext(_wsc)
            # Qt defaults `QAction.autoRepeat` to True, so holding a shortcut
            # runs its handler once per OS key repeat. For a *toggle* that is a
            # bug rather than a convenience: holding Space re-ran
            # "Play / Pause" on every repeat, flapping playback for as long as
            # the key was down and landing wherever the parity fell. Whether
            # a user ever saw it depended on their keyboard repeat delay and
            # rate, which on Windows is a per-machine Control Panel setting --
            # hence a report of double-toggling "only on some machines".
            #
            # So repeat is opted into, never inherited: it stays on only where
            # holding the key *is* the gesture (frame stepping, second jumps,
            # plot zoom), and every toggle and one-shot action is off.
            a.setAutoRepeat(repeatable)
            a.triggered.connect(handler)
            a.setProperty("av_category", category)
            self.addAction(a)
            self._all_actions.append(a)
            # Remember single-character shortcuts, so a numeric field cannot
            # silently swallow one (see `_reserve_letter_shortcut`).
            for sequence in a.shortcuts():
                text = sequence.toString()
                if len(text) == 1 and text.isalpha():
                    self._letter_shortcuts.add(text.lower())
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
            repeatable=True,
        )
        _act(
            "Step forward 1 frame",
            "Playback",
            lambda: self.transport.frame_step_requested.emit(1),
            Qt.Key.Key_Right,
            Qt.Key.Key_Period,
            repeatable=True,
        )

        # Jump ±1 s: emit transport signal (D-022.1 — duplicates –1s/+1s buttons)
        _act(
            "Jump back 1 second",
            "Playback",
            lambda: self.transport.jump_requested.emit(-1.0),
            "Shift+Left",
            "J",
            repeatable=True,
        )
        _act(
            "Jump forward 1 second",
            "Playback",
            lambda: self.transport.jump_requested.emit(1.0),
            "Shift+Right",
            repeatable=True,
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
        _act("Plot zoom in", "View", self.plot_pane.zoom_in, "+", repeatable=True)
        _act("Plot zoom out", "View", self.plot_pane.zoom_out, "-", repeatable=True)

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
            # Only the video-load probes are left outside JobManager; the four
            # export registries this used to sweep are registered jobs now, and
            # `self._job_manager.shutdown()` below is what stops them (D-107).
            _quit_legacy_jobs(self._video_load_jobs)

        # Ordering matters twice over.
        #
        # State is captured before anything is torn down: `_build_session_state`
        # reads `video_grid.panes`, and `video_grid.shutdown()` clears them, so
        # running the autosave afterwards wrote a session with zero videos and
        # silently discarded the user's video list on every close (D-059).
        #
        # Decoder teardown goes last, and every step is isolated. Each pane owns
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
        if event_type == QEvent.Type.ShortcutOverride and (
            self._reserve_playhead_key(event) or self._reserve_letter_shortcut(event)
        ):
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

    def _reserve_letter_shortcut(self, event: QEvent) -> bool:
        """Return whether a letter shortcut outranks the editor holding focus.

        The playhead keys above are reserved unconditionally because no editor
        we own has a use for them. Letters are different: ``J``/``K``/``L``
        shuttle playback, but they are also perfectly ordinary text. So they are
        only taken back from a field that would have refused them anyway — a
        numeric spin box, or a line edit whose validator rejects the character.
        A field that accepts letters keeps typing them.
        """
        if not isinstance(event, QKeyEvent):
            return False
        text = event.text()
        if text.lower() not in self._letter_shortcuts:
            return False

        app = QApplication.instance()
        focus = app.focusWidget() if isinstance(app, QApplication) else None
        if focus is None or focus.window() is not self:
            return False
        return _editor_rejects_text(focus, text)

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
        #: Lower-cased single-character shortcut keys, collected as actions are
        #: registered so nothing has to restate the bindings.
        self._letter_shortcuts: set[str] = set()
        #: (action, precondition, reason, original tooltip) for every command
        #: that needs something loaded. See `_require`.
        self._action_preconditions: list[tuple[QAction, Callable[[], bool], str, str]] = []

        def _reg(act: QAction, category: str) -> QAction:
            """Tag an action with its category and add it to the registry."""
            act.setProperty("av_category", category)
            # No menu action is a hold-to-repeat gesture -- opening a file
            # dialog or cycling the theme once per key repeat is never what was
            # meant. See `_act` for why Qt's default is the wrong one here.
            act.setAutoRepeat(False)
            # Registered whether or not it has a shortcut. The shortcuts dialog
            # filters for bound ones itself; the command palette wants the rest
            # too, since a command with no key is exactly the one somebody
            # cannot find (WP-3).
            self._all_actions.append(act)
            return act

        menu = self.menuBar()

        # ── File ──────────────────────────────────────────────────────
        file_menu = menu.addMenu(tr("File"))

        # Ctrl+Shift+V (not Ctrl+V — system Paste collision, D-022.7 / Trap §18)
        act = file_menu.addAction(tr("Open Video(s)…"))
        act.setShortcut(QKeySequence("Ctrl+Shift+V"))
        act.triggered.connect(self._open_video)
        _reg(act, "File")

        # Ctrl+Shift+D (not Ctrl+D — bookmark/dock collision, D-022.7 / Trap §18)
        act = file_menu.addAction(tr("Open Sensor/Ephys Data…"))
        act.setShortcut(QKeySequence("Ctrl+Shift+D"))
        act.triggered.connect(self._open_data)
        _reg(act, "File")

        file_menu.addSeparator()

        act = file_menu.addAction(tr("Save Session…"))
        act.setShortcut(QKeySequence(QKeySequence.StandardKey.Save))
        act.triggered.connect(self._save_session)
        _reg(act, "File")
        self._require(
            act,
            self._anything_loaded,
            tr("Open a recording first — an empty workspace has nothing to save."),
        )

        act = file_menu.addAction(tr("Open Session…"))
        act.setShortcut(QKeySequence(QKeySequence.StandardKey.Open))
        act.triggered.connect(self._open_session)
        _reg(act, "File")

        file_menu.addSeparator()

        self._act_export_changes = file_menu.addAction(tr("Export Changes…"))
        act = self._act_export_changes
        act.triggered.connect(self._export_changes)
        self.changes_panel.set_export_action(act)
        self._require(
            act,
            lambda: bool(self.annotation_store.markers) or len(self.point_edits) > 0,
            tr("Flag a frame or correct a tracked point first — there is nothing to export yet."),
        )

        self._recent_menu = file_menu.addMenu(tr("Recent Sessions"))
        self._rebuild_recent_menu()

        file_menu.addSeparator()

        # Export Snapshot — Ctrl+E is the single authority; no duplicate QShortcut
        self._act_snapshot = file_menu.addAction(tr("Export Snapshot…"))
        self._act_snapshot.setShortcut(QKeySequence("Ctrl+E"))
        self._act_snapshot.triggered.connect(self._export_snapshot)
        _reg(self._act_snapshot, "File")
        self._require(
            self._act_snapshot,
            self._anything_loaded,
            tr("Load a video or a data file to have something to snapshot."),
        )

        act = file_menu.addAction(tr("Export Trimmed Video Clip…"))
        act.triggered.connect(self._export_video_clip)
        self._require(
            act,
            lambda: bool(self.video_grid._paths) and self.transport._ab_in_t is not None,
            tr("Load a video and mark an A/B loop — [ and ] set where a clip starts and ends."),
        )

        act = file_menu.addAction(tr("Export Data Slice…"))
        act.triggered.connect(self._export_data_slice)
        self._require(
            act,
            lambda: bool(self.plot_pane.channels),
            tr("Load sensor or ephys data to have a slice to export."),
        )

        act = file_menu.addAction(tr("Generate Proxy…"))
        act.triggered.connect(self._generate_proxy)
        self._require(
            act,
            lambda: bool(self.video_grid._paths),
            tr("Load a video first — a proxy is a lighter copy of one."),
        )

        file_menu.addSeparator()

        # Preferences — macOS PreferencesRole moves this to the app menu, the
        # same treatment About and Quit already get (D-022.3).
        act = file_menu.addAction(tr("Preferences…"))
        act.setShortcut(QKeySequence(QKeySequence.StandardKey.Preferences))
        act.setMenuRole(QAction.MenuRole.PreferencesRole)
        act.triggered.connect(self._show_preferences)
        _reg(act, "File")

        file_menu.addSeparator()

        # Quit — macOS QuitRole moves this to the app menu (D-022.3)
        act = file_menu.addAction(tr("Quit"))
        act.setShortcut(QKeySequence(QKeySequence.StandardKey.Quit))
        act.setMenuRole(QAction.MenuRole.QuitRole)
        act.triggered.connect(self.close)
        _reg(act, "File")

        # ── Edit ──────────────────────────────────────────────────────
        # There was no Edit menu at all, which on macOS is a visible platform
        # conventions violation and everywhere else means nothing is reversible.
        from avialsync.ui.undo_adapter import install_edit_menu

        # Retained: a QMenu reachable only through `menuBar().actions()` can
        # have its C++ side collected while the Python wrapper survives, which
        # surfaces as "Internal C++ object already deleted" on next access.
        self._edit_menu = menu.addMenu(tr("Edit"))
        self._undo_actions = install_edit_menu(self, self._edit_menu)
        _reg(self._undo_actions.undo_action, "Edit")
        _reg(self._undo_actions.redo_action, "Edit")

        # Fix Tracker. One QAction drives both the menu entry and the button in
        # the Data Streams header, so the label, the shortcut, and the checked
        # state have a single author (D-092, architecture rule 15).
        self._edit_menu.addSeparator()
        self._act_fix_tracker = self._edit_menu.addAction(tr("Fix Tracker"))
        self._act_fix_tracker.setCheckable(True)
        self._act_fix_tracker.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self._act_fix_tracker.setToolTip(
            tr("Drag a tracked point where it belongs, in every video pane")
        )
        self._act_fix_tracker.toggled.connect(self._toggle_point_edit_mode)
        _reg(self._act_fix_tracker, "Edit")
        self.transport.install_fix_tracker_action(self._act_fix_tracker)

        # ── Align ─────────────────────────────────────────────────────
        # Promoted out of File. Alignment is not a file operation -- it is the
        # reason this application exists, and it sat between Open Sensor Data
        # and Save Session (WP-10).
        self._align_menu = menu.addMenu(tr("Align"))

        act = self._align_menu.addAction(tr("Synchronize TTL / events…"))
        act.setToolTip(tr("Fit an offset from events both recordings share"))
        act.triggered.connect(self._open_sync_wizard)
        _reg(act, "Align")
        self._require(
            act,
            self._has_alignment_evidence,
            tr(
                "Load a video with frame timestamps, and either a TTL-bearing sensor "
                "channel or a second such video, to have evidence to fit."
            ),
        )

        act = self._align_menu.addAction(tr("Open Trigger Evidence…"))
        act.setToolTip(tr("Load a TTL or strobe file and say what each of its lines is"))
        act.triggered.connect(self._open_trigger_evidence)
        _reg(act, "Align")

        self._align_menu.addSeparator()
        act = self._align_menu.addAction(tr("Nudge selected source earlier"))
        act.setShortcut(QKeySequence("Ctrl+Shift+Left"))
        act.triggered.connect(lambda: self._nudge_alignment(-1))
        _reg(act, "Align")
        self._require(
            act,
            lambda: bool(self.video_grid._paths),
            tr("Load a video before nudging its alignment."),
        )

        act = self._align_menu.addAction(tr("Nudge selected source later"))
        act.setShortcut(QKeySequence("Ctrl+Shift+Right"))
        act.triggered.connect(lambda: self._nudge_alignment(+1))
        _reg(act, "Align")
        self._require(
            act,
            lambda: bool(self.video_grid._paths),
            tr("Load a video before nudging its alignment."),
        )

        # ── View ──────────────────────────────────────────────────────
        view_menu = menu.addMenu(tr("View"))

        theme_menu = view_menu.addMenu(tr("Theme"))
        self._theme_group = QActionGroup(self)
        for label, key in [("System", "system"), ("Dark", "dark"), ("Light", "light")]:
            ta = theme_menu.addAction(label)
            ta.setCheckable(True)
            ta.setData(key)
            self._theme_group.addAction(ta)
        self._theme_group.triggered.connect(self._on_theme_selected)
        self._sync_theme_menu()

        font_menu = view_menu.addMenu(tr("Font Size"))
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

        time_menu = view_menu.addMenu(tr("Time Display"))
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
        # Overlays: one checkbox per registered layer, generated from the
        # registry so a new overlay cannot ship without one (D-090).
        self._overlays_menu = view_menu.addMenu(tr("Overlays"))
        self._build_overlays_menu(_reg)
        view_menu.addSeparator()

        # Workspaces: a session is looked at in more than one way, and
        # rearranging the splitters each time is friction enough to stop
        # people doing it (WP-11).
        self._workspace_menu = view_menu.addMenu(tr("Workspace"))
        self._rebuild_workspace_menu()
        view_menu.addSeparator()

        self._act_reset_zoom = view_menu.addAction(tr("Reset Plot Zoom"))
        self._act_reset_zoom.setShortcut(QKeySequence("Ctrl+0"))
        self._act_reset_zoom.triggered.connect(self.plot_pane.reset_zoom)
        _reg(self._act_reset_zoom, "View")
        self._require(
            self._act_reset_zoom,
            lambda: bool(self.plot_pane.channels),
            tr("There are no plots to reset until data is loaded."),
        )

        # Fullscreen toggle — StandardKey.FullScreen = F11 / Ctrl+Cmd+F on macOS (D-022.2)
        self._act_fullscreen = view_menu.addAction(tr("Toggle Pane Fullscreen"))
        self._act_fullscreen.setShortcut(QKeySequence(QKeySequence.StandardKey.FullScreen))
        self._act_fullscreen.triggered.connect(self._toggle_fullscreen)
        _reg(self._act_fullscreen, "View")
        self._require(
            self._act_fullscreen,
            lambda: bool(self.video_grid._paths),
            tr("Load a video — fullscreen applies to a camera pane."),
        )

        # Pass reset-zoom action to plot pane so the context menu uses the same object (D-022)
        self.plot_pane.set_context_actions([self._act_reset_zoom])

        # ── Help ──────────────────────────────────────────────────────
        help_menu = menu.addMenu(tr("Help"))

        # Shortcuts dialog: F1 primary (HelpContents); "?" alias added in _setup_shortcuts
        # Commands — searchable by name. The menus are deep enough now that
        # finding a command is the problem, not typing it (WP-3).
        act = help_menu.addAction(tr("Commands…"))
        act.setShortcut(QKeySequence("Ctrl+Shift+P"))
        act.setToolTip(tr("Search every command by name"))
        act.triggered.connect(self._show_command_palette)
        _reg(act, "View")

        self._act_shortcuts = help_menu.addAction(tr("Keyboard Shortcuts…"))
        self._act_shortcuts.setShortcut(QKeySequence(QKeySequence.StandardKey.HelpContents))
        self._act_shortcuts.triggered.connect(self._show_shortcuts)
        _reg(self._act_shortcuts, "View")

        act = help_menu.addAction(tr("Documentation"))
        act.triggered.connect(lambda: self._open_project_url("Documentation"))
        act = help_menu.addAction(tr("Report a Problem…"))
        act.triggered.connect(self._report_a_problem)
        act = help_menu.addAction(tr("Check for Updates"))
        act.setToolTip(tr("The installers are not code-signed and do not update themselves"))
        act.triggered.connect(lambda: self._open_project_url("Changelog"))
        help_menu.addSeparator()

        act = help_menu.addAction(tr("Cite AvialSync…"))
        act.triggered.connect(self._show_citation)

        act = help_menu.addAction(tr("Diagnostics…"))
        act.triggered.connect(self._show_diagnostics)

        # About — macOS AboutRole moves this to the app menu (D-022.3)
        act = help_menu.addAction(tr("About AvialSync"))
        act.setMenuRole(QAction.MenuRole.AboutRole)
        act.triggered.connect(self._show_about)

        # Belt and braces for availability (D-107). The state-change hooks are
        # what keep a shortcut and the command palette honest; this catches the
        # menu itself in the case nobody predicted, at the one moment it is
        # about to be read, for the price of a couple of dozen predicate calls.
        for opened in (file_menu, self._align_menu, view_menu, help_menu):
            opened.aboutToShow.connect(self._refresh_action_availability)

        # Nothing is loaded yet, so most of this starts unavailable and says so.
        self._refresh_action_availability()

    # ── Workspaces (WP-11) ───────────────────────────────────────────

    def _rebuild_workspace_menu(self) -> None:
        """Regenerate the Workspace menu from what is actually stored."""
        from avialsync.ui import workspaces

        self._workspace_menu.clear()
        saved = workspaces.names()
        if saved:
            for name in saved:
                act = self._workspace_menu.addAction(name)
                act.triggered.connect(lambda _c, n=name: self._apply_workspace(n))
        else:
            act = self._workspace_menu.addAction(tr("(no saved layouts)"))
            act.setEnabled(False)
        self._workspace_menu.addSeparator()

        act = self._workspace_menu.addAction(tr("Save Current Layout…"))
        act.triggered.connect(self._save_workspace)
        if saved:
            act = self._workspace_menu.addAction(tr("Delete Layout…"))
            act.triggered.connect(self._delete_workspace)

    def _save_workspace(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        from avialsync.ui import workspaces

        name, accepted = QInputDialog.getText(self, "Save Layout", "Name this layout:")
        if not accepted or not name.strip():
            return
        workspaces.save(name, workspaces.capture(self))
        self._rebuild_workspace_menu()
        self.notifications.show_success(f"Layout saved as “{name.strip()}”.")

    def _apply_workspace(self, name: str) -> None:
        from avialsync.ui import workspaces

        workspace = workspaces.load(name)
        if workspace is None:
            self.notifications.show_warning(f"Layout “{name}” is no longer stored.")
            self._rebuild_workspace_menu()
            return
        workspaces.apply(self, workspace)

    def _delete_workspace(self) -> None:
        """Delete a saved layout, and offer it back for as long as the message shows.

        Saving a layout said so and deleting one said nothing, which is the
        wrong way round: the destructive half is the one that needs an answer
        (D-107). Rather than a "are you sure?" gate in front of a reversible
        act, the deletion happens and the layout is held here, offered back
        under Undo on the notification strip — the same shape as the recovery
        offer, and the same reason: never block, always inform.
        """
        from PySide6.QtWidgets import QInputDialog

        from avialsync.ui import workspaces

        saved = workspaces.names()
        if not saved:
            return
        name, accepted = QInputDialog.getItem(
            self, tr("Delete Layout"), tr("Layout:"), saved, 0, False
        )
        if not (accepted and name):
            return

        removed = workspaces.load(name)
        workspaces.remove(name)
        self._rebuild_workspace_menu()

        if removed is None:
            self.notifications.show_warning(
                tr("Layout “{name}” was already gone.").format(name=name)
            )
            return

        def _restore() -> None:
            workspaces.save(name, removed)
            self._rebuild_workspace_menu()
            self.notifications.show_success(tr("Layout “{name}” is back.").format(name=name))

        self.notifications.show_warning(
            tr("Deleted layout “{name}”.").format(name=name),
            action_label=tr("Undo"),
            on_action=_restore,
        )

    # ── Alignment (WP-10) ────────────────────────────────────────────

    def _nudge_alignment(self, direction: int) -> None:
        """Shift the focused video by one frame against the master clock.

        Aligning by eye is the most common real workflow and had no direct
        path: the only control was a spin box with 0.05 s steps, which is more
        than a frame at any rate this application targets. A frame is the unit
        the user is actually judging.
        """
        path = self._focused_video_path()
        if path is None:
            if self.video_grid.pane_paths():
                # Several cameras and none chosen. Guessing moved the wrong
                # one silently, which is worse than saying so.
                self.notifications.show_warning(
                    "Click the camera you want to move first, or open one fullscreen."
                )
            else:
                self.notifications.show_warning("Load a video before nudging its alignment.")
            return

        fps = self._video_fps.get(path, 0.0)
        step = (1.0 / fps) if fps > 0 else 0.001
        offset, drift = self._recorded_mappings.get(path, (0.0, 0.0))
        new_offset = offset + direction * step

        self.sidebar.set_video_offset(path, new_offset)
        self._on_video_offset_changed(path, new_offset)
        self.transport.set_status(
            f"{Path(path).name} offset {new_offset:+.4f} s ({direction:+d} frame)", "info"
        )

    def _supersede_alignment(
        self, source_id: str, before: tuple[float, float], after: tuple[float, float]
    ) -> None:
        """Mark accepted evidence as no longer describing this source.

        A fit accepted at two milliseconds and then nudged five frames is no
        longer that fit, but nothing used to connect the two: the session kept
        reporting the residual of a mapping it was no longer using. The record
        is annotated rather than dropped, so the user can still see what the
        alignment was and that it has been moved off it by hand.
        """
        moved = after[0] - before[0]
        for index, entry in enumerate(self._sync_provenance):
            if entry.target_id != source_id or entry.superseded_by:
                continue
            self._sync_provenance[index] = dataclasses.replace(
                entry,
                superseded_by=(
                    f"moved {moved:+.4f} s by hand after it was accepted "
                    f"({self._describe_provenance(entry)})"
                ),
            )
            self.refresh_alignment_badges()

    def alignment_confidence(self, path: str) -> str:
        """One line describing how this source is aligned, or that it is not.

        Derived from the accepted provenance, which is the record of what was
        actually agreed to. Event-driven: never sampled on the clock tick.

        Every method is described in the terms it supports, and no others.
        This used to print `max_residual` as a "±" for every record alike,
        which turned a hand-typed offset into "± 0.0 ms from 3 events" -- the
        most confident thing the sentence could say, about the one kind of
        mapping that measured nothing.
        """
        for entry in self._sync_provenance:
            if entry.target_id != path:
                continue
            if entry.superseded_by:
                return f"alignment superseded: {entry.superseded_by}"
            reference = Path(entry.reference_id).name or entry.reference_id
            return f"aligned to {reference}: {self._describe_provenance(entry)}"
        return "no accepted alignment"

    def refresh_alignment_badges(self) -> None:
        """Push each source's alignment state onto its badge.

        Event-driven, from the four things that can change it: accepting a fit,
        moving a source by hand, removing a source, and restoring a session.
        Never sampled on the clock tick -- this walks every loaded source, and
        doing that sixty times a second to display a string that changes a
        handful of times per session is the shape architecture rule 3 forbids.
        """
        for path in self.video_grid.pane_paths():
            summary = self.alignment_confidence(path)
            self.sidebar.set_video_alignment(path, summary, accepted=self._has_live_alignment(path))
        for path in self._sensor_cache_dirs:
            summary = self.alignment_confidence(path)
            self.sidebar.set_sensor_alignment(
                path, summary, accepted=self._has_live_alignment(path)
            )

    def _has_live_alignment(self, path: str) -> bool:
        """Whether accepted evidence still describes this source.

        Superseded evidence does not count. The source sits where a person put
        it, which is a legitimate place to be and an entirely different claim
        from a fit nobody has contradicted.
        """
        return any(
            entry.target_id == path and not entry.superseded_by for entry in self._sync_provenance
        )

    @staticmethod
    def _describe_provenance(entry: SyncProvenance) -> str:
        """Render a persisted record through the same words a live fit uses."""
        from avialsync.core.sync import AlignmentMethod, SyncFit

        return SyncFit(
            offset=entry.offset,
            drift_ppm=entry.drift_ppm,
            rms_residual=entry.rms_residual,
            max_residual=entry.max_residual,
            matched_count=entry.matched_count,
            rejected_count=entry.rejected_count,
            reference_count=entry.reference_count,
            target_count=entry.target_count,
            offset_stderr=entry.offset_stderr,
            ambiguity_margin=entry.ambiguity_margin,
            method=AlignmentMethod(entry.method),
        ).describe()

    # ── Overlays (D-090) ─────────────────────────────────────────────

    def _build_overlays_menu(self, register) -> None:
        """Generate View -> Overlays from the registry, grouped.

        Generated rather than hand-written: a hand-written menu is how the next
        overlay ships without a switch, which is the failure Law 2 exists to
        prevent.
        """
        self._overlay_actions: dict[str, QAction] = {}
        current_group = ""
        for layer in OVERLAY_LAYERS:
            if current_group and layer.group != current_group:
                self._overlays_menu.addSeparator()
            current_group = layer.group

            action = self._overlays_menu.addAction(layer.label)
            action.setCheckable(True)
            action.setChecked(self.overlay_state.is_visible(layer.overlay_id))
            action.setToolTip(layer.description)
            if layer.locked:
                # Registered and shown, but not switchable. Greyed with the
                # reason in the tooltip, so the exception stays visible rather
                # than becoming folklore.
                action.setEnabled(False)
            else:
                action.toggled.connect(
                    lambda checked, oid=layer.overlay_id: self._on_overlay_toggled(oid, checked)
                )
            register(action, "View")
            self._overlay_actions[layer.overlay_id] = action

        self._overlays_menu.addSeparator()
        show_all = self._overlays_menu.addAction(tr("Show All"))
        show_all.triggered.connect(lambda: self._set_all_overlays(True))
        hide_all = self._overlays_menu.addAction(tr("Hide All"))
        hide_all.triggered.connect(lambda: self._set_all_overlays(False))

    def _on_overlay_toggled(
        self, overlay_id: str, visible: bool, camera: str | None = None
    ) -> None:
        """Apply an overlay change and record it as undoable."""
        if not self.overlay_state.set_visible(overlay_id, visible, camera):
            return
        layer = layer_for(overlay_id)
        self._record(
            SetOverlayVisibleCommand(
                overlay_id=overlay_id,
                visible=visible,
                camera=camera,
                display_name=layer.label if layer else overlay_id,
            )
        )
        self._apply_overlay_state()

    def _set_all_overlays(self, visible: bool) -> None:
        for layer in OVERLAY_LAYERS:
            if not layer.locked:
                self._on_overlay_toggled(layer.overlay_id, visible)

    def _apply_overlay_state(self) -> None:
        """Push resolved visibility to every pane and re-check the menu."""
        self.video_grid.set_overlay_visibility(self.overlay_state.visibility_for)
        for overlay_id, action in getattr(self, "_overlay_actions", {}).items():
            blocked = action.blockSignals(True)
            try:
                action.setChecked(self.overlay_state.is_visible(overlay_id))
            finally:
                action.blockSignals(blocked)

    # ── Fix Tracker: correcting a predicted point by hand (D-099) ────

    def _toggle_point_edit_mode(self, enabled: bool) -> None:
        """Turn point correction on or off across every video pane.

        Playback stops on the way in.  A moving frame makes the gesture
        impossible -- the marker being aimed at is somewhere else by the time
        the button goes down -- and stopping is what the user is about to do by
        hand anyway.  This is presentation state, not a document mutation, so
        it is deliberately not on the undo stack: undo reverses corrections,
        not the mode you made them in.
        """
        enabled = bool(enabled)
        if enabled and self.clock.state.playing:
            # Same route the K shortcut takes, so the transport button, the
            # player, and the clock stay in agreement.
            self.transport.play_toggled.emit(False)
        self.video_grid.set_point_edit_mode(enabled)
        if enabled:
            self.transport.set_status(
                tr("Fix Tracker on — drag a point to correct it. Playback paused."), "info"
            )
        else:
            corrections = len(self.point_edits)
            self.transport.set_status(
                tr("Fix Tracker off — {n} corrected point(s) in this session.").format(
                    n=corrections
                )
                if corrections
                else tr("Fix Tracker off."),
                "info",
            )

    def _on_tracked_point_moved(self, move: object) -> None:
        """Route a finished drag through the command bus so it can be undone."""
        if not isinstance(move, PointMove):
            return
        self.document.execute(
            SetTrackedPointCommand(
                source_id=move.key.source_id,
                point=move.key.point,
                index=move.key.index,
                before=move.before,
                after=move.after,
                display_frame=corrections_controller.frame_for(
                    self, move.key.source_id, move.key.index
                ),
            ),
            self._mutations,
        )

    def _on_point_edits_changed(self, source_id: str | None) -> None:
        """Repaint every overlay after a correction is applied, undone, or loaded.

        The window observes the store, not each pane: a callback held by a
        widget outlives it, and a repaint scheduled onto a freed pane is a
        SIGSEGV with no traceback (HANDOUT.md).  The window outlives them all.

        *source_id* is unused here -- every pane repaints either way -- but it is
        what tells the persistence path a change came from the user rather than
        from reading a sidecar back in.
        """
        # The first correction is what makes Export Changes available (D-107).
        self._refresh_action_availability()
        del source_id
        grid = getattr(self, "video_grid", None)
        if grid is not None:
            grid.refresh_point_edits()
        panel = getattr(self, "changes_panel", None)
        if panel is not None:
            panel.refresh()

    def _locate_correction(self, key: object) -> tuple[float, str, int] | None:
        """Place a correction on the master clock, a camera, and a frame.

        The Changes panel cannot work this out: it needs the pose source's own
        time column and the video that source overlays, and both live here.
        """
        if not isinstance(key, PointKey):
            return None
        for video, sources in self._overlay_sources.items():
            entry = sources.get(key.source_id)
            if entry is None:
                continue
            points = entry.get("points") or {}
            axes = points.get(key.point) or next(iter(points.values()), None)
            if axes is None:
                return None
            reader = axes[0]
            times = reader.source_reader.mapped_columns()[0]
            if not 0 <= key.index < len(times):
                return None
            t_master = float(reader.time_map.to_master(float(times[key.index])))
            frame = corrections_controller.frame_for(self, key.source_id, key.index)
            return t_master, video, frame
        return None

    def _revisit_change(self, row: object) -> None:
        """Go to a change the user selected in the panel.

        Seek, select the camera it belongs to, and -- for a correction -- ring
        the body part, because landing on the right frame with nine markers on
        screen is only half of "show me that again".
        """
        if not isinstance(row, ChangeRow):
            return
        if row.t_master is not None:
            self.player.seek(row.t_master, exact=True)
        if row.camera:
            self._select_video(row.camera)
        self.video_grid.highlight_point(row.point)
        if row.point is not None:
            self._highlight_timer.start(_HIGHLIGHT_MS)

    def _clear_point_highlight(self) -> None:
        """Drop the revisit ring once it has done its job."""
        self.video_grid.highlight_point(None)

    def _restore_predicted_point(self, key: object) -> None:
        """Undo one correction from the panel, through the command bus."""
        if not isinstance(key, PointKey):
            return
        before = self.point_edits.get(key)
        if before is None:
            return
        self.document.execute(
            SetTrackedPointCommand(
                source_id=key.source_id,
                point=key.point,
                index=key.index,
                before=before,
                after=None,
                display_frame=corrections_controller.frame_for(self, key.source_id, key.index),
            ),
            self._mutations,
        )

    def _persist_point_edits(self, source_id: str) -> None:
        """Write one pose source's corrections beside it, immediately."""
        corrections_controller.persist(self, source_id)

    def _adopt_point_edits(self, source_id: str) -> None:
        """Load the corrections that live beside a pose file being imported."""
        corrections_controller.adopt(self, source_id)

    # ── Command bus: recording live mutations (WP-1 step 4) ──────────

    def _record(self, command: object) -> None:
        """Log an already-applied mutation, unless undo is replaying one.

        `record` rather than `execute`: the widget has already done the work by
        the time its signal arrives, and re-applying it here would double the
        change. The Document coalesces continuous edits, so a spin-box drag
        stays one undo step.
        """
        if self._recording_suspended:
            return
        self.document.record(command)  # type: ignore[arg-type]

    def _record_mapping_change(self, source_id: str, offset: float, drift_ppm: float) -> None:
        """Record an offset/drift change against whatever it was before."""
        before = self._recorded_mappings.get(source_id, (0.0, 0.0))
        after = (offset, drift_ppm)
        if before == after:
            return
        self._recorded_mappings[source_id] = after
        self._supersede_alignment(source_id, before, after)
        if self._recording_suspended:
            return
        self._record(
            SetSourceMappingCommand(
                source_id=source_id,
                before=before,
                after=after,
                display_name=Path(source_id).name,
            )
        )

    def _record_marker_added(self, index: int) -> None:
        markers = self.annotation_store.markers
        if not 0 <= index < len(markers):
            return
        self._record(AddMarkerCommand(marker_record(markers[index], index)))

    def _record_marker_removed(self, index: int, marker: object) -> None:
        if not isinstance(marker, Marker):
            return
        # Hold the marker itself, not just its description: undo must restore
        # the same object, keeping its colour index and per-video frame
        # snapshots rather than building a lookalike.
        self._mutations.retain_removed(marker)
        self._record(RemoveMarkerCommand(marker_record(marker, index)))

    def _record_marker_relabelled(self, index: int, before: str, after: str) -> None:
        self._record(RelabelMarkerCommand(index=index, before=before, after=after))

    def _note_source_loaded(self, source_id: str, kind: str) -> None:
        """Record a source the user opened, or finish a restore.

        Called when a source actually lands, which is the only point that can
        tell a successful open from a requested one: a file that failed to open
        is not a change to the session, and undoing it would try to close a pane
        that never appeared.
        """
        if not self._session_restoring:
            self._record(AddSourceCommand(self._source_record(source_id, kind)))
            return
        if self._pending_video_loads or self._pending_imports:
            return
        # The restore has drained. Everything on the log describes the file that
        # was just opened, so the session is clean by definition.
        self._session_restoring = False
        self.document.clear()
        self._mark_session_saved()

    def _source_record(self, source_id: str, kind: str) -> SourceRecord:
        offset, drift_ppm = self._recorded_mappings.get(source_id, (0.0, 0.0))
        return SourceRecord(
            source_id=source_id,
            path=source_id,
            kind=kind,
            offset=offset,
            drift_ppm=drift_ppm,
        )

    # ── Session identity and dirty state ─────────────────────────────

    def _update_window_title(self) -> None:
        """Name the open session in the title bar, with Qt's modified marker.

        The title used to be the constant string "AvialSync", so two windows
        were indistinguishable in the taskbar and nothing showed that a session
        had unsaved changes. ``[*]`` is Qt's placeholder: it renders as the
        platform's own modified indicator when ``setWindowModified(True)`` and
        disappears otherwise, so this stays native on each OS rather than
        hardcoding an asterisk.
        """
        name = self._session_path.stem if self._session_path is not None else "Untitled"
        self.setWindowTitle(f"{name}[*] — AvialSync")
        self.setWindowModified(self.document.is_dirty)

    def _on_dirty_changed(self, dirty: bool) -> None:
        """Reflect a dirty transition in the title.

        The Document notifies only on a genuine clean/dirty transition, so this
        does not need a throttle of its own: a two-hundred-step offset drag is
        one merged command and at most one transition, which keeps the title
        repaint clear of the 8 ms UI-callback target (WP-1 step 6).
        """
        self.setWindowModified(dirty)

    def _mark_session_saved(self) -> None:
        """Record that the session on disk now matches the workspace."""
        self.document.session_path = str(self._session_path) if self._session_path else None
        self.document.mark_saved()
        self._update_window_title()

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

        act_fs = menu.addAction(tr("Fullscreen this camera"))
        act_snap = menu.addAction(tr("Snapshot this camera"))

        # Per-camera overrides, same labels as View -> Overlays. The menu sets
        # the default for every camera; this overrides one (D-090).
        menu.addSeparator()
        overlays_menu = menu.addMenu(tr("Overlays on this camera"))
        camera_actions: dict[QAction, str] = {}
        for layer in OVERLAY_LAYERS:
            if layer.locked or not layer.per_camera:
                continue
            act = overlays_menu.addAction(layer.label)
            act.setCheckable(True)
            act.setChecked(self.overlay_state.is_visible(layer.overlay_id, path))
            camera_actions[act] = layer.overlay_id
        overlays_menu.addSeparator()
        act_follow = overlays_menu.addAction(tr("Follow the View menu"))

        menu.addSeparator()
        act_props = menu.addAction(tr("Properties…"))
        act_copy = menu.addAction(tr("Copy frame info"))

        chosen = menu.exec(pos)
        if chosen in camera_actions:
            overlay_id = camera_actions[chosen]
            self._on_overlay_toggled(overlay_id, chosen.isChecked(), camera=path)
            return
        if chosen == act_follow:
            for layer in OVERLAY_LAYERS:
                self.overlay_state.clear_override(layer.overlay_id, path)
            self._apply_overlay_state()
            return
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

    def _open_project_url(self, label: str) -> None:
        """Open one of the project's declared URLs in the browser.

        Read from the installed metadata, never hardcoded here: they were
        repointed during the 0.1.6 cycle and a copy in this file would have
        gone stale without anything failing.
        """
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        url = project_urls().get(label)
        if url:
            QDesktopServices.openUrl(QUrl(url))
        else:
            self.notifications.show_warning(f"No {label} link is declared for this build.")

    def _report_a_problem(self) -> None:
        """Open the issue tracker with the version details already copied.

        A report without a version costs a round trip, and asking someone to
        find it themselves is how it gets left out.
        """
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(version_report())
            self.notifications.show_success("Version details copied — paste them into the report.")
        self._open_project_url("Issues")

    def _show_citation(self) -> None:
        """Show the citation the release process maintains."""
        show_text(
            self,
            tr("Cite AvialSync"),
            citation_text(),
            lead=tr("Citation metadata for this release:"),
        )

    def _show_preferences(self) -> None:
        """Open the generated Preferences dialog.

        Non-modal: a setting is often changed to see its effect, and a modal
        would hide the thing it changes.
        """
        from avialsync.ui.preferences_dialog import PreferencesDialog

        if getattr(self, "_preferences_dialog", None) is None:
            self._preferences_dialog = PreferencesDialog(self)
            self._preferences_dialog.setting_changed.connect(self._on_setting_changed)
        self._preferences_dialog.show()
        self._preferences_dialog.raise_()

    def _on_setting_changed(self, key: str) -> None:
        """Apply a preference immediately rather than at close."""
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        if key == "theme/preference":
            from avialsync.ui.theme import apply_theme, load_saved_theme

            apply_theme(app, load_saved_theme(app))
        elif key == "font/preference":
            from avialsync.ui.theme import apply_font_size, load_saved_font_size

            apply_font_size(app, load_saved_font_size(app))

    def _show_about(self) -> None:
        """Name the build, so a bug report can carry it."""
        show_text(
            self,
            tr("About AvialSync"),
            version_report(),
            lead=tr(
                "AvialSync — The Advanced Video and Instrument Alignment Library.\n"
                "Multi-camera video and time-series inspection.\n"
                "Free software under the GNU AGPL v3 or later."
            ),
        )

    # ── Shortcuts dialog ─────────────────────────────────────────────

    def _show_command_palette(self) -> None:
        """Search every registered command by name.

        Built from the same live QActions the shortcuts dialog uses (D-022.6),
        so it cannot list a command that does not exist or miss one that does.
        Registered actions without a shortcut are included too -- the menus have
        grown deep enough that finding a command is the problem, not typing it.
        """
        from avialsync.ui.command_palette import CommandPalette

        palette = CommandPalette(list(self._all_actions), self)
        palette.exec()

    def _show_shortcuts(self) -> None:
        from avialsync.ui.shortcuts_dialog import ShortcutsDialog

        # Group all registered QActions by category tag (D-022.6). Unbound
        # actions are included now that the dialog can assign a key: one with
        # no shortcut is exactly the one somebody wants to give a shortcut.
        groups: dict[str, list[QAction]] = {}
        for act in getattr(self, "_all_actions", []):
            if not act.text():
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

        # A scrolling dialog, not a message box: this report grows with the
        # number of loaded sources and plugins, and a QMessageBox sized itself
        # to the text until it ran off the screen with no way to scroll it. It
        # is also the text most worth pasting into a bug report, so the Copy
        # button that About had and this did not is now on both (D-107).
        show_text(self, tr("Diagnostics"), text)

    # ── Snapshot export ──────────────────────────────────────────────

    def _export_snapshot(self) -> None:
        export_controller.export_snapshot(self)

    def _start_snapshot_export(self, figure: SnapshotFigure, path: Path) -> None:
        export_controller.start_snapshot_export(self, figure, path)

    @Slot(str)
    def _on_snapshot_finished(self, path: str) -> None:
        export_controller.on_snapshot_finished(self, path)

    @Slot(str)
    def _on_snapshot_error(self, error: str) -> None:
        export_controller.on_snapshot_error(self, error)

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

    # ── Proxy generation ─────────────────────────────────────────────

    def _generate_proxy(self) -> None:
        if not self.video_grid._paths:
            self.notifications.show_warning(tr("Load a video before generating a proxy."))
            return

        from avialsync.engine.proxy import ProxyWorker

        # Proxy the first video for now
        video_path = Path(self.video_grid._paths[0])

        self._proxy_worker = ProxyWorker(video_path)

        # Proxy generation is minutes of transcoding. Behind a modal that was
        # minutes of unusable application, for work the user started so they
        # could keep looking at the session (D-091).
        self.activity_bar.begin(f"Generating proxy for {video_path.name}")
        self._active_cancel = self._proxy_worker.cancel

        def _wire(thread: QThread) -> None:
            worker = self._proxy_worker
            assert worker is not None
            self._proxy_thread = thread
            worker.progress.connect(self.activity_bar.set_progress)
            worker.finished.connect(self._on_proxy_finished)
            worker.error.connect(self._on_proxy_error)

        # Registered rather than hand-wired (D-107). `JobManager` connects
        # `started -> run` and quits the thread on `finished`/`error`, so this
        # no longer repeats those four lines — and a transcode that wedges is
        # now reported as not responding instead of merely looking busy.
        self._run_job(
            self._proxy_worker,
            label=f"Generating proxy for {video_path.name}",
            configure=_wire,
        )

    def _on_proxy_finished(self, orig: str, proxy: str) -> None:
        self.activity_bar.end()
        self._active_cancel = None
        self.notifications.show_success(f"Proxy ready: {Path(proxy).name}")

    def _on_proxy_error(self, err: str) -> None:
        self.activity_bar.end()
        self._active_cancel = None
        self.notifications.show_error("Could not generate the proxy", details=err)

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
        self._note_source_loaded(original_path, "video")
        self._refresh_empty_state()

    def _build_next_video_pane(self) -> None:
        video_controller.build_next_video_pane(self)

    def _apply_overlays_to_new_pane(self, path: str) -> None:
        """A camera opened after a layer was switched must not come up showing it."""
        self.video_grid.apply_overlays_to(path)

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
        _, drift = self._recorded_mappings.get(path, (0.0, 0.0))
        self._record_mapping_change(path, offset, drift)
        self.video_grid.set_offset(path, offset)
        if path in self._video_source_bounds:
            _, drift_ppm = self._video_time_mappings.get(path, (0.0, 0.0))
            self._set_video_coverage(path, self._video_source_bounds[path], offset, drift_ppm)
        self.clock.play()
        self.clock.pause()

    # ── Trigger evidence (WP-D) ──────────────────────────────────────

    def _open_trigger_evidence(self) -> None:
        """Load a trigger file and record what the user says its lines are."""
        from PySide6.QtWidgets import QFileDialog

        from avialsync.core.errors import FileUnreadableError

        chosen, _ = QFileDialog.getOpenFileName(
            self,
            tr("Open Trigger Evidence"),
            "",
            tr("Trigger and TTL files (*.csv *.tsv *.txt);;All files (*)"),
        )
        if not chosen:
            return
        path = Path(chosen)

        provider_cls = self._registry.trigger_for(path)
        if provider_cls is None:
            self.report_failure(
                FileUnreadableError(
                    f"Nothing installed can read {path.name} as trigger evidence. A "
                    "trigger file needs a time column and at least one logical line."
                )
            )
            return

        suggestions = provider_cls.suggest_trains(path)
        if not suggestions or not suggestions[0].get("trains"):
            self.report_failure(
                FileUnreadableError(
                    f"{path.name} has no columns that look like trigger lines. Trigger "
                    "evidence is a time column plus a line that goes high and low, or a "
                    "column of event timestamps."
                )
            )
            return

        from avialsync.ui.trigger_dialog import TriggerEvidenceDialog

        dialog = TriggerEvidenceDialog(
            path, suggestions[0], list(self.video_grid.pane_paths()), self
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        config = dialog.config()
        if not config["trains"]:
            self.notifications.show_warning(tr("No trigger lines were selected."))
            return
        self._start_trigger_read(provider_cls(), path, config)

    def _start_trigger_read(self, source: object, path: Path, config: dict[str, Any]) -> None:
        """Read the declared trains off the UI thread (architecture rule 3)."""
        from avialsync.core.errors import FileUnreadableError
        from avialsync.engine.trigger_worker import TriggerReadWorker

        worker = TriggerReadWorker(cast(Any, source), path, config)

        def configure(_thread: QThread) -> None:
            # Connected before the thread runs: a worker that finishes first
            # would otherwise emit into nothing (D-062).
            worker.finished.connect(
                lambda results: self._on_trigger_trains_read(str(path), results)
            )
            worker.error.connect(
                lambda message: self.report_failure(FileUnreadableError(f"{path.name}: {message}"))
            )

        self._run_job(worker, label=f"Reading triggers from {path.name}", configure=configure)

    @Slot(str, object)
    def _on_trigger_trains_read(self, path: str, results: object) -> None:
        """Register read trains as evidence the alignment wizard can offer."""
        if not isinstance(results, list):
            return
        self._trigger_trains[path] = list(results)
        drops = sum(len(getattr(train, "drops", ())) for train in results)
        summary = tr("{count} trigger train(s) from {name}").format(
            count=len(results), name=Path(path).name
        )
        if drops:
            # Said on arrival rather than discovered later: a train that skips
            # beats is the evidence that frames were lost, and it is the reason
            # an index-paired mapping would be wrong.
            summary = tr("{summary} — {drops} gap(s) in the pulses").format(
                summary=summary, drops=drops
            )
        self.notifications.show_success(summary)
        self._refresh_action_availability()

    def _source_coverage(self) -> list[SourceCoverage]:
        """Every loaded source's span, and how much of it evidence reaches.

        Answering "do these recordings overlap at all" before anything is
        fitted, which no residual can answer afterwards.
        """
        coverage: list[SourceCoverage] = []
        for path, bounds in self._video_source_bounds.items():
            offset, drift_ppm = self._video_time_mappings.get(path, (0.0, 0.0))
            mapping = TimeMap(offset, drift_ppm)
            coverage.append(
                SourceCoverage(
                    label=Path(path).name,
                    data=(mapping.to_master(bounds[0]), mapping.to_master(bounds[1])),
                    evidence=self._evidence_span(path),
                )
            )
        for path, cache_dir in self._sensor_cache_dirs.items():
            span = self.plot_pane.source_bounds(cache_dir)
            if span is None:
                continue
            coverage.append(
                SourceCoverage(
                    label=Path(path).name,
                    data=span,
                    evidence=self._evidence_span(path),
                )
            )
        return coverage

    def _evidence_span(self, path: str) -> tuple[float, float] | None:
        """First and last accepted sync point for *path*, or None.

        Superseded evidence is not a span: the source has been moved off it by
        hand, so nothing between those points is measured any more.
        """
        for entry in self._sync_provenance:
            if entry.target_id != path or entry.superseded_by or not entry.matches:
                continue
            times = [float(match["reference_time"]) for match in entry.matches]
            return (min(times), max(times))
        return None

    @Slot(str, float, float)
    def _on_video_mapping_changed(self, path: str, offset: float, drift_ppm: float) -> None:
        """Re-map one camera against the master clock, rate included.

        `_on_video_offset_changed` keeps whatever drift was already recorded,
        because a nudge is about position alone. This is the path that can
        change the rate, and it exists because a camera had no way to be given
        one by hand: the only route was an accepted fit, so a user watching a
        camera slip had to drift the *sensor* instead, moving it relative to
        every other camera at once.
        """
        _, previous_drift = self._recorded_mappings.get(path, (0.0, 0.0))
        if drift_ppm == previous_drift:
            return  # `_on_video_offset_changed` already handled the position.
        self._record_mapping_change(path, offset, drift_ppm)
        self.video_grid.set_sync_mapping(path, offset, drift_ppm, None, None)
        if path in self._video_source_bounds:
            self._set_video_coverage(path, self._video_source_bounds[path], offset, drift_ppm)
        self.player.seek(self.clock.state.t, exact=True)

    def _open_sync_wizard(self) -> None:
        """Open evidence-based TTL/frame-event alignment for loaded sources."""
        from avialsync.engine.sync_worker import (
            EventEvidenceSpec,
            EvidenceSpec,
            SignalEvidenceSpec,
        )
        from avialsync.ui.sync_wizard import SyncWizard

        references: list[EvidenceSpec] = [
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
        # Every loaded trigger train, on whichever side it belongs. A train the
        # user said is evidence *about* a video is a target; everything else is
        # a reference other sources can be fitted to.
        for file_path, trains in self._trigger_trains.items():
            for train in trains:
                spec = EventEvidenceSpec(f"{Path(file_path).name} : {train.train_id}", train.times)
                if train.target:
                    targets.append(spec)
                else:
                    references.append(spec)

        # A camera can be a reference too. Two cameras that saw the same trigger
        # had no path to each other before this: each had to be fitted to a
        # sensor separately, and a rig with no sensor at all could not align its
        # cameras even when their frame timestamps agreed perfectly. The fitter
        # already refuses a source against itself.
        references = references + list(targets)
        if not references or not targets:
            self.notifications.show_warning(
                tr(
                    "Load a TTL-bearing sensor channel, or a second video with frame "
                    "timestamps, before aligning."
                )
            )
            return

        wizard = SyncWizard(references, targets, self)
        wizard.set_coverage(self._source_coverage())
        if wizard.exec() == wizard.DialogCode.Accepted and wizard.proposal is not None:
            self._accept_sync_proposal(wizard.target_id, wizard.proposal)

    def _accept_sync_proposal(self, target_path: str, proposal: object) -> None:
        """Apply an explicitly accepted proposal and retain reproducible provenance."""
        from avialsync.core.sync import SyncProposal

        if not isinstance(proposal, SyncProposal) or not proposal.applicable:
            raise ValueError("Only an applicable synchronization proposal can be applied.")
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
            method=str(fit.method),
            reference_count=fit.reference_count,
            target_count=fit.target_count,
            offset_stderr=fit.offset_stderr,
            ambiguity_margin=fit.ambiguity_margin,
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
        previous_provenance = next(
            (item for item in self._sync_provenance if item.target_id == target_path), None
        )
        self._sync_provenance = [
            item for item in self._sync_provenance if item.target_id != target_path
        ]
        self._sync_provenance.append(provenance)
        # Acceptance stays explicit (architecture rule 8); recording it only
        # makes the accepted result reversible, so a user who takes the wrong
        # fit is not left reconstructing their previous mapping by hand.
        self._record(
            AcceptSyncCommand(
                source_id=target_path,
                before=self._recorded_mappings.get(target_path, (0.0, 0.0)),
                after=(fit.offset, fit.drift_ppm),
                evidence=provenance,
                before_evidence=previous_provenance,
            )
        )
        self._recorded_mappings[target_path] = (fit.offset, fit.drift_ppm)
        self.refresh_alignment_badges()
        self.transport.set_status(f"Aligned · {fit.describe()}", "info")
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
        self._record(RemoveSourceCommand(self._source_record(path, "video")))
        # Everything this window knows about the source is dropped before the
        # grid tears the pane down, because `remove_pane` writes the session on
        # the way past and that snapshot must describe the session the user
        # just asked for, not the one with this video still in it.
        self.sidebar.remove_video(path)
        self._video_frame_times.pop(path, None)
        self._overlay_sources.pop(path, None)
        self.overlay_state.forget_camera(path)
        self._sync_provenance = [
            entry for entry in self._sync_provenance if entry.target_id != path
        ]
        self.video_grid.remove_pane(path)
        self._refresh_empty_state()

    def _on_sensor_remove_requested(self, path: str) -> None:
        self._record(RemoveSourceCommand(self._source_record(path, "sensor")))
        cache_dir = self._sensor_cache_dirs.pop(path, None)
        if cache_dir is None:
            # Pre-import removal: fall back to the manager's derived location.
            from avialsync.core.cache import CacheManager

            cache_dir = CacheManager(loader_version=3).get_cache_dir(Path(path))
        self.plot_pane.remove_channels(cache_dir)
        self.sidebar.remove_sensor(path)
        self.message_store.remove_source(path)
        self.transport.set_source_coverage(path, 0.0, 0.0, "data")

    def _on_sensor_mapping_changed(self, path: str, offset: float, drift_ppm: float) -> None:
        """Re-align one time-series source against the master clock.

        This only changes the source's ``TimeMap`` — cached samples are never
        rewritten and no channel is re-imported (P3.5, mirrors video offsets).
        """
        cache_dir = self._sensor_cache_dirs.get(path)
        if cache_dir is None:
            return
        self._record_mapping_change(path, offset, drift_ppm)
        self.plot_pane.set_source_mapping(cache_dir, offset, drift_ppm)
        # A note moves with the samples it describes; leaving it behind would
        # put an experimenter's "stimulus on" beside the wrong trace.
        self.message_store.set_source_mapping(path, offset, drift_ppm)
        bounds = self.plot_pane.source_bounds(cache_dir)
        if bounds is not None:
            self.transport.set_source_coverage(
                path, bounds[0], bounds[1], "data", self.coverage_group_for(path)
            )
            self._update_bounds(bounds[0], bounds[1])
        self.readout_panel.set_cursor(self.clock.state.t)

    def _on_channel_remove_requested(self, path: str, channel: str) -> None:
        """Remove only this source's row — another file may use the same name."""
        self.plot_pane.remove_channel(ChannelKey(path, channel))

    def _on_channel_visibility_changed(self, path: str, channel: str, is_visible: bool) -> None:
        self._record(SetChannelVisibleCommand(source_id=path, channel=channel, visible=is_visible))
        self.plot_pane.set_channel_visible(ChannelKey(path, channel), is_visible)

    # ── Display levels (D-093) ───────────────────────────────────────

    def _focused_video_path(self) -> str | None:
        """The camera an action without an explicit target should act on.

        In order: the one shown fullscreen, then the one the user last touched,
        then -- only when there is exactly one -- that one.

        It deliberately does **not** fall back to the first of several. It used
        to, and with three cameras loaded that meant every nudge moved FaceCam
        whichever camera the user had in mind, silently. Returning None instead
        lets the caller say what it needs rather than acting on a guess.
        """
        paths = self.video_grid.pane_paths()
        if not paths:
            return None

        fullscreen = getattr(self.video_grid, "_fullscreen_pane", None)
        if fullscreen is not None:
            for path, pane in zip(paths, self.video_grid.panes, strict=False):
                if pane is fullscreen:
                    return path

        if self._selected_video_path in paths:
            return self._selected_video_path

        return paths[0] if len(paths) == 1 else None

    def _select_video(self, path: str) -> None:
        """Remember the camera the user just interacted with.

        Any interaction counts -- a click on the pane, its context menu, or a
        change to its offset -- because all of them mean "this one" as clearly
        as a selection gesture would, and none of them needed inventing.
        """
        if path in self.video_grid.pane_paths():
            self._selected_video_path = path
            self._on_source_format_detected(
                path, getattr(self._pane_for(path), "source_format", None)
            )

    def _pane_for(self, path: str) -> object | None:
        try:
            return self.video_grid.panes[self.video_grid.pane_paths().index(path)]
        except (ValueError, IndexError):
            return None

    def _on_source_format_detected(self, path: str, source_format: object) -> None:
        """Show or hide the levels panel according to what this file turned out to be."""
        if not isinstance(source_format, SourceFormat):
            return
        if path == self._focused_video_path():
            self.levels_panel.set_source_format(source_format)

    def _on_display_levels_changed(self, levels: object) -> None:
        if not isinstance(levels, DisplayLevels):
            return
        path = self._focused_video_path()
        if path is None:
            return
        self._display_levels[path] = levels
        self.video_grid.set_display_levels(path, levels)

    def _on_auto_levels_requested(self) -> None:
        """Choose black and white from the frame currently on screen."""
        path = self._focused_video_path()
        if path is None:
            return
        levels = self.video_grid.auto_display_levels(path)
        if levels is not None:
            self.levels_panel.set_levels(levels)
            self._on_display_levels_changed(levels)

    def _on_channel_group_visibility_changed(
        self, path: str, group_label: str, channels: list, visible: bool
    ) -> None:
        """Show or hide a whole group of channels as one undoable action.

        One command, not one per channel: hiding a group of forty is a single
        decision, and an undo history needing forty presses to reverse one
        click would be worse than no undo for it.
        """
        before = {
            str(channel): self.plot_pane.is_channel_visible(ChannelKey(path, str(channel)))
            for channel in channels
        }
        self._record(
            SetChannelGroupVisibleCommand(
                source_id=path,
                group_label=group_label,
                before=before,
                visible=visible,
            )
        )
        for channel in channels:
            self.plot_pane.set_channel_visible(ChannelKey(path, str(channel)), visible)

    def _on_plot_channel_close_requested(self, source_id: str, channel: str) -> None:
        """Route a plot-row close through the owning source's visibility checkbox."""
        self.sidebar.set_channel_visible(channel, False, source_id)

    def _on_video_visibility_changed(self, path: str, is_visible: bool) -> None:
        self._record(
            SetSourceVisibleCommand(
                source_id=path, visible=is_visible, display_name=Path(path).name
            )
        )
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
        # As with video, on success rather than on request.
        self._note_source_loaded(path, "sensor")
        self._refresh_empty_state()

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
