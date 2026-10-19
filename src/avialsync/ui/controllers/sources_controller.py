"""Loaded sources after import: removal, re-mapping, visibility, the focused camera.

Moved from MainWindow (WINDOW_COMPOSITION_PLAN A9), which keeps one delegator
per function (D-066); the moved code keeps calling the window's own methods,
and its private accesses are in the boundary baseline under D-248. Imports
that were local stay local, so a test patching their module still intercepts.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from avialsync.core.channel_reader import ChannelKey
from avialsync.core.commands import (
    RemoveSourceCommand,
    SetChannelGroupVisibleCommand,
    SetChannelVisibleCommand,
    SetSourceVisibleCommand,
    SetTrackingVisibleCommand,
)
from avialsync.ui import tracking_timing, video_levels
from avialsync.ui.controllers import wheel_display

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


def on_video_remove_requested(window: MainWindow, path: str) -> None:
    """Remove one camera and everything the window knew about it, undoably."""
    from avialsync.ui.sync_lifecycle import invalidate

    invalidate(window, path)
    window._record(RemoveSourceCommand(window._source_record(path, "video")))
    # Everything this window knows about the source is dropped before the
    # grid tears the pane down, because `remove_pane` writes the session on
    # the way past and that snapshot must describe the session the user
    # just asked for, not the one with this video still in it.
    window.sidebar.remove_video(path)
    window._video_frame_times.pop(path, None)
    window._overlay_sources.pop(path, None)
    window.overlay_state.forget_camera(path)
    window._sync_provenance = [
        entry for entry in window._sync_provenance if entry.target_id != path
    ]
    window.video_grid.remove_pane(path)
    # The master timeline is the union of the loaded sources, so a camera
    # that is gone must stop claiming a span -- otherwise removing the one
    # source that reached out to 400 s leaves the timeline 400 s long.
    window._video_source_bounds.pop(path, None)
    window._video_time_mappings.pop(path, None)
    window.transport.set_source_coverage(path, 0.0, 0.0, "video")
    window._recompute_bounds()
    window._refresh_empty_state()


def on_sensor_remove_requested(window: MainWindow, path: str) -> None:
    """Remove one time-series or tracking source and its rows, undoably."""
    from avialsync.ui.sync_lifecycle import invalidate

    invalidate(window, path)
    window._record(RemoveSourceCommand(window._source_record(path, "sensor")))
    inspection = window._inspections.get(path)
    if inspection is not None:
        inspection.release_cache_pin()
    cache_dir = window._sensor_cache_dirs.pop(path, None)
    tracking_source = window._tracking_plot_sources.pop(path, None)
    window._tracking_visibility.pop(path, None)
    window._pending_tracking_visibility.pop(path, None)
    window._pose_3d_sources.pop(path, None)
    for sources in window._overlay_sources.values():
        sources.pop(path, None)
    for video in window._overlay_sources:
        window._refresh_overlays(video)
    window._refresh_pose_3d()
    if tracking_source is not None:
        cache_dir = tracking_source[0]
    if cache_dir is None:
        # Pre-import removal: fall back to the manager's derived location.
        from avialsync.core.cache import CacheManager

        cache_dir = CacheManager().get_cache_dir(Path(path))
    window.plot_pane.remove_channels(cache_dir)
    window.sidebar.remove_sensor(path)
    window.message_store.remove_source(path)
    window.transport.set_source_coverage(path, 0.0, 0.0, "data")
    window._recompute_bounds()


def on_sensor_mapping_changed(window: MainWindow, path: str, offset: float, drift: float) -> None:
    """Re-align one time-series source against the master clock.

    This only changes the source's ``TimeMap`` — cached samples are never
    rewritten and no channel is re-imported (P3.5, mirrors video offsets).
    """
    if path in window._tracking_plot_sources:
        # A pose source has no plot rows to carry the mapping; its readers do.
        window._record_mapping_change(path, offset, drift)
        tracking_timing.apply_mapping(window, path, window.effective_offset(path, offset), drift)
        return
    cache_dir = window._sensor_cache_dirs.get(path)
    if cache_dir is None:
        return
    window._record_mapping_change(path, offset, drift)
    # *offset* is the sidebar residual; the readers need the whole mapping,
    # session placement included, or a wall-clock source jumps back to its
    # raw epoch the moment the user touches the control.
    effective = window.effective_offset(path, offset)
    window.plot_pane.set_source_mapping(cache_dir, effective, drift)
    # A note moves with the samples it describes; leaving it behind would
    # put an experimenter's "stimulus on" beside the wrong trace.
    window.message_store.set_source_mapping(path, effective, drift)
    bounds = window.plot_pane.source_bounds(cache_dir)
    if bounds is not None:
        # Coverage first, then bounds: the timeline is derived from the
        # registered spans, so it has to see this source's new one rather
        # than the span it had before the user moved it.
        window.transport.set_source_coverage(
            path, bounds[0], bounds[1], "data", window.coverage_group_for(path)
        )
        window._recompute_bounds()
    window.readout_panel.set_cursor(window.clock.state.t)
    if any(w.binding is not None and w.binding.source_id == path for w in window.wheels):
        # The wheel turns by this encoder: redraw it, and show the new
        # offset on its Props Wheel page row as well as in Sources.
        wheel_display.refresh(window)


def _follow_tracking_rows(window: MainWindow, path: str) -> bool:
    """Route a visibility change on a tracking source; False for ordinary rows."""
    if path not in window._tracking_plot_sources:
        return False
    window._refresh_tracking_visuals(path)
    if window._tracking_visibility.get(path, {}).get("plot", False):
        window._sync_tracking_plot(path)
    return True


def on_channel_visibility_changed(
    window: MainWindow, path: str, channel: str, is_visible: bool
) -> None:
    """Show or hide one channel's row, undoably."""
    window._record(SetChannelVisibleCommand(source_id=path, channel=channel, visible=is_visible))
    if not _follow_tracking_rows(window, path):
        window.plot_pane.set_channel_visible(ChannelKey(path, channel), is_visible)


