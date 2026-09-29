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

import numpy as np
from PySide6.QtCore import QThread, QTimer

from avialsync.core.channel_reader import ChannelKey
from avialsync.core.errors import FileUnreadableError, LoaderContractError, SourceOpenError
from avialsync.core.inspection import SourceInspection
from avialsync.core.pose import PoseSchema
from avialsync.core.source import TimeSeriesSource
from avialsync.ui.controllers import identity_controller
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

#: Stands in for a rate no loaded camera can supply yet. Never the final word:
#: an import that uses it is flagged provisional and re-run when one arrives.
_ASSUMED_FPS = 30.0


def _has_pose_coordinates(pose: PoseSchema | None, axes: tuple[str, ...]) -> bool:
    """Whether one point carries every coordinate a declared pose role needs.

    The loader's own schema is the only answer (D-140). A source that declares
    none is not a pose source, and the role falls back to plain channels with
    the notification the caller already raises.
    """
    return pose is not None and bool(pose.points_with(*axes))


# ── Time-series intake ───────────────────────────────────────────────


def start_data_import(
    window: MainWindow,
    path: Path,
    loader_cls: type[TimeSeriesSource] | None = None,
    pre_config: dict | None = None,
    *,
    restoring: bool = False,
) -> None:
    if loader_cls is None:
        discovered_loader = window._registry.find_best_loader(path)
        if discovered_loader is None:
            # Reported, not refused with a modal in the way (AGENTS rules 10 and
            # 12): `SourceOpenError`'s presentation already names "a format
            # AvialSync has no loader for" as one of its causes, and offers
            # Locate and Copy diagnostics with it.
            window.report_failure(
                SourceOpenError(f"No installed loader claims {path.name}"),
                doing=f"opening {path.name}",
            )
            return
        if not issubclass(discovered_loader, TimeSeriesSource):
            window.report_failure(
                LoaderContractError(
                    f"{discovered_loader.__name__} claimed {path.name} but is not a "
                    "time-series source"
                ),
                doing=f"opening {path.name}",
            )
            return
        loader_cls = discovered_loader

    config = pre_config or {}

    if getattr(loader_cls, "needs_import_wizard", lambda: False)():
        if not restoring and not config.get("auto_resolved"):
            from avialsync.ui.import_wizard import ImportWizard

            wizard = ImportWizard(path, window)
            if wizard.exec() != ImportWizard.DialogCode.Accepted:
                return
            # The import review may have assigned a pose role or camera before
            # this loader asks how to parse its time column. Keep that choice.
            config = {**config, **wizard.config()}
    elif config.get("_is_frame_indexed") or loader_cls().is_frame_indexed():
        # A frame rate already in the config is a decision -- a restored
        # session's, or a session scanner's -- and is not re-derived here.
        if "fps" not in config:
            fps, provisional = frame_rate_for_tracking(window, config)
            config["fps"] = fps
            config["fps_provisional"] = provisional
        if config.get("fps_provisional"):
            # Imported anyway, at an assumed rate, and re-imported the moment a
            # camera can date these frames (rule 10: never block, always
            # inform). The quality badge carries the "assumed" until then.
            window._frame_indexed_sources.append((path, loader_cls, config))

    window._enqueue_import(path, loader_cls, config)


def frame_rate_for_tracking(window: MainWindow, config: dict[str, Any]) -> tuple[float, bool]:
    """Return ``(fps, provisional)`` for a frame-indexed source, asking nothing.

    A tracking file counts frames; only the camera that exposed them knows how
    fast they came. Asking the user is asking them to read a number off the
    video and type it back in, and the dialog this replaced also *discarded*
    what they typed in its one-video case -- it returned the pre-filled rate
    whatever the field said (D-137).

    ``provisional`` means nothing loaded can answer yet and the rate returned is
    an assumption. The caller flags the import, which is what raises the "Frame
    rate assumed, not read" badge, and re-imports once a camera arrives.
    """
    declared = str(config.get("overlay_video", ""))
    if declared:
        # The user has already said which camera these frames belong to; that
        # declaration is the answer, and no other video may override it.
        rate = window._video_fps.get(declared)
        return (float(rate), False) if rate else (_ASSUMED_FPS, True)

    rates = [float(rate) for rate in window._video_fps.values() if rate > 0.0]
    if not rates:
        return _ASSUMED_FPS, True
    if len({round(rate, 6) for rate in rates}) == 1:
        # One camera, or several agreeing: there is nothing to choose between.
        return rates[0], False
    # Cameras at different rates and nothing saying which these frames index.
    # Placed against the first rather than refused, and the badge says it is a
    # guess -- naming the camera is the user's to do in the import review.
    return rates[0], True


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
    from avialsync.engine.importer import ImportWorker

    # The local is what `_wire` closes over. `window._import_worker` is typed
    # `QObject | None`, and that narrowing does not survive into a nested
    # function -- so reading it back inside `_wire` costs an assert and three
    # `attr-defined` errors rather than buying anything.
    # The session's declared zero travels with the import. A loader reading
    # clock times -- "09:35:40" -- needs a date to place them on, and when the
    # session already knows when it happened, asking the user again is asking
    # them to retype what the application has. An explicit anchor from the
    # wizard always wins; the loader decides.
    config = dict(config)
    config.setdefault("session_start_time", window.session_start_time)

    worker = ImportWorker(path, config, loader_cls)
    window._import_worker = worker

    # No modal dialog (D-091). The work was always on a worker; the modality
    # was gratuitous, and the budget allows a 1 GB CSV sixty seconds -- a full
    # minute during which the window could not be touched.
    window.activity_bar.begin(f"Importing {path.name}")
    window._active_cancel = worker.cancel

    def _wire(thread: QThread) -> None:
        # Assigned here, not from `_run_job`'s return value: that returns an
        # already-running thread, so a fast import can finish -- and
        # `_on_import_thread_finished` can clear this back to None -- before
        # the assignment lands. The stale handle would then gate every later
        # import forever, since `enqueue_import` treats non-None as "busy".
        window._import_thread = thread
        worker.progress.connect(window.activity_bar.set_progress)
        worker.finished.connect(window._on_import_finished)
        worker.error.connect(window._on_import_error)
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
        thread.finished.connect(window._on_import_thread_finished)

    # Registered rather than hand-wired (D-107), so the import appears in the
    # Tasks panel beside every other job, is watched for stalls, and is
    # abandoned in the ordinary way at shutdown. `JobManager` already connects
    # `started -> run` and quits the thread on `finished`/`error`, so those
    # four connections are gone from here rather than duplicated.
    window._run_job(worker, label=f"Importing {path.name}", configure=_wire)


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


