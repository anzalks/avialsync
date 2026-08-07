"""Time-series import and pose routing.

One import worker owns the modal progress dialog at a time; later requests
queue behind it.  Pose data is routed to the video overlay or the 3D view
rather than a plot row, because 27 3D channels or 81 per-camera 2D channels
would bury the recorded signals a plot is meant to show.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import QMessageBox

from avialsync.core.channel_reader import ChannelKey
from avialsync.core.inspection import SourceInspection
from avialsync.core.source import TimeSeriesSource

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


# ── Time-series intake ───────────────────────────────────────────────


def start_data_import(
    window: MainWindow,
    path: Path,
    loader_cls: type[TimeSeriesSource] | None = None,
    pre_config: dict | None = None,
) -> None:
    if loader_cls is None:
        discovered_loader = window._registry.find_best_loader(path)
        if discovered_loader is None:
            QMessageBox.warning(
                window, "Unsupported File", "No suitable loader found for this file."
            )
            return
        if not issubclass(discovered_loader, TimeSeriesSource):
            QMessageBox.warning(
                window, "Unsupported File", "The selected loader is not time-series data."
            )
            return
        loader_cls = discovered_loader

    config = pre_config or {}

    if getattr(loader_cls, "needs_import_wizard", lambda: False)():
        if not config.get("auto_resolved"):
            from avialsync.ui.import_wizard import ImportWizard

            wizard = ImportWizard(path, window)
            if wizard.exec() != ImportWizard.DialogCode.Accepted:
                return
            config = wizard.config()
    elif config.get("_is_frame_indexed") or loader_cls().is_frame_indexed():
        if not config.get("auto_resolved") and "fps" not in config:
            fps, ok = window._resolve_tracking_fps()
            if not ok:
                return
            config["fps"] = fps

        if not window._video_fps:
            window._frame_indexed_sources.append((path, loader_cls, config))

    window._enqueue_import(path, loader_cls, config)


def resolve_tracking_fps(window: MainWindow) -> tuple[float, bool]:
    """Return (fps, ok) for a frame-indexed source, using loaded video fps when possible."""
    from PySide6.QtWidgets import QInputDialog

    n = len(window._video_fps)
    if n == 1:
        fps = next(iter(window._video_fps.values()))
        _, ok = QInputDialog.getDouble(
            window,
            "Confirm Frame Rate",
            "Frame rate for this tracking data (pre-filled from loaded video):",
            fps,
            1.0,
            1000.0,
            2,
        )
        return fps, ok
    if n > 1:
        items = list(window._video_fps.keys())
        picked, ok = QInputDialog.getItem(
            window,
            "Select Video for Frame Rate",
            "Use frame rate from which video?",
            items,
            0,
            False,
        )
        return (window._video_fps[picked], ok) if ok else (30.0, False)
    # No videos loaded — ask user for nominal fps
    fps, ok = QInputDialog.getDouble(
        window,
        "Tracking Data FPS",
        "Enter the video frame rate for this tracking data:",
        30.0,
        1.0,
        1000.0,
        2,
    )
    return fps, ok


def enqueue_import(
    window: MainWindow, path: Path, loader_cls: type, config: dict[str, Any]
) -> None:
    """Queue a source import so only one worker owns the import UI at a time."""
    if window._import_thread is not None:
        window._pending_imports.append((path, loader_cls, config))
        return
    window._start_import(path, loader_cls, config)


def start_import(window: MainWindow, path: Path, loader_cls: type, config: dict[str, Any]) -> None:
    """Start the next queued background import."""
    from PySide6.QtWidgets import QProgressDialog

    from avialsync.engine.importer import ImportWorker

    window._import_thread = QThread()
    window.transport.set_status(f"Importing data: {path.name}", "busy")
    window._import_worker = ImportWorker(path, config, loader_cls)
    window._import_worker.moveToThread(window._import_thread)

    window._progress_dialog = QProgressDialog("Importing…", "Cancel", 0, 100, window)
    window._progress_dialog.setWindowTitle("Importing Data")
    window._progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
    window._progress_dialog.setAutoClose(True)
    window._progress_dialog.setAutoReset(True)
    window._progress_dialog.setValue(0)

    window._import_thread.started.connect(window._import_worker.run)
    window._import_worker.progress.connect(window._progress_dialog.setValue)
    window._progress_dialog.canceled.connect(window._import_worker.cancel)

    window._import_worker.finished.connect(window._on_import_finished)
    window._import_worker.finished.connect(window._import_thread.quit)
    # The worker is released in `_on_import_thread_finished`, on this
    # thread. It must NOT be `deleteLater`-ed from its own `finished`:
    # that signal is emitted in the worker thread, the worker lives there
    # too, so the connection is direct and ~QObject then runs inside the
    # worker's event loop. Destroying a QObject severs its connections
    # while holding one of Qt's 131 *pooled* signal/slot mutexes, and
    # PySide's `disconnectNotify` override takes the GIL to look for a
    # Python override. Meanwhile the GUI thread holds the GIL and closes
    # the progress dialog, which waits on a mutex from that same pool.
    # Colliding addresses deadlock both threads permanently (D-062).
    window._import_thread.finished.connect(window._import_thread.deleteLater)
    window._import_thread.finished.connect(window._on_import_thread_finished)

    window._import_worker.error.connect(window._on_import_error)
    window._import_worker.error.connect(window._import_thread.quit)

    window._progress_dialog.show()
    window._import_thread.start()


def on_import_thread_finished(window: MainWindow) -> None:
    """Release the completed import and begin the next queued source."""
    window._import_thread = None
    # Dropping the last reference destroys the worker here, on the GUI
    # thread, which already holds the GIL that ~QObject needs to sever the
    # progress dialog's `canceled` connection.
    window._import_worker = None
    if not window._pending_imports:
        return
    path, loader_cls, config = window._pending_imports.popleft()
    QTimer.singleShot(0, lambda: window._start_import(path, loader_cls, config))


def rebind_frame_indexed_sources(window: MainWindow, fps: float) -> None:
    """Re-import all provisional frame-indexed sources using the video fps."""
    from avialsync.core.cache import CacheManager

    for dlc_path, loader_cls, config in window._frame_indexed_sources:
        cache_dir = CacheManager(loader_version=3).get_cache_dir(dlc_path)
        window.plot_pane.remove_channels(cache_dir)
        window.sidebar.remove_sensor(str(dlc_path))
        config["fps"] = fps
        window._enqueue_import(dlc_path, loader_cls, config)
    window._frame_indexed_sources.clear()


def on_import_finished(
    window: MainWindow,
    path: str,
    cache_dir: str,
    channels: list[str],
    bounds: tuple[float, float],
    inspection: object = None,
) -> None:
    progress_dialog = getattr(window, "_progress_dialog", None)
    if progress_dialog is not None:
        progress_dialog.close()
    offset, drift_ppm = window._pending_sensor_mappings.pop(path, (0.0, 0.0))

    role = ""
    if isinstance(inspection, SourceInspection):
        role = str(inspection.import_config.get("role", ""))
        # If the config explicitly provides an offset (e.g. from drop_worker or wizard), use it.
        if "offset" in inspection.import_config and offset == 0.0:
            offset = float(inspection.import_config["offset"])
        if "drift_ppm" in inspection.import_config and drift_ppm == 0.0:
            drift_ppm = float(inspection.import_config["drift_ppm"])

    if role in ("overlay2d", "pose3d"):
        # Pose data drives the video overlay and the 3D view. It is not
        # plotted: 27 3D channels or 81 per-camera 2D channels would bury
        # the recorded signals a plot row is meant to show.
        window._register_tracking_source(
            path, Path(cache_dir), channels, role, inspection, offset, drift_ppm
        )
        if offset != 0.0 or drift_ppm != 0.0:
            from avialsync.core.timeline import TimeMap

            tm = TimeMap(offset=offset, drift_ppm=drift_ppm)
            mapped = (tm.to_master(bounds[0]), tm.to_master(bounds[1]))
        else:
            mapped = bounds
    else:
        window.plot_pane.load_channels(Path(cache_dir), channels, offset, drift_ppm, source_id=path)
        window._sensor_cache_dirs[path] = Path(cache_dir)
        # Rows are built across several event-loop turns so the window stays
        # usable during a large selection (D-060), so reader-derived bounds
        # may not exist yet. The worker's bounds are the correct stand-in
        # until they do; `_refine_source_bounds` re-applies the exact span
        # once every row exists.
        mapped = window.plot_pane.source_bounds(Path(cache_dir)) or bounds
        window._pending_bounds_sources[path] = Path(cache_dir)
    window._update_bounds(mapped[0], mapped[1])
    window.transport.set_source_coverage(path, mapped[0], mapped[1], "data")
    window.sidebar.add_sensor(path, channels)
    if offset or drift_ppm:
        window.sidebar.set_sensor_mapping(path, offset, drift_ppm)

    if isinstance(inspection, SourceInspection):
        window._inspections[path] = inspection
        window.sidebar.set_sensor_inspection(path, inspection)
        # Extract per-channel units from import config ("units" key → dict or mapping)
        units_cfg = inspection.import_config.get("units", {})
        if isinstance(units_cfg, dict):
            # Units are source-scoped: two files may both declare "force_z"
            # in different units and neither may relabel the other's row.
            scoped: dict[ChannelKey | str, str] = {
                ChannelKey(path, str(channel)): str(unit) for channel, unit in units_cfg.items()
            }
            window._channel_units.update(
                {key: unit for key, unit in scoped.items() if isinstance(key, ChannelKey)}
            )
            window.plot_pane.set_channel_units(scoped)
        # Overlay gap markers on each channel from this source
        rep = inspection.import_report
        if rep and rep.gap_locations:
            gap_times = list(rep.gap_locations)
            window._overview_gaps.update({time: f"Source: {Path(path).name}" for time in gap_times})
            window.transport.set_gap_events(sorted(window._overview_gaps.items()))
            if not role:
                # Pose sources have no plot rows to mark.
                for ch in channels:
                    window.plot_pane.set_gap_markers(ch, gap_times)
    window.transport.set_status(f"Ready · imported {Path(path).name}")


# ── Pose sources (overlay + 3D view, never plotted) ──────────────────


def register_tracking_source(
    window: MainWindow,
    path: str,
    cache_dir: Path,
    channels: list[str],
    role: str,
    inspection: object,
    offset: float = 0.0,
    drift_ppm: float = 0.0,
) -> None:
    """Route imported pose data to the overlay or the 3D view.

    Readers are built straight from the source's own sidecar cache, so two
    cameras or two models that both emit ``head_bar_x`` stay separate without
    depending on globally unique channel names.
    """
    from avialsync.core.channel_reader import MappedChannelReader
    from avialsync.core.pyramid import PyramidReader
    from avialsync.core.timeline import TimeMap

    config: dict[str, Any] = {}
    if isinstance(inspection, SourceInspection):
        config = dict(inspection.import_config)

    time_map = TimeMap(offset=offset, drift_ppm=drift_ppm)

    if role == "pose3d":
        window._pose_3d_sources[path] = [
            MappedChannelReader(PyramidReader(cache_dir, channel), time_map, source_id=path)
            for channel in channels
        ]
        window._refresh_pose_3d()
        return

    video = str(config.get("overlay_video", ""))
    if not video:
        logger.warning("2D pose source %s has no overlay target; skipping.", path)
        return

    points: dict[str, tuple[MappedChannelReader, MappedChannelReader]] = {}
    by_name: dict[str, dict[str, MappedChannelReader]] = {}
    for channel in channels:
        base, separator, axis = channel.rpartition("_")
        if separator and axis in ("x", "y"):
            by_name.setdefault(base, {})[axis] = MappedChannelReader(
                PyramidReader(cache_dir, channel), time_map, source_id=path
            )
    for name, axes in by_name.items():
        if "x" in axes and "y" in axes:
            points[name] = (axes["x"], axes["y"])

    if not points:
        logger.warning("2D pose source %s produced no complete XY points.", path)
        return

    # Decide colours now, while the whole set of body parts for this source
    # is in hand, so the overlay and the 3D view agree from the first paint.
    from avialsync.ui.tracking_colors import register_points

    register_points(points)

    window._overlay_sources.setdefault(video, {})[path] = {
        "label": str(config.get("overlay_label", Path(path).stem)),
        "is_ensemble": bool(config.get("overlay_is_ensemble", False)),
        "points": points,
    }
    window._refresh_overlays(video)


def refresh_pose_3d(window: MainWindow) -> None:
    """Feed the 3D view from registered pose sources plus any plotted XYZ."""
    readers: list[Any] = list(window._plotted_readers)
    for source_readers in window._pose_3d_sources.values():
        readers.extend(source_readers)
    window.tracking_3d_pane.set_readers(readers)
    window.tracking_3d_pane.set_cursor(window.clock.state.t)
    window._update_tracking_pane_visibility()


def update_tracking_pane_visibility(window: MainWindow) -> None:
    """Show the 3D pane only while a source provides complete XYZ triplets.

    An always-present empty pane keeps a third of the media width and raises
    the window's minimum width for sessions that have no tracking data.
    """
    has_points = window.tracking_3d_pane.canvas.point_count > 0
    if window.tracking_3d_pane.isVisible() == has_points:
        return
    window.tracking_3d_pane.setVisible(has_points)
    if has_points:
        width = max(window._media_splitter.width(), 600)
        window._media_splitter.setSizes([int(width * 0.65), int(width * 0.35)])
    # Showing or hiding a pane changes which panes share the width, so the
    # split that results is the one to hold from here on.
    window._pane_proportions.record(window._media_splitter)


def refresh_overlays(window: MainWindow, video: str) -> None:
    """Rebuild one camera's overlay track list, ensemble last."""
    from avialsync.ui.video_overlay import OverlayTrack, track_color

    sources = window._overlay_sources.get(video, {})
    tracks: list[OverlayTrack] = []
    model_index = 0
    for _source_path, entry in sorted(
        sources.items(), key=lambda item: (not item[1]["is_ensemble"], item[1]["label"])
    ):
        is_ensemble = bool(entry["is_ensemble"])
        color = track_color(model_index, is_ensemble=is_ensemble)
        if not is_ensemble:
            model_index += 1
        tracks.append(
            OverlayTrack(
                label=str(entry["label"]),
                points=entry["points"],
                color=color,
                is_ensemble=is_ensemble,
            )
        )
    window.video_grid.set_overlay_tracks(video, tracks)


def on_import_error(window: MainWindow, err_msg: str) -> None:
    progress_dialog = getattr(window, "_progress_dialog", None)
    if progress_dialog is not None:
        progress_dialog.close()
    window.transport.set_status("Data import failed", "error")

    # Name the format that actually failed. This said "Failed to import CSV"
    # whatever the loader was, so an ephys directory read by the wrong format
    # reported a CSV problem and pointed at nothing the user had chosen.
    worker = getattr(window, "_import_worker", None)
    loader_cls = getattr(worker, "loader_class", None)
    fmt = loader_cls.display_name() if loader_cls is not None else "data"
    source = Path(worker.path).name if worker is not None else ""
    heading = f"Failed to import {source} as {fmt}" if source else f"Failed to import {fmt}"

    QMessageBox.critical(window, "Import Error", f"{heading}:\n{err_msg}")
