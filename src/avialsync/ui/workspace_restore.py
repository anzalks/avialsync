"""Reversible workspace snapshot restoration for ``ResetSessionCommand``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from avialsync.core.channel_reader import ChannelKey
from avialsync.ui import imaging_integration, video_levels
from avialsync.ui.annotations import VideoFrame

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


def restore_workspace_snapshot(window: MainWindow, snapshot: Any) -> None:
    """Restore a captured workspace snapshot onto *window* during Undo."""
    state = snapshot.get("state")
    if state is None:
        for path in snapshot.get("videos", []):
            window._load_video(Path(path))
        for path in snapshot.get("sensors", []):
            window._start_data_import(Path(path))
        return
    _restore_chrome_and_sync(window, state)
    _restore_sources(window, snapshot, state)
    _restore_views_and_markers(window, state)


def _restore_chrome_and_sync(window: MainWindow, state: Any) -> None:
    window.overlay_state.load(state.overlays)
    window._apply_overlay_state()
    video_levels.restore(window, state.display_levels)
    window._show_original_tracker = state.show_original_tracker
    action = window._act_show_original_tracker
    blocked = action.blockSignals(True)
    action.setChecked(state.show_original_tracker)
    action.blockSignals(blocked)
    window.session_runtime.start_time = float(state.session_start_time)
    window._publish_session_epoch()
    window._sync_provenance = list(state.sync_provenance)
    window.refresh_alignment_badges()
    window.restore_trigger_sources(list(state.triggers))
    window._pending_exact_mappings.clear()
    for prov in state.sync_provenance:
        if len(prov.exact_master) and len(prov.exact_source):
            window._pending_exact_mappings[prov.target_id] = (
                np.asarray(prov.exact_master, dtype=np.float64),
                np.asarray(prov.exact_source, dtype=np.float64),
            )


def _restore_sources(window: MainWindow, snapshot: Any, state: Any) -> None:
    videos_by_path = {ve.path: ve for ve in state.videos}
    video_paths = list(dict.fromkeys([*snapshot.get("videos", []), *videos_by_path]))
    for path in video_paths:
        ve = videos_by_path.get(path)
        window._load_video(
            Path(path),
            offset=ve.offset if ve else 0.0,
            drift_ms_per_hour=ve.drift_ms_per_hour if ve else 0.0,
        )
    camera_views = {ve.path: dict(ve.view) for ve in state.videos if ve.view}
    window.video_grid.apply_camera_views(camera_views, defer_unloaded=True)
    imaging_integration.restore_entries(window, state.imaging, {})
    sensors_by_path = {se.path: se for se in state.sensors}
    sensor_paths = list(dict.fromkeys([*snapshot.get("sensors", []), *sensors_by_path]))
    for path in sensor_paths:
        se = sensors_by_path.get(path)
        if se is None:
            window._start_data_import(Path(path))
            continue
        window._pending_sensor_mappings[path] = (se.offset, se.drift_ms_per_hour)
        window._pending_channel_visibility[path] = dict(se.channel_visibility)
        window._pending_tracking_visibility[path] = {
            "overlay": se.tracking_overlay_visible,
            "plot": se.tracking_plot_visible,
        }
        if se.import_config:
            window._start_data_import(Path(path), pre_config=dict(se.import_config))
        else:
            window._start_data_import(Path(path))


def _restore_views_and_markers(window: MainWindow, state: Any) -> None:
    if state.view_3d:
        window.tracking_3d_pane.set_view_orientation(state.view_3d, defer_until_loaded=True)
    window.plot_pane.set_view_mode(getattr(state, "plot_view_mode", "stacked"))
    pinned = getattr(state, "pinned_channels", None) or []
    if pinned:
        apply_pins = getattr(window.plot_pane, "apply_pinned_channels", None)
        if callable(apply_pins):
            apply_pins(pinned, {})
        for p in pinned:
            window.plot_pane.set_channel_pinned(ChannelKey(p["source_id"], p["channel"]), True)
    for entry in state.markers:
        vfs = [
            VideoFrame(
                path=str(vf["path"]),
                frame_index=int(vf["frame_index"]),
                media_timestamp=float(vf["media_timestamp"]),
            )
            for vf in entry.video_frames
        ]
        if entry.t_end is None:
            window.annotation_store.add_point(entry.t_start, entry.label, video_frames=vfs)
        else:
            window.annotation_store.add_range(
                entry.t_start, entry.t_end, entry.label, video_frames=vfs
            )
    if state.plot_x0 is not None and state.plot_x1 is not None:
        window.plot_pane.set_window_duration(state.plot_x1 - state.plot_x0)