def on_channel_group_visibility_changed(
    window: MainWindow, path: str, group_label: str, channels: list, visible: bool
) -> None:
    """Show or hide a whole group of channels as one undoable action.

    One command, not one per channel: hiding a group of forty is a single
    decision, and an undo history needing forty presses to reverse one
    click would be worse than no undo for it.
    """
    before = {
        str(channel): window.plot_pane.is_channel_visible(ChannelKey(path, str(channel)))
        for channel in channels
    }
    window._record(
        SetChannelGroupVisibleCommand(
            source_id=path, group_label=group_label, before=before, visible=visible
        )
    )
    if _follow_tracking_rows(window, path):
        return
    for channel in channels:
        window.plot_pane.set_channel_visible(ChannelKey(path, str(channel)), visible)


def on_tracking_visibility_changed(
    window: MainWindow, path: str, surface: str, visible: bool
) -> None:
    """Record a per-tracker presentation choice from its sidebar card."""
    state = window._tracking_visibility.get(path)
    if state is None or state.get(surface) == visible:
        return
    window._record(
        SetTrackingVisibleCommand(
            source_id=path, surface=surface, visible=visible, display_name=Path(path).name
        )
    )
    window._apply_tracking_visibility(path, surface, visible)


def apply_tracking_visibility(window: MainWindow, path: str, surface: str, visible: bool) -> None:
    """Apply one tracking presentation choice to its real rendering path."""
    if surface not in {"overlay", "plot"}:
        return
    state = window._tracking_visibility.setdefault(path, {"overlay": True, "plot": False})
    state[surface] = visible
    window.sidebar.set_tracking_visible(path, surface, visible)
    if surface == "overlay":
        window._refresh_tracking_visuals(path)
        return
    window._sync_tracking_plot(path)


def refresh_tracking_visuals(window: MainWindow, path: str) -> None:
    """Rebuild only the visual routes that a tracking source can feed."""
    for video, sources in window._overlay_sources.items():
        if path in sources:
            window._refresh_overlays(video)
    window._refresh_pose_3d()


def sync_tracking_plot(window: MainWindow, path: str) -> None:
    """Build or hide a tracking source's plot rows without re-importing it."""
    source = window._tracking_plot_sources.get(path)
    if source is None:
        return
    cache_dir, channels, offset, drift_ms_per_hour = source
    visible = window._tracking_visibility.get(path, {}).get("plot", False)
    card = window.sidebar.sensor_widget(path)
    selected = set(card.checked_channels()) if card is not None else set(channels)
    if visible:
        existing = {
            channel.reader.channel_id
            for channel in window.plot_pane.channels
            if channel.reader.source_id == path
        }
        missing = [
            channel for channel in channels if channel in selected and channel not in existing
        ]
        if missing:
            window.plot_pane.load_channels(
                cache_dir, missing, offset, drift_ms_per_hour, source_id=path
            )
    for channel in channels:
        window.plot_pane.set_channel_visible(
            ChannelKey(path, channel), visible and channel in selected
        )


def on_video_visibility_changed(window: MainWindow, path: str, is_visible: bool) -> None:
    """Show or hide one camera's pane, undoably."""
    window._record(
        SetSourceVisibleCommand(source_id=path, visible=is_visible, display_name=Path(path).name)
    )
    window.video_grid.set_pane_visible(path, is_visible)


def focused_video_path(window: MainWindow) -> str | None:
    """The camera an action without an explicit target should act on.

    In order: the one shown fullscreen, then the one the user last touched,
    then -- only when there is exactly one -- that one.

    It deliberately does **not** fall back to the first of several. It used
    to, and with three cameras loaded that meant every nudge moved FaceCam
    whichever camera the user had in mind, silently. Returning None instead
    lets the caller say what it needs rather than acting on a guess.
    """
    paths = window.video_grid.pane_paths()
    if not paths:
        return None

    fullscreen = getattr(window.video_grid, "_fullscreen_pane", None)
    if fullscreen is not None:
        for path, pane in zip(paths, window.video_grid.panes, strict=False):
            if pane is fullscreen:
                return path

    if window._selected_video_path in paths:
        return window._selected_video_path

    return paths[0] if len(paths) == 1 else None


def select_video(window: MainWindow, path: str) -> None:
    """Remember the camera the user just interacted with.

    Any interaction counts -- a click on the pane, its context menu, or a
    change to its offset -- because all of them mean "this one" as clearly
    as a selection gesture would, and none of them needed inventing.
    """
    if path in window.video_grid.pane_paths():
        window._selected_video_path = path
        # The panel shows this camera's levels, not the last camera's.
        video_levels.show_focused(window)