def rebind_frame_indexed_sources(window: MainWindow) -> None:
    """Re-import provisional frame-indexed sources now a camera can date them.

    Each source resolves its own rate: two tracking files may name two cameras,
    and the one whose camera is still missing stays provisional rather than
    being dated by somebody else's video.
    """
    from avialsync.core.cache import CacheManager

    pending = list(window._frame_indexed_sources)
    window._frame_indexed_sources.clear()
    for dlc_path, loader_cls, config in pending:
        fps, provisional = frame_rate_for_tracking(window, config)
        if provisional:
            window._frame_indexed_sources.append((dlc_path, loader_cls, config))
            continue
        cache_dir = CacheManager(loader_version=5).get_cache_dir(dlc_path)
        window.plot_pane.remove_channels(cache_dir)
        window.sidebar.remove_sensor(str(dlc_path))
        config["fps"] = fps
        config["fps_provisional"] = False
        window._enqueue_import(dlc_path, loader_cls, config)


def on_import_finished(
    window: MainWindow,
    path: str,
    cache_dir: str,
    channels: list[str],
    bounds: tuple[float, float],
    inspection: object = None,
) -> None:
    window.activity_bar.end()
    window._active_cancel = None
    window.notifications.show_success(f"Imported {Path(path).name}")
    offset, drift_ppm = window._pending_sensor_mappings.pop(path, (0.0, 0.0))

    role = ""
    if isinstance(inspection, SourceInspection):
        role = str(inspection.import_config.get("role", ""))
        # If the config explicitly provides an offset (e.g. from drop_worker or wizard), use it.
        if "offset" in inspection.import_config and offset == 0.0:
            offset = float(inspection.import_config["offset"])
        if "drift_ppm" in inspection.import_config and drift_ppm == 0.0:
            drift_ppm = float(inspection.import_config["drift_ppm"])

    if role in ("pose3d", "overlay2d"):
        required = ("x", "y", "z") if role == "pose3d" else ("x", "y")
        target = (
            inspection.import_config.get("overlay_video")
            if isinstance(inspection, SourceInspection)
            else None
        )
        pose = inspection.pose if isinstance(inspection, SourceInspection) else None
        if not _has_pose_coordinates(pose, required) or (role == "overlay2d" and not target):
            window.notifications.show_warning(
                tr(
                    "{file} has no usable {kind} coordinates; its channels were plotted instead."
                ).format(
                    file=Path(path).name,
                    kind=tr("3D pose") if role == "pose3d" else tr("2D pose"),
                )
            )
            if isinstance(inspection, SourceInspection):
                inspection.import_config.pop("role", None)
                inspection.import_config.pop("overlay_video", None)
            role = ""

    # NWB's zero. A source carrying wall-clock time is placed against the
    # session reference instead of sitting 1.7e9 seconds from a
    # container-relative video, which is how the master timeline came to be
    # fifty-four years long with two short islands at its ends.
    #
    # The placement is kept apart from whatever the user or the wizard asked
    # for, and only the latter reaches the sidebar. Adding them into one number
    # is what made `set_sensor_mapping` hand an `epoch_ms` file's 1.77e9 to a
    # spin box ranged at a day: it clamped to 86400 s, silently, and that clamp
    # was then what the session saved (D-026).
    base = window.declare_base_offset(path, bounds[0])
    if offset == 0.0:
        # Nothing more specific was asked for, so the placement is the mapping.
        # An explicit offset -- from the wizard, a drop, or a restored session
        # -- is already the whole mapping and wins.
        offset = base
    user_offset = window.user_offset(path, offset)

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
    window.transport.set_source_coverage(
        path, mapped[0], mapped[1], "data", window.coverage_group_for(path)
    )
    window._recompute_bounds()
    window.sidebar.add_sensor(path, channels)
    window.sidebar.set_sensor_identity_count(path, window.identity_swaps.count_for(path))
    if user_offset or drift_ppm:
        window.sidebar.set_sensor_mapping(path, user_offset, drift_ppm)
    window._recorded_mappings[path] = (user_offset, drift_ppm)

    if isinstance(inspection, SourceInspection):
        window._inspections[path] = inspection
        window.sidebar.set_sensor_inspection(path, inspection)
        window.refresh_alignment_badges()
        # Messages arrive in source time, so the mapping goes in first: setting
        # them the other way round would emit a change the panel renders at the
        # unmapped position before the correction lands.
        if inspection.messages:
            window.message_store.set_source_mapping(path, offset, drift_ppm)
            window.message_store.set_source_messages(path, inspection.messages)
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
        from avialsync.ui.controllers import custom_marker_controller, wheel_files

        custom_marker_controller.adopt(window)
        wheel_files.adopt(window)
        return

    video = str(config.get("overlay_video", ""))
    if not video:
        logger.warning("2D pose source %s has no overlay target; skipping.", path)
        return

    # The loader said which points exist and what they are called; this no
    # longer re-derives them by splitting ``_x`` off a channel name, which is
    # what let two animals sharing ``snout`` collapse into one point (D-140).
    points: dict[str, tuple[MappedChannelReader, MappedChannelReader]] = {}
    available = set(channels)

    def _reader(channel: str) -> MappedChannelReader:
        return MappedChannelReader(PyramidReader(cache_dir, channel), time_map, source_id=path)

    pose = inspection.pose if isinstance(inspection, SourceInspection) else None
    if pose is None:
        logger.warning("2D pose source %s declares no pose schema; not overlaid.", path)
        return
    for point in pose.points_with("x", "y"):
        x_channel, y_channel = point.channel("x"), point.channel("y")
        if x_channel in available and y_channel in available:
            points[point.name] = (_reader(x_channel), _reader(y_channel))

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
        "frame_rate": float(config.get("fps", 0.0)),
    }
    # What this source is and where it was imported to, kept because an
    # identity swap has to rebuild its channels and re-point its readers
    # without re-reading the file (D-142).
    window._pose_schemas[path] = pose
    window._pose_cache_dirs[path] = cache_dir
    calibrate_overlay_timing(window, video)
    # Whatever the user already corrected on this recording, wherever the
    # session it was corrected in has got to (D-099). After registration
    # because the sidecar speaks video frame numbers and the conversion back to
    # sample indices needs this source's own time column; before the tracks are
    # published, so the pane's first paint is already the corrected one.
    window._adopt_point_edits(path)
    # After the corrections, because both feed one edit program and the
    # generation it names has to be built from the whole of it; before the
    # tracks are published, so the pane's first paint is already the edited one.
    identity_controller.adopt(window, path)
    window._refresh_overlays(video)
    # Markers and wheels placed on this recording, now its camera's pose file is known.
    from avialsync.ui.controllers import custom_marker_controller, wheel_files

    custom_marker_controller.adopt(window)
    wheel_files.adopt(window)


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


