"""Re-timing a pose source after it is loaded.

A pose source is never plotted by default, so it has no plot rows whose shared
``TimeMap`` an offset could move: its overlay and 3D readers hold their own. Its
source card offered the same Offset and Drift fields as any data source, and
they changed nothing until the session was reopened -- the handler looked for
plot rows, found none, and returned. This applies the mapping live, the way a
reopen would apply it.

A 2D overlay whose frame indices fit its camera is timed by that camera's own
presentation times, which replace any offset of its own (an exact mapping wins
over offset and drift). Its fields are locked and say so, rather than accepting
a value that cannot move it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.core.timeline import TimeMap
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def _readers(window: MainWindow, path: str) -> list[Any]:
    """Every overlay and 3D reader built for pose source *path*."""
    readers = list(window._pose_3d_sources.get(path, []))
    for sources in window._overlay_sources.values():
        entry = sources.get(path)
        if entry is not None:
            for axes in entry.get("points", {}).values():
                readers.extend(axes)
    return readers


def _time_maps(window: MainWindow, path: str) -> list[TimeMap]:
    """The distinct time maps those readers share (usually one)."""
    maps: dict[int, TimeMap] = {}
    for reader in _readers(window, path):
        maps[id(reader.time_map)] = reader.time_map
    return list(maps.values())


def timing_owner(window: MainWindow, path: str) -> str:
    """The camera whose frames time pose source *path*, or ``""`` when its own mapping does."""
    if not any(time_map.has_exact_mapping for time_map in _time_maps(window, path)):
        return ""
    for video, sources in window._overlay_sources.items():
        if path in sources:
            return Path(video).name
    return ""


def show_timing_owner(window: MainWindow, path: str) -> None:
    """Lock or free the source card's Offset and Drift to match who times the source."""
    owner = timing_owner(window, path)
    window.sidebar.set_sensor_timing_locked(path, owner_tooltip(owner) if owner else "")


def apply_mapping(window: MainWindow, path: str, offset: float, drift: float) -> None:
    """Move pose source *path* to *offset* and *drift*, as reopening the session would."""
    entry = window._tracking_plot_sources.get(path)
    if entry is None:
        return
    cache_dir, channels, _offset, _drift = entry
    # Kept for the rows Show plot builds later, which read it from here.
    window._tracking_plot_sources[path] = (cache_dir, channels, offset, drift)
    for time_map in _time_maps(window, path):
        time_map.offset = offset
        time_map.drift_ms_per_hour = drift
    window.plot_pane.set_source_mapping(cache_dir, offset, drift)
    videos = [video for video, sources in window._overlay_sources.items() if path in sources]
    for video in videos:
        # Setting an offset drops an exact mapping; where the camera's frames
        # time this source, they take it back, exactly as on reopen.
        calibrate_overlay_timing(window, video)
        window._refresh_overlays(video)
    if path in window._pose_3d_sources:
        window._refresh_pose_3d()
    window.message_store.set_source_mapping(path, offset, drift)
    spans = [span for reader in _readers(window, path) if (span := reader.coverage()) is not None]
    if spans:
        window.transport.set_source_coverage(
            path,
            min(span[0] for span in spans),
            max(span[1] for span in spans),
            "data",
            window.coverage_group_for(path),
        )
        window._recompute_bounds()
    window.readout_panel.set_cursor(window.clock.state.t)


def owner_tooltip(owner: str) -> str:
    """Why a locked pose source's timing fields cannot be edited."""
    return tr("Timed by {camera}'s own frames. Move that camera to move this source.").format(
        camera=owner
    )


def calibrate_overlay_timing(window: MainWindow, video: str) -> None:
    """Map an AOL 2D track's frame indices to its video's presentation times.

    Tracking CSVs name frames while a video may have VFR intervals or dropped
    frames.  Matching the track's stored frame-index times to the target pane's
    measured timestamps keeps the overlay tied to the pixels actually shown.
    """
    try:
        pane_index = window.video_grid.pane_paths().index(video)
    except ValueError:
        return
    frame_times = window._video_frame_times.get(video)
    if frame_times is None or len(frame_times) < 2:
        return

    pane = window.video_grid.panes[pane_index]
    for entry in window._overlay_sources.get(video, {}).values():
        frame_rate = float(entry.get("frame_rate", 0.0))
        points = entry.get("points", {})
        if frame_rate <= 0.0 or not points:
            continue
        first_reader = next(iter(points.values()))[0]
        source_times = first_reader.source_reader.mapped_columns()[0]
        if len(source_times) < 2:
            continue
        frame_indices = np.rint(source_times * frame_rate).astype(np.intp)
        if (
            not np.allclose(source_times * frame_rate, frame_indices)
            or frame_indices[0] < 0
            or frame_indices[-1] >= len(frame_times)
        ):
            _report_uncalibrated_overlay(window, video, first_reader.source_id)
            continue
        master_times = pane.time_map.to_master_array(frame_times[frame_indices])
        time_maps = {
            id(reader.time_map): reader.time_map for axes in points.values() for reader in axes
        }
        for time_map in time_maps.values():
            time_map.set_exact_mapping(master_times, source_times)
        cache_dir = getattr(window, "_pose_cache_dirs", {}).get(first_reader.source_id)
        if cache_dir is not None and hasattr(window, "plot_pane"):
            window.plot_pane.set_source_exact_mapping(cache_dir, master_times, source_times)
        if hasattr(window, "sidebar"):
            # The camera now times this source, so its own Offset and Drift cannot move it.
            show_timing_owner(window, first_reader.source_id)


def _report_uncalibrated_overlay(window: MainWindow, video: str, source_id: str) -> None:
    """Say that an overlay is drawn on assumed timing rather than the video's own.

    Not a log line. Uniform ``index / fps`` timing drifts from a real
    recording's presentation times by up to 0.16 s -- five frames at 30 fps, on
    top of the animal -- and a person who is not told simply sees tracking that
    does not fit and mistrusts the tracking (never block, always inform).

    Once per source: a retry on every video load would train them to dismiss it.
    """
    name = Path(source_id).name
    logger.warning(
        "Cannot align overlay %s to %s: tracking frame indices do not fit the video.",
        video,
        name,
    )
    announced = getattr(window, "_announced_uncalibrated_overlays", None)
    if announced is None or source_id in announced:
        return
    announced.add(source_id)
    window.notifications.show_warning(
        tr(
            "{source} could not be aligned to {video}'s own frame times, so it is drawn "
            "at its assumed frame rate and may drift from the video by a few frames."
        ).format(source=name, video=Path(video).name)
    )
