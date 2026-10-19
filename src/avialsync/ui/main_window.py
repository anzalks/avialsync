"""Main window for AvialSync."""

import dataclasses
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

import numpy as np
from PySide6.QtCore import QEvent, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMenu,
    QSplitter,
    QWidget,
)
from shiboken6 import isValid

from avialsync.core.channel_reader import ChannelKey
from avialsync.core.commands import (
    AddMarkerCommand,
    AddSourceCommand,
    RelabelMarkerCommand,
    RemoveMarkerCommand,
    ResetSessionCommand,
    SetOriginalTrackerVisibleCommand,
    SetSourceMappingCommand,
)
from avialsync.core.custom_markers import CustomMarkerStore
from avialsync.core.document import Document
from avialsync.core.identity_swaps import SwapGroup, SwapStore
from avialsync.core.inspection import SourceInspection
from avialsync.core.point_edits import PointEditStore
from avialsync.core.pose import PoseSchema
from avialsync.core.session import (
    SessionState,
    SyncProvenance,
    TriggerEntry,
)
from avialsync.core.source import ImagingSource, TimeSeriesSource, VideoSource
from avialsync.core.timeline import MasterClock, TimeMap
from avialsync.engine.display_pipeline import DisplayLevels, SourceFormat
from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.player import Player
from avialsync.engine.snapshot import SnapshotFigure
from avialsync.ui import (
    dandi_open,
    imaging_integration,
    recovery_worker,
    tracking_timing,
    video_levels,
    workspaces,
)
from avialsync.ui.accessibility import apply_accessibility, install_show_time_sweep
from avialsync.ui.annotations import AnnotationStore, Marker
from avialsync.ui.changes_panel import ChangesPanel
from avialsync.ui.controllers import (
    alignment_controller,
    appearance,
    artifact_write_controller,
    calibration_controller,
    changes_export_controller,
    corrections_controller,
    custom_marker_controller,
    drop_controller,
    export_controller,
    gap_view,
    identity_controller,
    identity_review,
    identity_view,
    import_controller,
    point_edit_controller,
    proxy_controller,
    session_controller,
    sources_controller,
    timebase,
    video_controller,
    wheel_controller,
    wheel_display,
    window_shortcuts,
    workspace_layout,
)
from avialsync.ui.controllers.import_state import ImportState
from avialsync.ui.controllers.rig_paths import RigPathsContext
from avialsync.ui.controllers.session_state import SessionRuntimeState
from avialsync.ui.controllers.timebase import SessionTimebase
from avialsync.ui.controllers.video_load_state import VideoLoadState
from avialsync.ui.controllers.wheel_state import WheelState
from avialsync.ui.controllers.window_feedback import WindowFeedback
from avialsync.ui.controllers.window_shortcuts import (
    _editor_rejects_text as _editor_rejects_text,
)
from avialsync.ui.coverage_lanes import SourceCoverage
from avialsync.ui.empty_state import EmptyState
from avialsync.ui.export_panel import ExportPanel
from avialsync.ui.feedback import ActivityBar, JobsPanel, NotificationStrip
from avialsync.ui.help_controller import HelpController
from avialsync.ui.i18n import tr
from avialsync.ui.identity_braid import BraidModel
from avialsync.ui.identity_model_worker import BraidBuildJob
from avialsync.ui.identity_panel import IdentityWindow
from avialsync.ui.inspector_dock import install_inspector_dock
from avialsync.ui.inspector_nav import InspectorNav
from avialsync.ui.job_manager import JobManager
from avialsync.ui.levels_panel import LevelsPanel
from avialsync.ui.menus import pane_menu
from avialsync.ui.menus import view as view_menu
from avialsync.ui.mutation_target import WindowMutationTarget, marker_record
from avialsync.ui.overlay_registry import OverlayState
from avialsync.ui.plot_pane import PlotPane
from avialsync.ui.props_app import PropsApp
from avialsync.ui.readout_panel import ReadoutPanel
from avialsync.ui.shortcut_overrides import apply_overrides
from avialsync.ui.source_records import anything_loaded, source_record
from avialsync.ui.time_format import TimeDisplayMode
from avialsync.ui.tracking_3d_pane import Tracking3DPane
from avialsync.ui.transport import Transport
from avialsync.ui.ui_heartbeat import UiHeartbeat
from avialsync.ui.undo_adapter import UndoActions
from avialsync.ui.video_grid import VideoGrid
from avialsync.ui.view_toolbar import ViewToolbar
from avialsync.ui.wheel_panel import WheelPanel
from avialsync.ui.wheel_tab import WheelTab

if TYPE_CHECKING:
    from avialsync.core.registry import LoaderRegistry
    from avialsync.ui.sync_wizard import SyncWizard

logger = logging.getLogger(__name__)


_AUTOSAVE_INTERVAL_MS = 120_000  # 2 minutes

#: Re-exported from the import controller, which owns the probe loop that
#: enforces it.  Kept here because this is the name the bound is known by.
_MAX_VIDEO_PROBES = video_controller.MAX_VIDEO_PROBES


class _JobWorker(Protocol):
    """A QObject with a run() slot, moved to a QThread by _run_job."""

    def run(self) -> None: ...
    def moveToThread(self, thread: QThread, /) -> bool: ...


