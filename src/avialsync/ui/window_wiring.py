"""Signal wiring MainWindow installs during construction.

Moved from ``MainWindow.__init__`` (WINDOW_COMPOSITION_PLAN A10) without
reordering: where two slots share a signal they still connect, and so run, in
the order written here. Every receiver is a bound method of the window, so
delivery semantics are unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from avialsync.ui import imaging_integration

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


def connect_annotations(window: MainWindow) -> None:
    """Keep the timeline, command availability, and undo log in step with annotations."""
    window.annotation_store.changed.connect(window._update_timeline_annotations)
    # Export Changes is available exactly when one of these has something
    # in it, so both drive the availability pass.
    window.annotation_store.changed.connect(window._refresh_action_availability)
    window.annotation_store.marker_added.connect(window._record_marker_added)
    window.annotation_store.marker_removed.connect(window._record_marker_removed)
    window.annotation_store.marker_relabelled.connect(window._record_marker_relabelled)


def connect_sources(window: MainWindow) -> None:
    """Route the Sources sidebar's per-source gestures to the window."""
    window.sidebar.video_offset_changed.connect(window._select_video)
    window.sidebar.video_offset_changed.connect(window._on_video_offset_changed)
    window.sidebar.video_mapping_changed.connect(window._on_video_mapping_changed)
    window.sidebar.video_badge_clicked.connect(window._select_video)
    window.sidebar.video_remove_requested.connect(window._on_video_remove_requested)
    # Persist before a removed pane's media client is torn down: that
    # teardown can fault on Windows, and mid-session it would otherwise
    # cost everything since the last autosave.
    window.video_grid.pane_detached.connect(window._write_session_snapshot)
    window.sidebar.video_visibility_changed.connect(window._on_video_visibility_changed)
    imaging_integration.connect_sidebar(window)
    window.sidebar.sensor_remove_requested.connect(window._on_sensor_remove_requested)
    window.sidebar.sensor_mapping_changed.connect(window._on_sensor_mapping_changed)
    window.sidebar.channel_remove_requested.connect(window._on_channel_remove_requested)
    window.sidebar.channel_visibility_changed.connect(window._on_channel_visibility_changed)
    window.sidebar.channel_group_visibility_changed.connect(
        window._on_channel_group_visibility_changed
    )
    window.sidebar.tracking_visibility_changed.connect(window._on_tracking_visibility_changed)
    window.plot_pane.channel_close_requested.connect(window._on_plot_channel_close_requested)
    window.sidebar.grid_mode_changed.connect(window.video_grid.set_grid_mode)
    window.sidebar.video_badge_clicked.connect(window._show_video_properties)
    window.sidebar.sensor_badge_clicked.connect(window._show_sensor_properties)
    window.sidebar.sensor_report_requested.connect(window._show_import_report)


def connect_transport_and_panes(window: MainWindow) -> None:
    """Route transport, toolbar, camera-pane and plot gestures to the window."""
    window.transport.ab_loop_changed.connect(window._on_ab_loop_changed)
    window.view_toolbar.flag_requested.connect(window._on_annotate_requested)
    window.transport.jump_requested.connect(window._on_jump_requested)

    # Camera selection and the picture’s context menu.
    window.video_grid.pane_activated.connect(window._select_video)
    window.video_grid.pane_right_clicked.connect(window._on_pane_right_clicked)

    # Plot annotate-at
    window.plot_pane.annotate_at_requested.connect(window._on_annotate_at_requested)