def _report_uncalibrated_overlay(window: MainWindow, video: str, source_id: str) -> None:
    """Say that an overlay is drawn on assumed timing rather than the video's own.

    Not a log line. Uniform ``index / fps`` timing drifts from a real
    recording's presentation times by up to 0.16 s -- five frames at 30 fps, on
    top of the animal -- and a person who is not told simply sees tracking that
    does not fit and mistrusts the tracking (Law 1: never block, always inform).

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

    An always-present empty pane keeps a quarter of the media width and raises
    the window's minimum width for sessions that have no tracking data.
    """
    has_points = (
        window.tracking_3d_pane.canvas.point_count > 0
        or len(window.custom_markers) > 0
        or len(window.wheels) > 0
        or window._wheel_placement is not None
    )
    if window.tracking_3d_pane.isVisible() == has_points:
        return
    window.tracking_3d_pane.setVisible(has_points)
    if has_points:
        width = max(window._media_splitter.width(), 600)
        window._media_splitter.setSizes([int(width * 0.75), int(width * 0.25)])
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
    window.activity_bar.end()
    window._active_cancel = None
    window.transport.set_status("Data import failed", "error")

    # Name the format that actually failed. This said "Failed to import CSV"
    # whatever the loader was, so an ephys directory read by the wrong format
    # reported a CSV problem and pointed at nothing the user had chosen.
    worker = getattr(window, "_import_worker", None)
    loader_cls = getattr(worker, "loader_class", None)
    fmt = loader_cls.display_name() if loader_cls is not None else "data"
    source = Path(worker.path).name if worker is not None else ""
    heading = f"Failed to import {source} as {fmt}" if source else f"Failed to import {fmt}"

    window.report_failure(FileUnreadableError(err_msg), doing=heading)
