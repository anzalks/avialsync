"""UI-thread snapshot builders for calibrated 3D-to-2D reprojected pose exports."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from avialsync.core import calibration_ref
from avialsync.core.calibration import corrected, read_calibration
from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.errors import CalibrationError
from avialsync.core.inspection import SourceInspection
from avialsync.core.pose import split_channel
from avialsync.core.reprojected_pose_export import reprojected_copy_path
from avialsync.core.sidecar_names import on_disk
from avialsync.core.timeline import TimeMap
from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.reprojected_pose_job import ReprojectedPoseJob
from avialsync.ui.controllers import calibration_controller, rig_paths
from avialsync.ui.controllers.calibration_controller import CalibrationState
from avialsync.ui.export_dialog import REPROJECTED_POSE, ExportItem
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

__all__ = [
    "can_export_reprojected_pose",
    "ensure_reprojection_ready",
    "reprojected_export_items",
    "reprojected_job_for",
]


def can_export_reprojected_pose(window: MainWindow) -> bool:
    """Return whether 3D pose and calibrated (or calibratable) cameras are present."""
    videos = window.video_grid.pane_paths()
    if not videos or not _pose_3d_ids(window):
        return False
    state = _quiet_calibration_state(window)
    if state is not None and any(video in state.cameras for video in videos):
        return True
    return len(videos) >= 2 and rig_paths.pose3d_dir(window.rig_paths) is not None


def ensure_reprojection_ready(
    window: MainWindow,
    *,
    has_manual_changes: bool,
    proceed: Callable[[], None],
) -> bool:
    """Acquire calibration when Export Changes was invoked solely for 3D reprojections.

    Returns True when an asynchronous or modal calibration step took over and
    will invoke *proceed* once ready.
    """
    if has_manual_changes:
        return False
    state = _quiet_calibration_state(window)
    if state is not None and any(v in state.cameras for v in window.video_grid.pane_paths()):
        return False
    if not can_export_reprojected_pose(window):
        return False
    calibration_controller.acquire_calibration(window, proceed, lambda: None)
    return True


def reprojected_export_items(window: MainWindow, *, has_manual_changes: bool) -> list[ExportItem]:
    """List one ``*_reprojected.csv`` export row per calibrated camera and 3D pose."""
    state = _quiet_calibration_state(window)
    if state is None or not state.cameras:
        return []
    pose_ids = _pose_3d_ids(window)
    items: list[ExportItem] = []
    for pose_id in pose_ids:
        if not _triplets_for(window, pose_id):
            continue
        suffix = f" ({Path(pose_id).name})" if len(pose_ids) > 1 else ""
        for video in window.video_grid.pane_paths():
            if video not in state.cameras:
                continue
            items.append(
                _item_for_camera(window, pose_id, video, suffix, selected=not has_manual_changes)
            )
    return items


def _item_for_camera(
    window: MainWindow,
    pose_id: str,
    video: str,
    suffix: str,
    *,
    selected: bool,
) -> ExportItem:
    pose_2d = rig_paths.pose_2d_file(window.rig_paths, video)
    if pose_2d is not None:
        disk_source = on_disk(pose_2d)
        target = reprojected_copy_path(disk_source)
        label = disk_source.name
        detail = tr(
            "A copy of {file} with matched x/y columns replaced by calibrated "
            "3D-to-2D projections; header, scorer, and likelihood stay untouched."
        ).format(file=disk_source.name)
    else:
        disk_video = on_disk(video)
        target = reprojected_copy_path(disk_video)
        label = disk_video.name
        detail = tr(
            "Calibrated 3D-to-2D projected pose coordinates on {video}'s frame grid."
        ).format(video=disk_video.name)
    return ExportItem(
        kind=REPROJECTED_POSE,
        title=tr("Reprojected 2D pose — {source}").format(source=f"{label}{suffix}"),
        detail=detail,
        target=target,
        source_id=pose_id,
        video=video,
        selected=selected,
    )


def reprojected_job_for(window: MainWindow, item: ExportItem) -> ReprojectedPoseJob | None:
    """Snapshot readers, calibration, and camera frame grid for worker execution."""
    state = _quiet_calibration_state(window)
    camera = state.cameras.get(item.video) if state is not None else None
    triplets = _triplets_for(window, item.source_id)
    if state is None or camera is None or not triplets:
        return None
    axes = {
        name: (
            ReaderReference.from_reader(rx),
            ReaderReference.from_reader(ry),
            ReaderReference.from_reader(rz),
        )
        for name, (rx, ry, rz) in triplets.items()
    }
    pose_2d = rig_paths.pose_2d_file(window.rig_paths, item.video)
    disk_2d = on_disk(pose_2d) if pose_2d is not None else None
    template_2d = disk_2d if disk_2d is not None and disk_2d.is_file() else None
    raw_times = window._video_frame_times.get(item.video)
    frame_times = (
        np.asarray(raw_times, dtype=np.float64).copy()
        if raw_times is not None and len(raw_times) > 0
        else None
    )
    tmap = window.video_grid.time_map_for(item.video)
    if tmap is not None:
        video_time_map = tmap.copy()
    elif item.video in window._video_time_mappings:
        offset, drift = window._video_time_mappings[item.video]
        video_time_map = TimeMap(offset=offset, drift_ms_per_hour=drift)
    else:
        video_time_map = TimeMap()
    session = Path(window.session_runtime.path) if window.session_runtime.path else None
    return ReprojectedPoseJob(
        target=item.target,
        video=on_disk(item.video),
        camera=camera,
        pose_3d_source=on_disk(item.source_id),
        calibration_path=state.path,
        axes=axes,
        video_time_map=video_time_map,
        template_2d=template_2d,
        frame_times=frame_times,
        point_labels=_point_labels_for(window, item.source_id),
        session=session,
    )


def _pose_3d_ids(window: MainWindow) -> list[str]:
    return [
        source_id
        for source_id in sorted(window._pose_3d_sources)
        if window._tracking_visibility.get(source_id, {}).get("overlay", True)
    ]


def _triplets_for(
    window: MainWindow, source_id: str
) -> dict[str, tuple[MappedChannelReader, MappedChannelReader, MappedChannelReader]]:
    readers = window._pose_3d_sources.get(source_id, [])
    by_channel = {r.channel_id: r for r in readers if isinstance(r, MappedChannelReader)}
    inspection = window._inspections.get(source_id)
    pose = inspection.pose if isinstance(inspection, SourceInspection) else None
    triplets: dict[str, tuple[MappedChannelReader, MappedChannelReader, MappedChannelReader]] = {}
    if pose is not None:
        for point in pose.points_with("x", "y", "z"):
            cx, cy, cz = point.channel("x"), point.channel("y"), point.channel("z")
            if cx in by_channel and cy in by_channel and cz in by_channel:
                triplets[point.name] = (by_channel[cx], by_channel[cy], by_channel[cz])
        if triplets:
            return triplets
    grouped: dict[str, dict[str, MappedChannelReader]] = {}
    for channel_id, reader in by_channel.items():
        split = split_channel(channel_id)
        if split is not None:
            grouped.setdefault(split[0], {})[split[1]] = reader
    for name, axes in grouped.items():
        if set(axes) == {"x", "y", "z"}:
            triplets[name] = (axes["x"], axes["y"], axes["z"])
    return triplets


def _point_labels_for(window: MainWindow, source_id: str) -> dict[str, tuple[str, str]] | None:
    inspection = window._inspections.get(source_id)
    pose = inspection.pose if isinstance(inspection, SourceInspection) else None
    if pose is None or not pose.multi_animal:
        return None
    return {
        point.name: (point.individual, point.bodypart) for point in pose.points_with("x", "y", "z")
    }


def _quiet_calibration_state(window: MainWindow) -> CalibrationState | None:
    calibration_controller.calibration_quietly(window)
    if window._calibration_state is not None:
        return window._calibration_state
    videos = window.video_grid.pane_paths()
    folder = rig_paths.pose3d_dir(window.rig_paths) if videos else None
    link = calibration_ref.locate(folder) if folder is not None else None
    if link is None or not link.calibration.is_file():
        return None
    try:
        hints = window.session_runtime.camera_corrections
        cal = corrected(
            read_calibration(link.calibration),
            [(h.camera, h.correction) for h in hints],
        )
    except CalibrationError:
        return None
    names = calibration_ref.camera_names(cal, list(videos), link.sources)
    cameras = {
        video: model for video, name in names.items() if (model := cal.camera(name)) is not None
    }
    return CalibrationState(path=link.calibration, cameras=cameras) if cameras else None