class MainWindow(QMainWindow):
    _open_nwb = dandi_open.open_nwb
    _open_imaging = imaging_integration.open_dialog
    _on_imaging_remove_requested = imaging_integration.remove
    _rebuild_workspace_menu = workspaces.rebuild_menu
    _save_workspace = workspaces.save_current
    _apply_workspace = workspaces.apply_named
    _delete_workspace = workspaces.delete_one
    _on_imaging_mapping_changed = imaging_integration.change_mapping
    load_imaging = imaging_integration.load_imaging
    _source_record = source_record
    _anything_loaded = anything_loaded

    # Built by ui.menus. These are declared here so every caller sees their
    # types, while the live QAction remains the sole source of command text,
    # shortcut, and enablement.
    _act_open_video: QAction
    _act_open_sensor: QAction
    _act_open_imaging: QAction
    _act_open_nwb: QAction
    _act_save_session: QAction
    _act_reset_session: QAction
    _act_export_changes: QAction
    _act_delete_all_cache: QAction
    _act_snapshot: QAction
    _act_fix_tracker: QAction
    _act_fix_identities: QAction
    _act_add_marker: QAction
    _act_add_prop: QAction
    _act_synchronize: QAction
    _act_find_partner: QAction
    _act_show_original_tracker: QAction
    _act_detach_plots: QAction
    _act_panels_back: QAction
    _act_reset_zoom: QAction
    _act_fit_videos: QAction
    _act_collapse_gaps: QAction
    _act_fullscreen: QAction
    _act_review_workflow: QAction
    _act_first_session: QAction
    _act_shortcuts: QAction
    _recent_menu: QMenu
    _edit_menu: QMenu
    _align_menu: QMenu
    _overlays_menu: QMenu
    _workspace_menu: QMenu
    _undo_actions: UndoActions
    _overlay_actions: dict[str, QAction]
    _theme_group: QActionGroup
    _font_size_group: QActionGroup
    _time_mode_group: QActionGroup

    time_mode_changed = Signal(object)  # TimeDisplayMode

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.resize(*workspace_layout.first_window_size())
        self._detached_plot_window: QDialog | None = None
        self._plots_detached = False

        # Initialized before menu preconditions read the recovery offer.
        self.session_runtime = SessionRuntimeState()

        # The one place that knows whether this session has unsaved changes.
        # Dirty state, undo, and the autosave trigger all derive from
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
        #: The camera the user last touched, so an action with no explicit
        #: target acts on the one they meant rather than on the first pane.
        self._selected_video_path: str | None = None
        #: Which overlay layers show, globally and per camera. Nothing is
        #: drawn over a frame that the user cannot turn off.
        self.overlay_state = OverlayState()
        #: Hand corrections to tracked points. Sparse, and written
        #: beside each pose file the moment they are made; the pose files
        #: themselves and their caches are never written.
        self.point_edits = PointEditStore()
        self.point_edits.observe(self._on_point_edits_changed)
        #: Hand-placed 3D markers (Add 3D Marker), written beside the pose
        #: files like corrections; the calibration that triangulates them; and
        #: the placement in progress, if any.
        self.custom_markers = CustomMarkerStore()
        self.custom_markers.observe(self._on_custom_markers_changed)
        self._calibration_state: calibration_controller.CalibrationState | None = None
        self._marker_placement: custom_marker_controller.MarkerPlacement | None = None
        self._announced_marker_files = False
        #: Wheels placed through Props, the one being placed, the one
        #: whose encoder the next click checks, and what drawing them needs:
        #: bars per frame, encoder readers, and the session's own hint.
        self.wheel_state = WheelState()
        self.props_app = PropsApp(self)
        self.wheels = self.props_app.wheels
        self.wheels.observe(self._on_wheels_changed)
        #: One callable, so the grid can tell "no wheel" from "same wheel source".
        self.wheel_state.pane_source = lambda path, t: wheel_display.pane_drawing(self, path, t)
        #: Accepted identity swaps: which lanes exchanged labels and
        #: from which frame. Like corrections, written beside the pose file the
        #: moment they are accepted; unlike corrections, applied by rebuilding
        #: the source's cached channels, so every consumer reads the edited
        #: tracker rather than each one applying the swap for itself.
        self.identity_swaps = SwapStore()
        self.identity_swaps.observe(self._on_identity_swaps_changed)
        self._show_original_tracker = False
        #: What each imported pose source is: its declared structure, where it
        #: was imported to, and which edited generation its readers are on.
        self._pose_schemas: dict[str, PoseSchema] = {}
        self._pose_cache_dirs: dict[str, Path] = {}
        self._edited_generations: dict[str, Any] = {}
        self._swap_storage: dict[str, str] = {}
        self._expected_swap_counts: dict[str, int] = {}
        self._expected_swap_groups: dict[str, tuple[SwapGroup, ...]] = {}
        self._announced_swap_files: set[str] = set()
        #: Pose sources already reported as drawn on assumed timing, so a
        #: retry on the next video load does not repeat itself.
        self._announced_uncalibrated_overlays: set[str] = set()
        #: What a scan proposed, keyed by (source, group, part). Proposals, not
        #: edits: nothing here changes what is drawn until a person accepts it.
        self._swap_candidates: dict[tuple[str, str, str], tuple[Any, ...]] = {}
        #: Cached edit programs, so the overlay can ask which column a label is
        #: showing on every paint. Dropped whenever the flips change.
        self._identity_routes: dict[str, Any] = {}
        self._identity_window: IdentityWindow | None = None
        self._identity_request_serial = 0
        self._pending_identity_model: tuple[int, BraidBuildJob] | None = None
        self._identity_model_timer = QTimer(self)
        self._identity_model_timer.setSingleShot(True)
        self._identity_model_timer.timeout.connect(self._start_identity_model_job)
        #: Where each source's corrections went. "session" only ever means
        #: writing beside the pose file failed, never a preference.
        self._point_edit_storage: dict[str, str] = {}
        #: What a restored session said each source should have, checked as that
        #: source imports so a missing sidecar is reported rather than silent.
        self._expected_correction_counts: dict[str, int] = {}
        #: Sources whose storage has already been reported, so a read-only
        #: volume does not raise the same strip on every drag.
        self._announced_correction_files: set[str] = set()

        # The feedback surface. JobManager already knew all of this;
        # none of it reached the user.
        self.activity_bar = ActivityBar(self)
        self.activity_bar.cancel_requested.connect(self._cancel_active_task)
        self.notifications = NotificationStrip(self)
        self.notifications.details_requested.connect(self._show_task_details)
        self.jobs_panel = JobsPanel(self)

        # Display levels, offered only for footage that has range to choose
        # from -- the panel asks the decoder what the recording actually is
        # rather than assuming a depth.
        self.levels_panel = LevelsPanel(self)
        self.levels_panel.levels_changed.connect(self._on_display_levels_changed)
        self.levels_panel.auto_requested.connect(self._on_auto_levels_requested)
        #: Per-source display window, keyed by path.
        self._display_levels: dict[str, DisplayLevels] = {}

        self._update_window_title()

        # Populated by the menu builders from the live QAction objects.
        self._all_actions: list[QAction] = []
        self._inspector_actions: list[QAction] = []
        self._letter_shortcuts: set[str] = set()
        self._action_preconditions: list[tuple[QAction, Callable[[], bool], str, str]] = []

        # fps of each loaded video (str(path) → fps); used for frame-indexed source resolution
        self._video_fps: dict[str, float] = {}
        # JobManager owns the workers; this state only tracks probe capacity
        # and preserves pane order when probes complete out of order.
        self.video_load_state = VideoLoadState()
        self._video_frame_times: dict[str, Any] = {}
        self._video_source_bounds: dict[str, tuple[float, float]] = {}
        self._video_time_mappings: dict[str, tuple[float, float]] = {}
        self._sync_provenance: list[SyncProvenance] = []
        # Master zero's placements and the time display mode (controllers/timebase.py).
        self.timebase = SessionTimebase()
        #: Trigger trains the user has loaded and typed, by file path. Evidence
        #: for the alignment wizard, not data: nothing here is ever plotted.
        self._trigger_trains: dict[str, list[Any]] = {}
        self._trigger_time_maps: dict[str, TimeMap] = {}
        #: The configuration each trigger file was read with, by path. Saved in
        #: the session; the trains themselves are re-read from it on restore.
        self._trigger_configs: dict[str, dict[str, Any]] = {}
        #: The alignment wizard while it is open. Non-modal, so the window has
        #: to own it -- see `_open_sync_wizard`.
        self._sync_wizard: SyncWizard | None = None
        self._pending_exact_mappings: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._overview_gaps: dict[float, str] = {}
        # DLC/frame-indexed sources loaded without a video present (path, provisional_fps)
        self._frame_indexed_sources: list[tuple[Path, type, dict[str, Any]]] = []
        self.import_state = ImportState()
        # Modal progress for the running import. Declared here rather than
        # created by the import starter: the finish and error handlers both
        # read it, and a window that has never imported must still answer.
        #: Cancel callback for whatever the activity bar is currently showing.
        #: Legacy workers are not registered with JobManager, so the bar needs
        #: its own handle to stop them.
        self._active_cancel: Callable[[], None] | None = None
        # Pose sources are shown on the video overlay and in the 3D view rather
        # than as plot rows. Keyed by video path -> source path -> track.
        self._overlay_sources: dict[str, dict[str, dict[str, Any]]] = {}
        self._pose_3d_sources: dict[str, list[Any]] = {}
        #: Per-pose-source presentation choices.  A role decides *where* a
        #: source can go; these choices decide whether it currently does.
        self._tracking_visibility: dict[str, dict[str, bool]] = {}
        #: Imported tracking cache details, retained so Show plot can add rows
        #: lazily without re-reading the source file.
        self._tracking_plot_sources: dict[str, tuple[Path, list[str], float, float]] = {}
        #: Session restore reaches the import completion asynchronously.
        self._pending_tracking_visibility: dict[str, dict[str, bool]] = {}
        self._plotted_readers: list[Any] = []
        self._region_stats_request = 0
        # Inspection data keyed by str(path)
        self._inspections: dict[str, SourceInspection] = {}
        # Units dict keyed by channel_id; populated from import config or wizard
        self._channel_units: dict[ChannelKey, str] = {}
        # Sensor source path → its cache entry, so an offset edit can find
        # the plot rows it owns without walking every channel.
        self._sensor_cache_dirs: dict[str, Path] = {}
        # Sources whose plot rows are still being built; their exact reader-derived
        # bounds are applied when PlotPane reports the load complete.
        self._pending_bounds_sources: dict[str, Path] = {}
        # Accepted mappings restored from a session, applied once their
        # asynchronous import reports back.
        self._pending_sensor_mappings: dict[str, tuple[float, float]] = {}
        self._pending_channel_visibility: dict[str, dict[str, bool]] = {}
        self._save_in_progress = False
        # One owner for background work: names it for the status bar, watches it
        # for stalls, and abandons it at shutdown so the window always closes.
        self._job_manager = JobManager(self)
        self._job_manager.jobs_changed.connect(self._on_jobs_changed)
        # A job too brief to be shown ends without `jobs_changed`; what waits for
        # idle (the cache commands) is re-answered on every start and end.
        self._job_manager.membership_changed.connect(self._refresh_action_availability)
        self.artifact_writes = artifact_write_controller.ArtifactWriteQueue(self)
        # Off-thread work is only half the guarantee; this notices when the UI
        # thread blocks anyway and says so instead of just feeling laggy.
        self._heartbeat = UiHeartbeat(self)
        self._heartbeat.stalled.connect(self._on_ui_stalled)
        # Core
        self.clock = MasterClock()

        # UI Components
        self.video_grid = VideoGrid(self)
        self.rig_paths = RigPathsContext(
            video_paths=lambda: list(self.video_grid.pane_paths()),
            pose_sources=self._pose_3d_sources,
            overlays=self._overlay_sources,
            calibrated_videos=lambda: (
                self._calibration_state.cameras.keys() if self._calibration_state else ()
            ),
            frame_index=lambda index, t: int(self.video_grid.panes[index].frame_record_at(t)[0]),
        )
        self.video_grid.set_point_edits(self.point_edits)
        # What a marker is *drawing* once a flip is accepted. Installed
        # here, beside the store it belongs with, so a pane created later gets
        # both from the same place.
        self.video_grid.set_identity_resolver(
            lambda source_id, name, index: identity_controller.data_point_for(
                self, source_id, name, index
            )
        )
        self.video_grid.point_moved.connect(self._on_tracked_point_moved)
        self.video_grid.marker_clicked.connect(self._on_marker_clicked)
        self.video_grid.custom_point_moved.connect(
            lambda path, name, frame, x, y: custom_marker_controller.on_moved(
                self, path, name, frame, x, y
            )
        )
        self.tracking_3d_pane = Tracking3DPane(self)
        self.imaging_pane, self.imaging_splitter, self._imaging_visibility_filter = (
            imaging_integration.install(self, self.tracking_3d_pane)
        )
        self.imaging_pending: set[str] = set()
        self.tracking_3d_pane.canvas.set_custom_point_source(
            lambda t: custom_marker_controller.points_at(self, t)
        )
        self.video_grid.set_reprojection_source(
            lambda path, t: calibration_controller.reprojected(self, path, t)
        )
        self.tracking_3d_pane.canvas.set_wheel_source(lambda t: wheel_display.scene(self, t))
        self.tracking_3d_pane.canvas.set_prop_source(self.props_app.scene_steps)
        self.plot_pane = PlotPane(self)
        self.transport = Transport(self)
        self.data_streams = self.transport.detach_data_streams()
        self.view_toolbar = ViewToolbar(self)
        self.plot_pane.view_window_changed.connect(self.transport.set_plot_viewport)
        self.plot_pane.seek_requested.connect(self._on_plot_seek_requested)

        # Engine
        from avialsync.ui.controllers.plugin_controller import new_registry

        self._registry = new_registry()
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
            imaging_pane=self.imaging_pane,
        )
        self.player.step_reference = self._step_reference_pane
        gap_view.install(self)  # D-218

        # Annotations
        self.annotation_store = AnnotationStore(self)
        self.annotation_store.changed.connect(self._update_timeline_annotations)
        # Export Changes is available exactly when one of these has something
        # in it, so both drive the availability pass.
        self.annotation_store.changed.connect(self._refresh_action_availability)
        self.annotation_store.marker_added.connect(self._record_marker_added)
        self.annotation_store.marker_removed.connect(self._record_marker_removed)
        self.annotation_store.marker_relabelled.connect(self._record_marker_relabelled)

        # Layout
        from avialsync.ui.sidebar import SidebarPane

        self.sidebar = SidebarPane(self)
        self.wheel_panel = WheelPanel()
        self.wheel_tab = WheelTab(self.wheel_panel, self, scrollable=False)
        wheel_controller.connect_panel(self)
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
        imaging_integration.connect_sidebar(self)
        self.sidebar.sensor_remove_requested.connect(self._on_sensor_remove_requested)
        self.sidebar.sensor_mapping_changed.connect(self._on_sensor_mapping_changed)
        self.sidebar.channel_remove_requested.connect(self._on_channel_remove_requested)
        self.sidebar.channel_visibility_changed.connect(self._on_channel_visibility_changed)
        self.sidebar.channel_group_visibility_changed.connect(
            self._on_channel_group_visibility_changed
        )
        self.sidebar.tracking_visibility_changed.connect(self._on_tracking_visibility_changed)
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
        self.plot_pane.sources_changed.connect(self._set_plotted_tracking_readers)
        self.plot_pane.measure_changed.connect(self._on_measure_changed)
        self.player._readout_panel = self.readout_panel

        # Annotation panel
        self.changes_panel = ChangesPanel(
            self.annotation_store, self.point_edits, self.identity_swaps, self
        )
        self.changes_panel.set_correction_resolver(self._locate_correction)
        self.changes_panel.revisit_requested.connect(self._revisit_change)
        self.changes_panel.delete_correction_requested.connect(self._restore_predicted_point)
        self.changes_panel.delete_swap_requested.connect(
            lambda source_id, event: identity_view.undo(self, source_id, event)
        )
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
        # A rail rather than tabs, so no page name elides. Tasks is not
        # a page: it opens from the status bar, beside the activity it lists.
        self._left_tabs = InspectorNav(self)
        self._left_tabs.setAccessibleName(tr("Inspector"))
        self._left_tabs.addTab(self.sidebar, tr("Sources"), icon="sources")
        self._left_tabs.addTab(self.readout_panel, tr("Values"), icon="values")
        self._left_tabs.addTab(self.message_panel, tr("Messages"), icon="messages")
        self._left_tabs.addTab(self.changes_panel, tr("Changes"), icon="changes")
        self._left_tabs.addTab(self.props_app.make_panel(self.wheel_tab), tr("Props"), icon="props")
        self.export_panel = ExportPanel(self)
        self._left_tabs.addTab(self.export_panel, tr("Exports"), icon="exports")
        # Display levels live under Sources, beside the camera they act on.
        # Hidden until a recording that has range to choose from is opened.
        self.sidebar.content_layout.addWidget(self.levels_panel)
        # A dock, not a splitter pane: either side, floating, or closed.
        self.inspector_dock = install_inspector_dock(self, self._left_tabs)
        self._workspace = workspace_layout.create_workspace(
            self,
            workspace_layout.WorkspaceParts(
                inspector=self._left_tabs,
                videos=self.video_grid,
                tracking=self.tracking_3d_pane,
                imaging=self.imaging_pane,
                imaging_splitter=self.imaging_splitter,
                plots=self.plot_pane,
                video_tools=self.view_toolbar,
                streams=self.data_streams,
                transport=self.transport,
                notifications=self.notifications,
            ),
        )
        # Compatibility handles refer to the same objects; geometry state is
        # owned solely by the composed workspace and its proportion store.
        self._media_splitter = self._workspace.media
        self._video_column = self._workspace.video_column
        self._v_splitter = self._workspace.vertical
        self._content_splitter = self._workspace.content
        self._pane_proportions = self._workspace.proportions
        self._pane_resize_timer = self._workspace.resize_timer
        self._enforce_splitter_policy()
        self._apply_default_splitter_sizes()
        self._workspace.mount()
        central_widget = self._workspace.central_widget
        right_widget = self._workspace.right_widget

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
        # window, so dialogs keep their own editing keys.
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.installEventFilter(self)

        self._help_controller = HelpController(self)

        # Menu
        self._setup_menu()

        # Feedback surface: activity in the status bar, outcomes in the strip.
        self._install_feedback_surface()

        # Empty state, over the video area until a recording is opened. Its
        # layout waits for the saved one to be restored first, so the
        # layout kept for later is the user's, not the defaults.
        self._empty_layout_saved: dict[QSplitter, tuple[float, ...] | None] | None = None
        self._empty_layout_ready = False
        self._install_empty_state()

        # Drag and Drop
        self.setAcceptDrops(True)

        # Restore geometry
        self._restore_geometry()
        self._empty_layout_ready = True
        self._refresh_empty_state()

        # Transport signals
        self.transport.ab_loop_changed.connect(self._on_ab_loop_changed)
        self.view_toolbar.flag_requested.connect(self._on_annotate_requested)
        self.transport.jump_requested.connect(self._on_jump_requested)

        # Camera selection and the picture’s context menu.
        self.video_grid.pane_activated.connect(self._select_video)
        self.video_grid.pane_right_clicked.connect(self._on_pane_right_clicked)

        # Plot annotate-at
        self.plot_pane.annotate_at_requested.connect(self._on_annotate_at_requested)

        # One window-owned timer clears the revisit ring. Owned here, not by a
        # pane: a timer that outlives the widget it repaints is a SIGSEGV with
        # no traceback, and the window outlives every pane.
        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.timeout.connect(self._clear_point_highlight)

        # Autosave timer
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start(_AUTOSAVE_INTERVAL_MS)

        # Startup diagnostics (deferred so window shows first)
        QTimer.singleShot(500, self, self._run_diagnostics)

        # Unsaved work from a previous run is read once by a worker and held, which is
        # what enables File → Recover Unsaved Work. The notification bar on top
        # of that is opt-in and off by default, so a launch is quiet unless the
        # user asked to be told.
        recovery_worker.start_recovery_check(self)

        # Start player tick
        self.player.start()

        # Setup global shortcuts (must come after _setup_menu so _all_actions exists)
        self._setup_shortcuts()

        # User rebindings, layered over the defaults just established. Applied
        # last so a stored choice wins, and after the defaults are recorded so
        # Reset has something to restore.
        apply_overrides(list(self._all_actions))

        # Name anything interactive that has not named itself. A sweep rather
        # than ninety manual calls, because the ninety-first widget is the one
        # that gets added without one.
        #
        # This pass covers the chrome only: the application starts empty, so
        # there are no video panes, plot rows, source entries or quality badges
        # here to name yet. `_sweep_accessibility` runs again as those appear,
        # and `install_show_time_sweep` catches every dialog when it is shown.
        apply_accessibility(self)
        app = QApplication.instance()
        if app is not None:
            #: Kept as an attribute, not a local: an event filter with no live
            #: Python reference is collected while Qt still holds a pointer to
            #: it.
            self._show_time_sweeper = install_show_time_sweep(app)
        # Don't count window construction as an event-loop stall. The timer is
        # useful only once every widget and startup action has been installed.
        self._heartbeat.start()

    # ── Background job lifetime ──────────────────────────────────────

    def _run_job(
        self,
        worker: _JobWorker,
        label: str = "Working",
        configure: Callable[[QThread], None] | None = None,
        *,
        announce_after_s: float = 0.0,
    ) -> QThread:
        """Own a worker/thread pair for the whole life of a background job.

        Delegates to :class:`JobManager`, which additionally names the job for
        the status bar, watches it for stalls, and can abandon it at shutdown so
        the window always closes.

        Connect result signals in *configure*, never after this returns: the
        thread is already running by then, and a worker that finishes first
        emits into nothing and the work is silently a no-op.
        """
        if announce_after_s:
            return self._job_manager.start(
                label, worker, configure=configure, announce_after_s=announce_after_s
            )
        return self._job_manager.start(label, worker, configure=configure)

    def _install_empty_state(self) -> None:
        """Put the empty state over the video area until something is loaded."""
        self.empty_state = EmptyState(self)
        self.empty_state.install_open_actions(self._act_open_video, self._act_open_sensor)
        self.empty_state.demo_requested.connect(self._launch_demo)
        self.video_grid.set_empty_widget(self.empty_state)
        self._refresh_empty_state()

    # ── Action availability ──────────────────────────────────

    def _has_alignment_evidence(self) -> bool:
        """Whether both halves of a TTL/event fit are present.

        The same rule the wizard uses to build its offer, so the menu item and
        the command agree about availability rather than the command
        discovering it a click later.
        """
        from avialsync.ui.sync_acceptance import has_alignment_evidence

        return has_alignment_evidence(self)

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
        """Name the widgets that were built after the window was.

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
        nothing_loaded = not self._anything_loaded()
        empty_state.setVisible(nothing_loaded)
        self.video_grid.refresh_empty()
        if self._empty_layout_ready:
            self._apply_empty_layout(nothing_loaded)
        # The grid's floor stays where `VideoGrid` set it, in every state. It
        # was raised to the empty state's own minimum here for one commit, so
        # five stacked controls would stop drawing as 2 px slivers; that made
        # the whole window unable to shrink below ~505 px tall and took the
        # 640x480 workspace guarantee with it. `EmptyState` scrolls instead, so
        # it survives a short video area without dictating a window minimum.

    def _apply_empty_layout(self, empty: bool) -> None:
        """Retain the existing window-owned saved layout for persistence."""
        self._empty_layout_saved = self._workspace.apply_empty(empty, self._empty_layout_saved)

    def _launch_demo(self) -> None:
        """Generate and open the sample session.

        The generator already exists and is what `avialsync demo` runs; it was
        simply unreachable from inside the application. It writes files and
        encodes video, so it goes through the activity bar like any other long
        job rather than blocking the window.
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
        """Compose feedback from the existing job owner and live widgets."""
        self._feedback = WindowFeedback(
            self,
            self._job_manager,
            self.transport,
            self.activity_bar,
            self.notifications,
            self.jobs_panel,
        )
        self.cache_indicator, self.tasks_button = self._feedback.install_status(
            self._run_job,
            self._act_delete_all_cache,
        )

    def _cancel_active_task(self) -> None:
        """Retain the single active-cancel callback on the window."""
        self._feedback.cancel_active_task(self._active_cancel)
        self._active_cancel = None

    def _show_task_details(self, details: str) -> None:
        """Keep requested details on this window's Qt receiver."""
        self._feedback.show_task_details(details)

    def report_failure(self, error: BaseException, *, doing: str = "") -> None:
        """Present a failure through the composed feedback surface."""
        self._feedback.report_failure(error, doing=doing)

    def _refresh_jobs_panel(self) -> None:
        self._feedback.refresh_jobs_panel()

    def _on_jobs_changed(self) -> None:
        """Keep queued delivery and instance-level hooks on the real window."""
        self._feedback.jobs_changed(self._refresh_action_availability, self._refresh_jobs_panel)

    def _on_ui_stalled(self, milliseconds: float) -> None:
        self._feedback.ui_stalled(milliseconds)

    # ── Sources / units ──────────────────────────────────────────────

    def _splitters(self) -> tuple[QSplitter, ...]:
        return self._workspace.splitters()

    def _enforce_splitter_policy(self) -> None:
        """Reapply the workspace policy after Qt restores saved state."""
        self._workspace.enforce_policy()

    def _repair_collapsed_panes(self) -> None:
        """Keep the window's live default-layout hook available to repairs."""
        self._workspace.repair_collapsed(self._apply_default_splitter_sizes)

    def _apply_default_splitter_sizes(self) -> None:
        """Seed ratios through the workspace's single proportion owner."""
        self._workspace.apply_defaults(self, self.inspector_dock, self._left_tabs)

    def source_readers(self, source_id: str) -> list[Any]:
        """Every channel reader of one source: its plot rows, then its 3D pose readers."""
        rows = [c.reader for c in self.plot_pane.channels if c.reader.source_id == source_id]
        return rows + list(self._pose_3d_sources.get(source_id, ()))

    def coverage_group_for(self, path: str) -> str:
        """Return the shared Data Streams lane *path* belongs in, if any.

        Empty for anything the current session did not group, which is every
        ordinary drop: a file with a span of its own keeps a lane of its own.
        """
        return self.session_runtime.coverage_groups.get(path, "")

    def _refine_source_bounds(self) -> None:
        """Apply exact reader-derived bounds once every queued row exists.

        Rows are built across several event-loop turns so a large selection does
        not freeze the window. Until they exist, `_on_import_finished`
        uses the import worker's bounds; this replaces them with the mapped span
        the readers actually cover, which differs whenever a source carries an
        offset or drift.
        """
        for path, cache_dir in list(self._pending_bounds_sources.items()):
            span = self.plot_pane.source_bounds(cache_dir)
            if span is None:
                continue
            self._pending_bounds_sources.pop(path, None)
            inspection = self._inspections.get(path)
            if inspection is not None:
                inspection.release_cache_pin()
            self.transport.set_source_coverage(
                path, span[0], span[1], "data", self.coverage_group_for(path)
            )
            self._recompute_bounds()

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

    def _set_plotted_tracking_readers(self, readers: list[Any]) -> None:
        """Forward loose plotted XY readers without duplicating routed pose overlays.

        A routed 2D source can now be plotted on request.  Its plot rows must
        not take the legacy loose-reader route, which broadcasts points to
        every camera and would bypass its source's Show overlay checkbox.
        """
        routed = set(self._tracking_visibility)
        self.video_grid.set_tracking_readers(
            [reader for reader in readers if getattr(reader, "source_id", "") not in routed]
        )

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
        """What this camera is -- resolution, depth, codec, rates -- and its import report."""
        self._show_source_properties(path, tr("Video Properties — {name}"))

    def _show_sensor_properties(self, path: str) -> None:
        self._show_source_properties(path, tr("Sensor Properties — {name}"))

    def _show_source_properties(self, path: str, title: str) -> None:
        """Properties first, then the import report; shown even when no report exists."""
        from avialsync.ui.import_report import ImportReportDialog

        properties = self.sidebar.properties_text(path)
        ins = self._inspections.get(path)
        if not properties and ins is None:
            return
        name = Path(path).name
        ImportReportDialog(ins, self, properties=properties, title=title.format(name=name)).exec()

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

    # ── Time display mode and session placement (controllers/timebase.py) ──

    @property
    def session_start_time(self) -> float:
        """Unix epoch of master-clock zero, or 0.0 when the session has no wall clock."""
        return self.session_runtime.start_time

    def adopt_session_start(self, source_start: float) -> float:
        return timebase.adopt_session_start(self, source_start)

    def declare_base_offset(
        self, source_id: str, source_start: float, source_epoch: float | None = None
    ) -> float:
        return timebase.declare_base_offset(self, source_id, source_start, source_epoch)

    @property
    def registry(self) -> "LoaderRegistry":
        """The window's loader registry; the drop worker discovers it off the UI thread."""
        return self._registry

    def base_offset(self, source_id: str) -> float:
        """The session placement for *source_id*, or 0.0 for a relative source."""
        return self.timebase.base_offsets.get(source_id, 0.0)

    def video_master_spans(self) -> dict[str, tuple[float, float]]:
        """Each loaded video's first and last frame on the master clock.

        Bounds are kept in source time; ``t_source = t_master + offset`` puts
        them on the master clock through the video's effective offset.
        """
        spans: dict[str, tuple[float, float]] = {}
        for path, (start, end) in self._video_source_bounds.items():
            offset, _drift = self._video_time_mappings.get(path, (self.base_offset(path), 0.0))
            spans[path] = (start - offset, end - offset)
        return spans

    def effective_offset(self, source_id: str, user_offset: float) -> float:
        return timebase.effective_offset(self, source_id, user_offset)

    def user_offset(self, source_id: str, effective: float) -> float:
        return timebase.user_offset(self, source_id, effective)

    def _publish_session_epoch(self) -> None:
        timebase.publish_session_epoch(self)

    def show_trial_segments(self, segments: list[tuple[float, float, str]]) -> None:
        timebase.show_trial_segments(self, segments)

    def _draw_trial_segments(self) -> None:
        timebase.draw_trial_segments(self)

    def forget_session_start(self) -> None:
        timebase.forget_session_start(self)

    def _set_time_mode(self, mode: TimeDisplayMode) -> None:
        timebase.set_time_mode(self, mode)

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
        -- so it is captured here, before the clear.
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

    def _recover_unsaved_work(self) -> None:
        session_controller.recover_unsaved_work(self)

    def _autosave_before_close(self) -> None:
        session_controller.autosave_before_close(self)

    def _write_session_snapshot(self, _path: str = "") -> None:
        session_controller.write_session_snapshot(self)

    # ── A/B loop stats ───────────────────────────────────────────────

    def _on_ab_loop_changed(self, t_in: float | None, t_out: float | None) -> None:
        # Export Trimmed Video Clip needs a loop, so its availability changes
        # here and nowhere else.
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
        """Build keyboard actions from explicitly supplied live components."""
        window_shortcuts.KeyboardActions(
            window_shortcuts.KeyboardContext(
                owner=self,
                actions=self._all_actions,
                letters=self._letter_shortcuts,
                clock=self.clock,
                player=self.player,
                transport=self.transport,
                plots=self.plot_pane,
                annotate=self._on_annotate_requested,
                cycle_theme=self._cycle_theme,
                show_shortcuts=self._show_shortcuts,
            )
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

        # Ordering matters twice over.
        #
        # State is captured before anything is torn down: `_build_session_state`
        # reads `video_grid.panes`, and `video_grid.shutdown()` clears them, so
        # running the autosave afterwards wrote a session with zero videos and
        # silently discarded the user's video list on every close.
        #
        # Decoder teardown goes last, and every step is isolated. Each pane owns
        # an event thread that outlives its widget, so a step that raises must
        # not skip the ones after it: that leaves those threads running and the
        # process never exits, which is the "window won't close" the user sees.
        self._close_step("releasing the application event filter", self._remove_app_event_filter)
        self._close_step(
            "re-attaching the detached plot pane",
            lambda: self._act_detach_plots.setChecked(False),
        )
        self._close_step("cancelling queued plot rows", self.plot_pane.shutdown)
        self._close_step("stopping the heartbeat", self._heartbeat.stop)
        self._close_step("stopping playback", self.player.stop)
        self._close_step("saving window geometry", self._save_geometry)
        self._close_step("writing the final autosave", self._autosave_before_close)
        self._close_step("stopping background jobs", self._job_manager.shutdown)
        self._close_step("releasing pending cache deliveries", self._release_import_deliveries)
        self._close_step("shutting down video panes", self.video_grid.shutdown)
        self._close_step("shutting down imaging pane", self.imaging_pane.shutdown)
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

    def _release_import_deliveries(self) -> None:
        """Release worker handoffs whose plot rows never finished building."""
        for inspection in self._inspections.values():
            inspection.release_cache_pin()

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
        """Keep Qt shortcut delivery on this window's real event receiver."""
        return window_shortcuts.reserve_playhead_key(self, event)

    def _reserve_letter_shortcut(self, event: QEvent) -> bool:
        """Delegate focus policy with the actual registered letter shortcuts."""
        return window_shortcuts.reserve_letter_shortcut(self, self._letter_shortcuts, event)

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
        loader_cls: type[TimeSeriesSource | VideoSource | ImagingSource],
        config: dict | None = None,
    ) -> None:
        drop_controller.route_import_candidate(self, path, loader_cls, config)

    def _process_drop_candidates(
        self, candidates: list[tuple[Path, type | None, dict | None]]
    ) -> None:
        drop_controller.process_drop_candidates(self, candidates)

    # ── Menu ─────────────────────────────────────────────────────────

    def _setup_menu(self) -> None:
        """Build menus from live actions, keeping action identity in one place."""
        from avialsync.ui.menus.builder import build_menus

        build_menus(self)

    # ── Alignment ────────────────────────────────────────────

    def _nudge_alignment(self, direction: int) -> None:
        alignment_controller.nudge_alignment(self, direction)

    def _supersede_alignment(
        self, source_id: str, before: tuple[float, float], after: tuple[float, float]
    ) -> None:
        """Annotate changed evidence and every dependent clock for review."""
        from avialsync.ui.sync_lifecycle import invalidate

        invalidate(self, source_id, after[0] - before[0])

    def accepted_alignment_records(self) -> tuple[SyncProvenance, ...]:
        """Snapshot accepted evidence without copying immutable mapping arrays."""
        return tuple(dataclasses.replace(entry) for entry in self._sync_provenance)

    def has_alignment_records(self) -> bool:
        """Check report availability without preparing export snapshots."""
        return bool(self._sync_provenance)

    def alignment_confidence(self, path: str) -> str:
        """Describe current accepted evidence without overstating its method."""
        return alignment_controller.alignment_confidence(self, path)

    def refresh_alignment_badges(self) -> None:
        """Push each source's alignment state onto its badge, on events only."""
        alignment_controller.refresh_alignment_badges(self)

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
        from avialsync.ui.sync_status import describe_provenance

        return describe_provenance(entry)

    # ── Overlays ─────────────────────────────────────────────

    def _build_overlays_menu(self, register) -> None:
        view_menu.build_overlays_menu(self, register)

    def _on_overlay_toggled(
        self, overlay_id: str, visible: bool, camera: str | None = None
    ) -> None:
        view_menu.overlay_toggled(self, overlay_id, visible, camera)

    def _set_all_overlays(self, visible: bool) -> None:
        view_menu.set_all_overlays(self, visible)

    def _apply_overlay_state(self) -> None:
        view_menu.apply_overlay_state(self)

    # ── Fix Tracker: correcting a predicted point by hand ────

    def _toggle_point_edit_mode(self, enabled: bool) -> None:
        point_edit_controller.toggle_point_edit_mode(self, enabled)

    def _on_tracked_point_moved(self, move: object) -> None:
        point_edit_controller.on_tracked_point_moved(self, move)

    def _on_point_edits_changed(self, source_id: str | None) -> None:
        # *source_id* tells the persistence path a change came from the user
        # rather than from reading a sidecar back in; every pane repaints anyway.
        del source_id
        point_edit_controller.on_point_edits_changed(self)

    def _on_wheels_changed(self, name: object) -> None:
        """Repaint every view and the Props Wheel page after a wheel changed or loaded."""
        del name
        if getattr(self, "wheel_panel", None) is not None:
            wheel_display.refresh(self)

    def _cancel_competing_placement(self, starting: Literal["marker", "wheel", "prop"]) -> None:
        """Give the shared video click to the placement starting now."""
        if starting != "marker":
            custom_marker_controller.cancel(self)
        if starting != "wheel":
            wheel_controller.cancel(self, tr("Wheel not added."))
            wheel_controller.stop_checking(self)
        if starting != "prop":
            self.props_app.cancel_step()

    def _on_marker_clicked(self, path: str, x: float, y: float) -> None:
        """A placement click in a pane: a wheel's, when one is being placed or checked.

        Otherwise a 3D marker's. The two placements never run at once.
        """
        if self.props_app.on_clicked(path, x, y):
            return
        if not wheel_controller.on_clicked(self, path, x, y):
            custom_marker_controller.on_clicked(self, path, x, y)

    def _on_custom_markers_changed(self, key: object) -> None:
        """Repaint every pane and the 3D view after a marker changed or loaded."""
        del key
        if getattr(self, "tracking_3d_pane", None) is not None:
            custom_marker_controller.refresh(self)

    def _locate_correction(self, key: object) -> tuple[float, str, int] | None:
        return point_edit_controller.locate_correction(self, key)

    def _revisit_change(self, row: object) -> None:
        point_edit_controller.revisit_change(self, row)

    def _clear_point_highlight(self) -> None:
        """Drop the revisit ring once it has done its job."""
        self.video_grid.highlight_point(None)

    def _restore_predicted_point(self, key: object) -> None:
        point_edit_controller.restore_predicted_point(self, key)

    def _persist_point_edits(self, source_id: str) -> None:
        """Write one pose source's corrections beside it, and rebuild what is shown."""
        corrections_controller.persist(self, source_id)
        # A correction is part of the same edit program as a swap, so the
        # cached channels every consumer reads have to follow it too.
        identity_controller.refresh(self, source_id)

    def _adopt_point_edits(self, source_id: str) -> None:
        """Load the corrections that live beside a pose file being imported."""
        corrections_controller.adopt(self, source_id)

    def _open_identity_panel(self) -> None:
        identity_review.open_identity_panel(self)

    def _play_identity_region(self, start: float, end: float) -> None:
        identity_review.play_identity_region(self, start, end)

    def _identity_dock_visibility_changed(self, visible: bool) -> None:
        identity_review.identity_dock_visibility_changed(self, visible)

    def _new_identity_group(self) -> None:
        identity_review.new_identity_group(self)

    def _apply_identity_swap(self) -> None:
        identity_review.apply_identity_swap(self)

    def _bring_panels_back(self) -> None:
        """Re-dock and re-centre every panel this window owns.

        A dock can be floated, dragged to a second screen, and left there --
        and a screen can then be unplugged. Nothing in Qt brings it home, so
        the panel is simply gone and reopening it shows it at the coordinates
        it vanished at. This is the one command that undoes all of that,
        whatever combination of detaching and closing got the user there.
        """
        self._act_detach_plots.setChecked(False)
        for dock in self.findChildren(QDockWidget):
            if dock.isFloating():
                dock.setFloating(False)
            dock.show()
        for dialog in (
            getattr(self, "_preferences_dialog", None),
            getattr(self, "_sync_wizard", None),
        ):
            if dialog is not None and isValid(dialog) and dialog.isVisible():
                self._bring_onto_screen(dialog)
        self.notifications.show_success(tr("Panels are back on this window."))

    def _set_plots_detached(self, detached: bool) -> None:
        """Move plots to another window, or restore them to their splitter slot."""
        if not detached:
            dialog = self._detached_plot_window
            if dialog is not None and isValid(dialog):
                dialog.close()
            else:
                self._on_detached_plots_returned()
            return

        existing = self._detached_plot_window
        if existing is not None and isValid(existing):
            existing.show()
            self._bring_onto_screen(existing)
            existing.raise_()
            return

        index = self._v_splitter.indexOf(self.plot_pane)
        if index < 0:
            blocked = self._act_detach_plots.blockSignals(True)
            self._act_detach_plots.setChecked(False)
            self._act_detach_plots.blockSignals(blocked)
            return

        from avialsync.ui.detached_pane import DetachedPaneWindow

        dialog = DetachedPaneWindow(tr("Plots"), self.plot_pane, self._v_splitter, index, self)
        self._detached_plot_window = dialog
        self._plots_detached = True
        dialog.returned.connect(self._on_detached_plots_returned)
        dialog.show()
        self._bring_onto_screen(dialog)
        dialog.raise_()

    def _on_detached_plots_returned(self) -> None:
        """Restore command state after the plot pane returns to its splitter."""
        self._detached_plot_window = None
        self._plots_detached = False
        blocked = self._act_detach_plots.blockSignals(True)
        self._act_detach_plots.setChecked(False)
        self._act_detach_plots.blockSignals(blocked)
        self._pane_proportions.record_all()

    def _bring_onto_screen(self, widget: QWidget) -> None:
        """Move *widget* onto this window's screen when it is off every screen.

        Reopening a dialog that was last closed on a monitor which is no longer
        attached shows it at coordinates nothing can reach, which reads as the
        command doing nothing at all.
        """
        if QGuiApplication.screenAt(widget.frameGeometry().center()) is not None:
            return
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = widget.frameGeometry()
        frame.moveCenter(available.center())
        widget.move(frame.topLeft())

    def _remove_identity_swap(self) -> None:
        identity_review.remove_identity_swap(self)

    def _refresh_identity_panel(self, source_id: str = "") -> None:
        identity_review.refresh_identity_panel(self, source_id)

    def _start_identity_model_job(self) -> None:
        identity_review.start_identity_model_job(self)

    def _show_identity_model(self, serial: int, job: BraidBuildJob, model: BraidModel) -> None:
        identity_review.show_identity_model(self, serial, job, model)

    def _identity_model_failed(self, serial: int, message: str) -> None:
        identity_review.identity_model_failed(self, serial, message)

    def _on_identity_swaps_changed(self, _source_id: str | None) -> None:
        """Refresh what reports accepted flips after one is accepted or undone.

        The window observes the store rather than each widget, for the reason
        the corrections observer states: a callback held by a pane outlives the
        pane, and the window outlives them all.
        """
        # The routing every overlay asks about has just changed. Dropped here,
        # in the one place that hears every add, remove and bulk load, so no
        # caller has to remember a second rule about when it went stale.
        identity_controller.forget_routes(self)
        self._refresh_action_availability()
        self._refresh_identity_lane()
        self._refresh_identity_panel()
        panel = getattr(self, "changes_panel", None)
        if panel is not None:
            panel.refresh()

    def _set_show_original_tracker(self, visible: bool) -> None:
        """Switch every pose reader through an undoable session view command."""
        if visible == self._show_original_tracker:
            return
        self.document.execute(SetOriginalTrackerVisibleCommand(visible), self._mutations)

    def _refresh_identity_lane(self) -> None:
        identity_review.refresh_identity_lane(self)

    def _master_time_of_sample(self, source_id: str, index: int) -> float | None:
        """When one sample of a pose source is shown on the master clock."""
        for sources in self._overlay_sources.values():
            entry = sources.get(source_id)
            if entry is None:
                continue
            for readers in (entry.get("points") or {}).values():
                times = readers[0].source_reader.mapped_columns()[0]
                if 0 <= index < len(times):
                    return float(readers[0].time_map.to_master(float(times[index])))
        return None

    # ── Command bus: recording live mutations ──────────

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

    def _record_mapping_change(self, source_id: str, offset: float, drift: float) -> None:
        """Record an offset/drift change against whatever it was before."""
        before = self._recorded_mappings.get(source_id, (0.0, 0.0))
        after = (offset, drift)
        if before == after:
            return
        prior_records = tuple(self._sync_provenance)
        self._recorded_mappings[source_id] = after
        self._supersede_alignment(source_id, before, after)
        changed = {entry.target_id: entry for entry in self._sync_provenance}
        before_evidence = tuple(
            entry for entry in prior_records if changed.get(entry.target_id) is not entry
        )
        if self._recording_suspended:
            return
        self._record(
            SetSourceMappingCommand(
                source_id=source_id,
                before=before,
                after=after,
                display_name=Path(source_id).name,
                before_evidence=before_evidence,
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
        if not self.session_runtime.restoring:
            self._record(AddSourceCommand(self._source_record(source_id, kind)))
            return
        if self.video_load_state.pending or self.import_state.pending or self.imaging_pending:
            return
        # The restore has drained. Everything on the log describes the file that
        # was just opened, so the session is clean by definition.
        self.session_runtime.restoring = False
        self.document.clear()
        self._mark_session_saved()
        if self.session_runtime.take_dirty_after_restore():
            self.document.mark_dirty()

    # ── Session identity and dirty state ─────────────────────────────

    def _update_window_title(self) -> None:
        appearance.update_window_title(self)

    def _on_dirty_changed(self, dirty: bool) -> None:
        """Reflect a dirty transition in the title.

        The Document notifies only on a genuine clean/dirty transition, so this
        does not need a throttle of its own: a two-hundred-step offset drag is
        one merged command and at most one transition, which keeps the title
        repaint clear of the 8 ms UI-callback target.
        """
        self.setWindowModified(dirty)

    def _mark_session_saved(self) -> None:
        appearance.mark_session_saved(self)

    def _rebuild_recent_menu(self) -> None:
        session_controller.rebuild_recent_menu(self)

    def _open_recent(self, path: str) -> None:
        session_controller.open_recent(self, path)

    # ── Theme selection ─────────────────────────────────────────────

    def _on_theme_selected(self, action: QAction) -> None:
        appearance.on_theme_selected(action)

    def _sync_theme_menu(self) -> None:
        appearance.sync_theme_menu(self._theme_group)

    def _cycle_theme(self) -> None:
        appearance.cycle_theme(self._theme_group)

    def _on_font_size_selected(self, action: QAction) -> None:
        appearance.on_font_size_selected(action)

    def _sync_font_size_menu(self) -> None:
        appearance.sync_font_size_menu(self._font_size_group)

    # ── Fullscreen / jump / pane context menu ───────────────────────

    def _toggle_fullscreen(self) -> None:
        """Show the selected camera alone, or every camera again.

        The camera is the one ``_focused_video_path`` names: the one already
        fullscreen, so the same gesture returns to the grid, then the one last
        touched. It used to be the first pane whatever was selected, so with
        three cameras F11 always enlarged the first one. With several cameras
        and none touched it still falls back to the first: unlike a nudge,
        enlarging the wrong camera changes nothing and is undone by the same key.
        """
        self.video_grid.toggle_fullscreen(self._focused_video_path())

    def _on_jump_requested(self, delta: float) -> None:
        """Clamp and seek relative to the current playhead."""
        t = self.clock.state.t + delta
        bounds = self.clock.state.bounds
        self.player.seek(max(bounds[0], min(bounds[1], t)), exact=True)

    def _on_pane_right_clicked(self, path: str, pos: Any) -> None:
        pane_menu.show_pane_menu(self, path, pos)

    def _export_snapshot_for_pane(self, path: str) -> None:
        export_controller.export_snapshot_for_pane(self, path)

    def _on_annotate_at_requested(self, t: float) -> None:
        """Add a point marker at the clicked time on the plot."""
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

    # ── Shortcuts dialog ─────────────────────────────────────────────

    def _show_command_palette(self) -> None:
        """Search every registered command by name.

        Built from the same live QActions the shortcuts dialog uses,
        so it cannot list a command that does not exist or miss one that does.
        Registered actions without a shortcut are included too -- the menus have
        grown deep enough that finding a command is the problem, not typing it.
        """
        from avialsync.ui.command_palette import CommandPalette

        palette = CommandPalette(list(self._all_actions), self)
        palette.exec()

    def _show_shortcuts(self) -> None:
        from avialsync.ui.shortcuts_dialog import ShortcutsDialog

        # Group all registered QActions by category tag. Unbound
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

    def _export_stimulus_grid(self) -> None:
        export_controller.export_stimulus_grid(self)

    @Slot(str, bool)
    def _on_stimulus_grid_export_finished(self, path: str, replaced: bool) -> None:
        export_controller.on_stimulus_grid_export_finished(self, path, replaced)

    @Slot(str)
    def _on_stimulus_grid_export_error(self, error: str) -> None:
        export_controller.on_stimulus_grid_export_error(self, error)

    # ── Proxy generation ─────────────────────────────────────────────

    def _generate_proxy(self) -> None:
        proxy_controller.generate_proxy(self)

    def _on_proxy_finished(self, _orig: str, proxy: str) -> None:
        proxy_controller.on_proxy_finished(self, proxy)

    def _on_proxy_error(self, err: str) -> None:
        proxy_controller.on_proxy_error(self, err)

    # ── Source loading ───────────────────────────────────────────────

    def _load_video(
        self,
        path: Path,
        offset: float = 0.0,
        drift_ms_per_hour: float = 0.0,
        config: dict[str, Any] | None = None,
    ) -> None:
        video_controller.load_video(self, path, offset, drift_ms_per_hour, config)

    def _start_next_video_load(self) -> None:
        video_controller.start_next_video_load(self)

    def _start_one_video_probe(self) -> None:
        video_controller.start_one_video_probe(self)

    def _set_video_coverage(
        self,
        path: str,
        source_bounds: tuple[float, float],
        offset: float,
        drift_ms_per_hour: float,
        exact_master: np.ndarray | None = None,
        exact_source: np.ndarray | None = None,
    ) -> None:
        video_controller.set_video_coverage(
            self, path, source_bounds, offset, drift_ms_per_hour, exact_master, exact_source
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
        # A probed video may wait behind another pane. Its eventual creation is
        # what changes commands requiring two cameras, even though no new probe
        # callback follows that event.
        self._refresh_empty_state()

    @Slot(str, str)
    def _on_video_open_error(self, path: str, error: str) -> None:
        video_controller.on_video_open_error(self, path, error)

    @Slot()
    def _on_video_thread_finished(self) -> None:
        video_controller.on_video_thread_finished(self)

    @Slot()
    def _on_video_pane_ready(self) -> None:
        video_controller.on_video_pane_ready(self)
        # Its frames are known only now; where it has none between parts may
        # have been asked of a pane that could not answer yet (D-218).
        gap_view.refresh_holes(self)

    def _on_video_offset_changed(self, path: str, offset: float) -> None:
        """Move one camera by hand. *offset* is the sidebar residual, not the map.

        The pane gets the residual plus this source's session placement. Giving
        it the residual alone is how a wall-clock camera used to vanish on its
        first nudge: 1.77e9 of placement was replaced by the two seconds the
        user typed, and the pane went looking for a frame five decades away.
        """
        _, drift = self._recorded_mappings.get(path, (0.0, 0.0))
        self._record_mapping_change(path, offset, drift)
        effective = self.effective_offset(path, offset)
        self.video_grid.set_offset(path, effective)
        if path in self._video_source_bounds:
            self._set_video_coverage(path, self._video_source_bounds[path], effective, drift)
        # The frame on screen was chosen under the old mapping, so it is now
        # the wrong one. This used to be `clock.play(); clock.pause()`, which
        # notifies no subscriber and left the pane showing that stale frame
        # until the user happened to scrub -- the change looked like it had not
        # taken.
        from avialsync.ui.sync_lifecycle import refresh_coverage

        refresh_coverage(self, path)
        tracking_timing.calibrate_overlay_timing(self, path)
        self.player.seek(self.clock.state.t, exact=True)

    # ── Trigger evidence (WP-D) ──────────────────────────────────────

    def _open_trigger_evidence(self) -> None:
        alignment_controller.open_trigger_evidence(self)

    def _start_trigger_read(self, source: object, path: Path, config: dict[str, Any]) -> None:
        alignment_controller.start_trigger_read(self, source, path, config)

    @Slot(str, object)
    def _on_trigger_trains_read(self, path: str, results: object) -> None:
        alignment_controller.on_trigger_trains_read(self, path, results)

    def _source_coverage(self) -> list[SourceCoverage]:
        """Every loaded source's span, and how much of it evidence reaches.

        Answering "do these recordings overlap at all" before anything is
        fitted, which no residual can answer afterwards.
        """
        from avialsync.ui.sync_lifecycle import coverage_sources

        return coverage_sources(self)

    def _evidence_span(self, path: str) -> tuple[float, float] | None:
        return alignment_controller.evidence_span(self, path)

    @Slot(str, float, float)
    def _on_video_mapping_changed(self, path: str, offset: float, drift: float) -> None:
        alignment_controller.on_video_mapping_changed(self, path, offset, drift)

    def restore_trigger_sources(self, entries: list[TriggerEntry]) -> None:
        """Re-read every trigger file a restored session declared."""
        alignment_controller.restore_trigger_sources(self, entries)

    def trigger_mapping(self, path: str) -> TimeMap:
        """Return the accepted mapping for a trigger file, or its local clock."""
        return self._trigger_time_maps.get(path, TimeMap())

    def set_trigger_mapping(self, path: str, mapping: TimeMap) -> None:
        """Place a trigger file's clock on the master timeline."""
        self._trigger_time_maps[path] = mapping

    def take_pending_exact_mapping(self, path: str) -> tuple[np.ndarray, np.ndarray] | None:
        """Claim the exact mapping a restored session holds for *path*, once."""
        return self._pending_exact_mappings.pop(path, None)

    def clear_trigger_sources(self) -> None:
        """Discard trigger evidence and placements when the workspace is reset."""
        self._trigger_trains.clear()
        self._trigger_time_maps.clear()
        self._trigger_configs.clear()

    def _open_sync_wizard(self) -> None:
        alignment_controller.open_sync_wizard(self)

    def _on_sync_wizard_accepted(self, wizard: object) -> None:
        """Apply what the user accepted, once they have finished looking."""
        proposal = getattr(wizard, "proposal", None)
        if proposal is not None:
            self._accept_sync_proposal(getattr(wizard, "target_id", ""), proposal)

    def _release_sync_wizard(self) -> None:
        """Drop the window's reference once the dialog has closed."""
        wizard = self._sync_wizard
        self._sync_wizard = None
        if wizard is not None:
            wizard.deleteLater()

    @Slot(float)
    def _seek_to_evidence(self, reference_time: float) -> None:
        """Put the master clock on a clicked event, so the footage can be seen.

        The reference source's own clock is master time for it: the fit being
        judged has not been applied to anything yet, and applying it to decide
        whether to apply it would be circular.
        """
        self.clock.seek(float(reference_time))
        self.player.seek(float(reference_time), exact=True)

    def _accept_sync_proposal(self, target_path: str, proposal: object) -> None:
        """Apply a proposal through the shared acceptance path."""
        from avialsync.ui.sync_acceptance import accept_sync_proposal

        accept_sync_proposal(self, target_path, proposal)

    def _on_video_remove_requested(self, path: str) -> None:
        sources_controller.on_video_remove_requested(self, path)

    def _on_sensor_remove_requested(self, path: str) -> None:
        sources_controller.on_sensor_remove_requested(self, path)

    def _on_sensor_mapping_changed(self, path: str, offset: float, drift: float) -> None:
        sources_controller.on_sensor_mapping_changed(self, path, offset, drift)

    def _on_channel_remove_requested(self, path: str, channel: str) -> None:
        """Remove only this source's row — another file may use the same name."""
        self.plot_pane.remove_channel(ChannelKey(path, channel))

    def _on_channel_visibility_changed(self, path: str, channel: str, is_visible: bool) -> None:
        sources_controller.on_channel_visibility_changed(self, path, channel, is_visible)

    def _on_tracking_visibility_changed(self, path: str, surface: str, visible: bool) -> None:
        sources_controller.on_tracking_visibility_changed(self, path, surface, visible)

    def _apply_tracking_visibility(self, path: str, surface: str, visible: bool) -> None:
        sources_controller.apply_tracking_visibility(self, path, surface, visible)

    def _refresh_tracking_visuals(self, path: str) -> None:
        sources_controller.refresh_tracking_visuals(self, path)

    def _sync_tracking_plot(self, path: str) -> None:
        sources_controller.sync_tracking_plot(self, path)

    # ── Display levels ───────────────────────────────────────

    def _focused_video_path(self) -> str | None:
        return sources_controller.focused_video_path(self)

    def _step_reference_pane(self) -> Any:
        """The camera frame steps follow: the focused one, when there is one."""
        path = self._focused_video_path()
        return self._pane_for(path) if path is not None else None

    def _select_video(self, path: str) -> None:
        sources_controller.select_video(self, path)

    def _pane_for(self, path: str) -> object | None:
        try:
            return self.video_grid.panes[self.video_grid.pane_paths().index(path)]
        except (ValueError, IndexError):
            return None

    def _on_source_format_detected(self, path: str, source_format: object) -> None:
        """Label the levels panel in the depth this file turned out to have."""
        if not isinstance(source_format, SourceFormat):
            return
        if path == self._focused_video_path():
            video_levels.show_focused(self)

    def _on_display_levels_changed(self, levels: object) -> None:
        """The inspector panel moved: a change to the focused camera's levels."""
        video_levels.request(self, self._focused_video_path(), levels)

    def _on_auto_levels_requested(self) -> None:
        """Choose black and white from the focused camera's frame on screen."""
        video_levels.request_auto(self, self._focused_video_path())

    def _on_channel_group_visibility_changed(
        self, path: str, group_label: str, channels: list, visible: bool
    ) -> None:
        sources_controller.on_channel_group_visibility_changed(
            self, path, group_label, channels, visible
        )

    def _on_plot_channel_close_requested(self, source_id: str, channel: str) -> None:
        """Route a plot-row close through the owning source's visibility checkbox."""
        self.sidebar.set_channel_visible(channel, False, source_id)

    def _on_video_visibility_changed(self, path: str, is_visible: bool) -> None:
        sources_controller.on_video_visibility_changed(self, path, is_visible)

    # No file filters: a plugin may claim any extension. Titles are
    # the actions' own text.
    def _open_video(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, self._act_open_video.text().rstrip("…"))
        for path in paths:
            self._load_video(Path(path))

    def _open_data(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, self._act_open_sensor.text().rstrip("…"))
        for path in paths:
            self.open_path(Path(path))

    def _start_data_import(
        self,
        path: Path,
        loader_cls: type[TimeSeriesSource] | None = None,
        pre_config: dict | None = None,
        *,
        restoring: bool = False,
    ) -> None:
        import_controller.start_data_import(self, path, loader_cls, pre_config, restoring=restoring)

    def _enqueue_import(self, path: Path, loader_cls: type, config: dict[str, Any]) -> None:
        import_controller.enqueue_import(self, path, loader_cls, config)

    def _start_import(self, path: Path, loader_cls: type, config: dict[str, Any]) -> None:
        import_controller.start_import(self, path, loader_cls, config)

    @Slot()
    def _on_import_thread_finished(self) -> None:
        import_controller.on_import_thread_finished(self)

    def _rebind_frame_indexed_sources(self) -> None:
        import_controller.rebind_frame_indexed_sources(self)

    def _on_import_finished(
        self,
        path: str,
        cache_dir: str,
        channels: list[str],
        bounds: tuple[float, float],
        inspection: object = None,
    ) -> None:
        import_controller.on_import_finished(self, path, cache_dir, channels, bounds, inspection)
        # Overlay calibration ran before the source card existed; lock it now if it must be.
        tracking_timing.show_timing_owner(self, path)
        if any(str(pending) == path for pending, _loader, _config in self._frame_indexed_sources):
            # A camera may have opened while this was importing at an assumed rate.
            self._rebind_frame_indexed_sources()
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
        drift_ms_per_hour: float = 0.0,
    ) -> None:
        import_controller.register_tracking_source(
            self, path, cache_dir, channels, role, inspection, offset, drift_ms_per_hour
        )

    def _refresh_pose_3d(self) -> None:
        import_controller.refresh_pose_3d(self)

    def _update_tracking_pane_visibility(self) -> None:
        import_controller.update_tracking_pane_visibility(self)

    def _refresh_overlays(self, video: str) -> None:
        import_controller.refresh_overlays(self, video)

    def _on_import_error(self, err_msg: str) -> None:
        import_controller.on_import_error(self, err_msg)

    def _recompute_bounds(self) -> None:
        """Derive the master timeline from the sources that are loaded now.

        Bounds used to be a running union that only ever grew, and the offset
        controls are what made that visible: every intermediate value a user
        typed stretched the timeline and none of them ever came back. Typing
        86400 into an offset field left the session 86400 s long around a
        twenty-second recording, with every camera off the visible range and
        the panes showing "No Footage" -- the source had been put back, and the
        timeline had not heard.

        The overview strip already keys one span per source and drops the ones
        that go away, so it -- not an accumulator -- is what the bounds are
        derived from (one authority per user-visible concept).
        """
        # An empty registry means the last source has been removed, and the
        # timeline goes back to what it is before anything is loaded. It cannot
        # mean "not loaded yet": every caller registers its span first.
        self._apply_bounds(self.transport.coverage_span() or (0.0, 0.0))

    def _apply_bounds(self, bounds: tuple[float, float]) -> None:
        """Publish one master-time range to the clock and everything drawing it.

        The playhead is redrawn at the time the clock actually holds. It used
        to be redrawn at the new *start*, which moved the transport readout,
        the slider and the overview cursor to a time playback was not at: the
        next click on the slider then seeked relative to a position the user
        had never chosen.
        """
        self.clock.set_bounds(*bounds)
        self.plot_pane.set_timeline_bounds(*bounds)
        self.transport.set_bounds(*bounds)
        self.transport.set_time(self.clock.state.t)
