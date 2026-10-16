"""Capture and resolve a prop's own cameras without reading calibration files."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING

from avialsync.core.calibration import CameraModel
from avialsync.core.prop_context import PropCamera, PropContext
from avialsync.core.wheel import Wheel
from avialsync.ui.controllers import rig_paths, wheel_display
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.core.physical_props import PhysicalProp
    from avialsync.ui.main_window import MainWindow
    from avialsync.ui.video_pane import VideoPane


def capture(window: MainWindow, frame: int | None = None) -> PropContext:
    """Record effective cameras and the reference camera's raw presentation time."""
    paths = rig_paths.open_videos(window.rig_paths)
    cameras = wheel_display.camera_models(window)
    snapshots = tuple(
        dataclasses.replace(
            PropCamera.capture(path, cameras[rig_paths.camera_name(path)]),
            name=rig_paths.camera_name(path),
        )
        for path in paths
        if rig_paths.camera_name(path) in cameras
    )
    if not snapshots:
        return PropContext()
    reference = snapshots[0]
    index = paths.index(reference.source)
    times = window._video_frame_times.get(reference.source)
    raw_time = (
        float(times[frame])
        if frame is not None and times is not None and 0 <= frame < len(times)
        else None
    )
    if raw_time is None and index < len(window.video_grid.panes):
        _, raw_time = window.video_grid.panes[index].frame_record_at(window.clock.state.t)
    return PropContext(
        snapshots, reference.name if index < len(window.video_grid.panes) else "", raw_time
    )


def camera_for(prop: PhysicalProp, video: str) -> CameraModel | None:
    """Match the resolved recorded source; a reused basename is not proof of ownership."""
    for camera in prop.context.cameras:
        if camera.source == video:
            return camera.model
    return None


def models(window: MainWindow, prop: PhysicalProp) -> dict[str, CameraModel]:
    """Saved context is the authority; live calibration is only for unsaved drafts."""
    if prop.context.cameras:
        return {camera.name: camera.model for camera in prop.context.cameras}
    return wheel_display.camera_models(window)


def _reference_pane(window: MainWindow, prop: PhysicalProp) -> tuple[str, VideoPane] | None:
    reference = next(
        camera for camera in prop.context.cameras if camera.name == prop.context.reference_camera
    )
    paths = rig_paths.open_videos(window.rig_paths)
    matches = [path for path in paths if path == reference.source]
    if len(matches) != 1:
        return None
    index = paths.index(matches[0])
    return (
        (matches[0], window.video_grid.panes[index])
        if index < len(window.video_grid.panes)
        else None
    )


def frame_and_time(
    window: MainWindow, prop: PhysicalProp, t_master: float
) -> tuple[int, float] | None:
    """Name a prop frame with its saved reference camera, independent of pane order."""
    if not prop.context.reference_camera:
        return wheel_display.frame_and_time(window, t_master)
    found = _reference_pane(window, prop)
    if found is None:
        return None
    _, pane = found
    index, pts = pane.frame_record_at(t_master)
    return int(index), float(pane.time_map.to_master(pts))


def frame_master_time(window: MainWindow, prop: PhysicalProp, frame: int) -> float | None:
    """Look up evidence on the saved reference camera through its live mapping."""
    if not prop.context.reference_camera:
        return wheel_display.frame_master_time(window, frame)
    found = _reference_pane(window, prop)
    if found is None:
        return None
    path, pane = found
    times = window._video_frame_times.get(path)
    if times is None or not 0 <= frame < len(times):
        return None
    return float(pane.time_map.to_master(float(times[frame])))


def reference_time(window: MainWindow, prop: PhysicalProp) -> float | None:
    """The placed frame's raw time through the reference camera's current mapping."""
    if not prop.context.reference_camera:
        return (
            wheel_display.frame_master_time(window, prop.frame) if isinstance(prop, Wheel) else None
        )
    found = _reference_pane(window, prop)
    if found is None or prop.context.reference_time is None:
        return None
    return float(found[1].time_map.to_master(prop.context.reference_time))


def wheel_status(window: MainWindow, wheel: Wheel) -> str:
    """Explain a loaded wheel's display dependencies without probing any files."""
    messages = []
    if wheel.context.reference_camera:
        messages.append(
            tr("Saved projection · reference camera: {camera}.").format(
                camera=wheel.context.reference_camera
            )
        )
        if frame_and_time(window, wheel, window.clock.state.t) is None:
            messages.append(
                tr("Open {camera} to display this wheel's rotation.").format(
                    camera=wheel.context.reference_camera
                )
            )
    elif not wheel.context.cameras:
        messages.append(tr("No saved camera projection; load a matching calibration for overlays."))
    if wheel.binding is None:
        messages.append(
            tr("No encoder bound; bars are shown only at placement frame {frame}.").format(
                frame=wheel.frame
            )
        )
    elif not any(
        row.reader.cache_dir == window._sensor_cache_dirs.get(wheel.binding.source_id)
        and row.reader.channel_id == wheel.binding.channel
        for row in window.plot_pane.channels
    ):
        messages.append(
            tr(
                "Load {source} ({channel}) for rotation; until then bars are shown only at "
                "placement frame {frame}."
            ).format(
                source=Path(wheel.binding.source_id).name,
                channel=wheel.binding.channel,
                frame=wheel.frame,
            )
        )
    else:
        messages.append(
            tr(
                "Rotation uses {channel}; missing samples hide bars beyond placement frame {frame}."
            ).format(channel=wheel.binding.channel, frame=wheel.frame)
        )
    return " ".join(messages)
