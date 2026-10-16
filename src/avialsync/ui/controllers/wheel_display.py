"""What a wheel looks like on each frame, in each view.

Split from :mod:`avialsync.ui.controllers.wheel_controller`, which decides what
happens, and :mod:`avialsync.ui.controllers.wheel_placement`, which holds the
wheel being labelled; this module decides what is drawn. Three rules hold here:

* **Per frame, not per paint.** A wheel's bars are generated once for the frame
  on screen and cached by frame index; every pane only projects them.
* **The frame's time, not the clock's.** The encoder is read at the
  presentation time of the frame shown -- the clock sits anywhere inside that
  frame's interval, and a fast wheel turns visibly within one.
* **The encoder's live mapping.** The reading goes through the same
  :class:`~avialsync.core.timeline.TimeMap` its plot rows use, so re-aligning
  the encoder moves the wheel with it; the reference frame is re-read the same
  way, so it stays at zero turn.

No file is read here: the paint path must not block.
"""

from __future__ import annotations

import dataclasses
import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from avialsync.core.calibration import CameraModel
from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.rotary_calibration import RotaryObservation
from avialsync.core.timeline import TimeMap
from avialsync.core.wheel import (
    EncoderBinding,
    Wheel,
    WheelGeometry,
    fit_issue,
    project_bars,
)
from avialsync.core.wheel_check import settle_sign
from avialsync.ui import prop_context
from avialsync.ui.controllers import rig_paths
from avialsync.ui.controllers.wheel_placement import Marks, WheelPlacement, placement_view
from avialsync.ui.i18n import tr
from avialsync.ui.wheel_overlay import WheelBar, WheelDrawing

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow
    from avialsync.ui.video_pane import VideoPane

logger = logging.getLogger(__name__)
#: A projected mark takes a click this close, in displayed pixels, at any zoom.
_PROJECTED_HIT_RADIUS_PX = 8.0


def camera_models(window: MainWindow) -> dict[str, CameraModel]:
    state = window._calibration_state
    if state is None:
        return {}
    return {rig_paths.camera_name(video): model for video, model in state.cameras.items()}


def projected_hit_radius(window: MainWindow, video: str) -> float:
    """Eight displayed pixels at this pane's current zoom, in source pixels."""
    try:
        index = window.video_grid.pane_paths().index(video)
        pane = window.video_grid.panes[index]
        geometry = pane.surface.frame_geometry(
            pane.paint_canvas.width(), pane.paint_canvas.height()
        )
    except (AttributeError, IndexError, ValueError):
        return 10.0
    if geometry is None or geometry[0] <= 0:
        return 10.0
    return _PROJECTED_HIT_RADIUS_PX / geometry[0]


# ── time and the encoder ─────────────────────────────────────────────


def _reference_pane(window: MainWindow) -> tuple[str, VideoPane] | None:
    """The pane whose frames name wheel frames: the one :func:`rig_paths.frame_at` uses."""
    videos = rig_paths.open_videos(window.rig_paths)
    state = window._calibration_state
    ordered = [v for v in videos if state is not None and v in state.cameras] or videos
    if not ordered:
        return None
    return ordered[0], window.video_grid.panes[videos.index(ordered[0])]


def frame_and_time(window: MainWindow, t_master: float) -> tuple[int, float] | None:
    """The frame on screen at *t_master*, and its presentation time on the master clock."""
    found = _reference_pane(window)
    if found is None:
        return None
    _, pane = found
    index, pts = pane.frame_record_at(t_master)
    return int(index), float(pane.time_map.to_master(pts))


def frame_master_time(window: MainWindow, frame: int) -> float | None:
    found = _reference_pane(window)
    if found is None:
        return None
    video, pane = found
    times = window._video_frame_times.get(video)
    if times is None or not 0 <= frame < len(times):
        return None
    return float(pane.time_map.to_master(float(times[frame])))


def _encoder_map(window: MainWindow, source_id: str) -> tuple[Path, TimeMap] | None:
    """The encoder's cache and its *live* mapping, shared with its plot rows."""
    cache_dir = window._sensor_cache_dirs.get(source_id)
    if cache_dir is None:
        return None
    for row in window.plot_pane.channels:
        if row.reader.cache_dir == cache_dir:
            return cache_dir, row.reader.time_map
    return None


def _channel_reader(window: MainWindow, channel: tuple[str, str]) -> MappedChannelReader | None:
    """The plot's own reader for this encoder channel -- the one the Values tab reads."""
    cache_dir = window._sensor_cache_dirs.get(channel[0])
    if cache_dir is None:
        return None
    for row in window.plot_pane.channels:
        if row.reader.cache_dir == cache_dir and row.reader.channel_id == channel[1]:
            return row.reader
    return None


def sample(window: MainWindow, channel: tuple[str, str], t_master: float) -> float | None:
    """The encoder reading at *t_master*, or None where it has none.

    Read through the plot row's own reader and the source's live mapping,
    interpolated between the samples either side (D-226): a frame's angle lies
    between two encoder samples, and the wheel-calibration analysis reads it
    that way. Coverage and gaps are refused exactly as the Values tab refuses
    them; within a sample period the two can differ by the motion in it.
    """
    reader = _channel_reader(window, channel)
    if reader is None:
        return None
    try:
        found = reader.interpolated_sample_at(t_master)
    except (OSError, ValueError, KeyError):
        logger.warning("Could not read %s from %s", channel[1], channel[0], exc_info=True)
        return None
    if found is None or not math.isfinite(found):
        return None
    return found


def encoder_binding(
    window: MainWindow, placement: WheelPlacement, previous: Wheel | None
) -> EncoderBinding | None:
    """The encoder's reading on the labelled frame: the new wheel's zero turn."""
    if placement.channel is None or placement.fit is None:
        return None
    t = frame_master_time(window, placement.frame)
    angle = sample(window, placement.channel, t) if t is not None else None
    if angle is None:
        window.notifications.show_warning(
            tr("{channel} has no reading on frame {frame}, so the wheel will not turn.").format(
                channel=placement.channel[1], frame=placement.frame
            )
        )
        return None
    binding = EncoderBinding(placement.channel[0], placement.channel[1], angle)
    if previous is not None and previous.binding is not None:
        # Re-placing keeps the ratio and the checks: they are observations of
        # the footage, still true of the new geometry, and re-settle against it.
        binding = dataclasses.replace(
            binding,
            ratio=previous.binding.ratio,
            checks=previous.binding.checks,
            motion_model=previous.binding.motion_model,
            motion_source=previous.binding.motion_source,
        )
        binding = settle_sign(placement.fit.geometry, binding, camera_models(window))[0]
    return binding


def _turn(window: MainWindow, wheel: Wheel, frame: int, t_frame: float) -> float | None:
    """Degrees *wheel* has turned on *frame*; None when the encoder cannot say."""
    binding = wheel.binding
    if binding is None:
        return 0.0 if frame == wheel.frame else None
    channel = (binding.source_id, binding.channel)
    now = sample(window, channel, t_frame)
    reference_time = prop_context.reference_time(window, wheel)
    then = sample(window, channel, reference_time) if reference_time is not None else None
    if now is None:
        return 0.0 if frame == wheel.frame else None
    # Both readings through today's mapping, so re-aligning the encoder after
    # placing the wheel keeps the reference frame at zero turn.
    return binding.turn(now, binding.reference_angle if then is None else then)


def saved_alignment(window: MainWindow, wheel: Wheel, frame: int) -> RotaryObservation | None:
    """The visual alignment saved on *frame*, shown only while *wheel* is adjusted."""
    if window.wheel_state.calibrating != wheel.name or wheel.binding is None:
        return None
    return next(
        (item for item in wheel.binding.rotation_observations if item.evidence_index == frame),
        None,
    )


def _wrap(value: float, period: float) -> float:
    return (value + period / 2.0) % period - period / 2.0


def _pane_frame(window: MainWindow, video: str, t_master: float) -> tuple[int, float] | None:
    """The frame *video*'s own pane shows at *t_master*, and its master time."""
    videos = rig_paths.open_videos(window.rig_paths)
    panes = window.video_grid.panes
    if video not in videos or videos.index(video) >= len(panes):
        return None
    pane = panes[videos.index(video)]
    index, pts = pane.frame_record_at(t_master)
    return int(index), float(pane.time_map.to_master(pts))


def alignment(
    window: MainWindow, wheel: Wheel, t_master: float, video: str | None = None
) -> tuple[int, float, float, float] | None:
    """``(frame, frame time, encoder turn, visual adjustment)`` on the frame at *t_master*.

    The adjustment is the unsaved slider value on this frame, else the saved
    alignment's offset from the current transfer, else zero.  It is derived
    from the saved cyclic angle rather than stored, so applying a new transfer
    leaves saved evidence drawn exactly where the user put it.

    Frames are named by the reference pane at the master cursor; with *video*,
    *t_master* is that camera's presented frame time, used to read its turn
    (D-226). Its earlier exposure must not rename the shared reference frame.
    """
    found = prop_context.frame_and_time(
        window, wheel, window.clock.state.t if video is not None else t_master
    )
    if found is None:
        return None
    frame, t_frame = found
    own = _pane_frame(window, video, t_master) if video is not None else None
    turn = _turn(window, wheel, frame, t_frame if own is None else own[1])
    if turn is None:
        return None
    preview = window.wheel_state.rotation_preview.get(wheel.name)
    if preview is not None and preview.frame == frame:
        return frame, t_frame, turn, preview.adjustment_degrees
    saved = saved_alignment(window, wheel, frame)
    if saved is not None:
        return frame, t_frame, turn, _wrap(saved.angle_degrees - turn, wheel.spec.pitch)
    return frame, t_frame, turn, 0.0


def _ends(
    window: MainWindow, wheel: Wheel, t_master: float, video: str | None = None
) -> np.ndarray | None:
    """*wheel*'s bars on the frame at *t_master*, generated once per frame and camera."""
    found = prop_context.frame_and_time(
        window, wheel, window.clock.state.t if video is not None else t_master
    )
    if found is None:
        return None
    frame = found[0]
    own = _pane_frame(window, video, t_master) if video is not None else None
    mapping = None
    if wheel.binding is not None:
        encoder = _encoder_map(window, wheel.binding.source_id)
        mapping = None if encoder is None else (encoder[1].offset, encoder[1].drift_ms_per_hour)
    preview = window.wheel_state.rotation_preview.get(wheel.name)
    saved = saved_alignment(window, wheel, frame)
    key = (
        frame,
        own,
        mapping,
        preview.adjustment_degrees if preview is not None and preview.frame == frame else None,
        None if saved is None else saved.angle_degrees,
    )
    slot = f"{wheel.name}\0{video or ''}"
    cached = window.wheel_state.cache.get(slot)
    if cached is not None and cached[0] == key:
        hit: np.ndarray | None = cached[1]
        return hit
    aligned = alignment(window, wheel, t_master, video)
    ends = None if aligned is None else wheel.geometry.bar_ends(aligned[2] + aligned[3])
    window.wheel_state.cache[slot] = (key, ends)
    return ends


# ── what each view draws ─────────────────────────────────────────────


def _bars(
    geometry: WheelGeometry,
    ends: np.ndarray,
    camera: CameraModel,
    preview: bool,
) -> list[WheelBar]:
    pixels, in_front, facing = project_bars(geometry, ends, camera)
    return [
        WheelBar(
            float(pixels[i, 0, 0]),
            float(pixels[i, 0, 1]),
            float(pixels[i, 1, 0]),
            float(pixels[i, 1, 1]),
            facing=bool(facing[i]),
            preview=preview,
            first=i == 0,
        )
        for i in range(len(ends))
        if in_front[i]
    ]


def _placement_on_screen(window: MainWindow, t_master: float) -> WheelPlacement | None:
    placement = window.wheel_state.placement
    if placement is None:
        return None
    found = frame_and_time(window, t_master)
    return placement if found is not None and found[0] == placement.frame else None


def pane_drawing(window: MainWindow, video: str, t_master: float) -> WheelDrawing | None:
    """Every wheel -- and the one being placed -- projected into *video*'s camera."""
    state = window._calibration_state
    camera = state.cameras.get(video) if state is not None else None
    bars: list[WheelBar] = []
    clicks: Marks = ()
    projections: Marks = ()
    # The canvas time is this camera's exposure, which can precede the
    # reference camera's current frame even while both panes show this click.
    placement = _placement_on_screen(window, window.clock.state.t)
    if placement is not None and camera is not None:
        if placement.fit is not None:
            geometry = placement.fit.geometry
            bars += _bars(geometry, geometry.bar_ends(), camera, preview=True)
        clicks, projections, _cue = placement.marks(rig_paths.camera_name(video))
    replacing = window.wheel_state.placement.replacing if window.wheel_state.placement else None
    for wheel in window.wheels:
        if wheel.name == replacing:
            continue
        own_camera = prop_context.camera_for(wheel, video) if wheel.context.cameras else camera
        if own_camera is None:
            continue
        ends = _ends(window, wheel, t_master, video)
        if ends is not None:
            bars += _bars(wheel.geometry, ends, own_camera, preview=False)
    if not bars and not clicks and not projections:
        return None
    return WheelDrawing(tuple(bars), clicks, projections)


def diameter(window: MainWindow, wheel: Wheel) -> float | None:
    """The bar diameter to draw, in calibration units: the slider's while dragged.

    The slider and the stored value are in the units the user measures in, so
    both go through the wheel's own scale.
    """
    typed = window.wheel_state.diameter_preview.get(wheel.name, wheel.bar_diameter)
    return None if typed is None else typed * wheel.world_per_unit


def scene(window: MainWindow, t_master: float) -> list[tuple[np.ndarray, bool, float | None]]:
    """Every wheel's bars for the 3D view: ``(ends, preview, bar diameter)``."""
    out: list[tuple[np.ndarray, bool, float | None]] = []
    placement = _placement_on_screen(window, t_master)
    if placement is not None and placement.fit is not None:
        out.append((placement.fit.geometry.bar_ends(), True, None))
    replacing = window.wheel_state.placement.replacing if window.wheel_state.placement else None
    for wheel in window.wheels:
        ends = None if wheel.name == replacing else _ends(window, wheel, t_master)
        if ends is not None:
            out.append((ends, False, diameter(window, wheel)))
    return out


def encoder_offsets(window: MainWindow) -> dict[str, float]:
    """Each wheel's encoder source offset, as its Sources row shows it, when loaded."""
    out = {}
    for wheel in window.wheels:
        binding = wheel.binding
        if binding is not None and window.sidebar.sensor_widget(binding.source_id) is not None:
            out[wheel.name] = window.sidebar.sensor_mapping(binding.source_id)[0]
    return out


def _rotation_adjustments(window: MainWindow, t_master: float) -> dict[str, float | None]:
    """The visual rotation slider value for the wheel being adjusted, on the shown frame."""
    name = window.wheel_state.calibrating
    wheel = window.wheels.get(name) if name is not None else None
    if wheel is None:
        return {}
    aligned = alignment(window, wheel, t_master)
    return {wheel.name: None if aligned is None else aligned[3]}


def _rig_wheel(window: MainWindow) -> str:
    """The rig's own calibrated wheel, by name, when the session supplies one."""
    hint = window.wheel_state.session_rotary
    return hint.geometry_source if hint is not None and hint.geometry is not None else ""


def show_rotation(window: MainWindow, t_master: float) -> None:
    """Keep the adjusting wheel's slider on the frame the clock moved to."""
    for name, adjustment in _rotation_adjustments(window, t_master).items():
        window.wheel_panel.show_rotation(name, adjustment)


def refresh(window: MainWindow) -> None:
    """Push wheels, the placement, and the panel to every view."""
    window.wheel_state.cache.clear()
    placement = window.wheel_state.placement
    if placement is not None:
        placement.quality_issue = (
            fit_issue(placement.fit, placement.ordered()) if placement.fit is not None else None
        )
    active = len(window.wheels) > 0 or window.wheel_state.placement is not None
    window.video_grid.set_wheel_source(window.wheel_state.pane_source if active else None)
    window.video_grid.refresh_point_edits()
    window.tracking_3d_pane.set_cursor(window.clock.state.t)
    window._update_tracking_pane_visibility()
    rotation_adjustments = _rotation_adjustments(window, window.clock.state.t)
    window.wheel_panel.set_wheels(
        list(window.wheels),
        window.wheel_state.checking,
        encoder_offsets(window),
        calibrating=window.wheel_state.calibrating,
        rotation_adjustments=rotation_adjustments,
        proposals=window.wheel_state.motion_proposals,
        fitting=window.wheel_state.motion_fitting,
        rig_wheel=_rig_wheel(window),
    )
    window.wheel_panel.set_dependencies(
        {wheel.name: prop_context.wheel_status(window, wheel) for wheel in window.wheels}
    )
    view = (
        placement_view(placement, sorted(camera_models(window))) if placement is not None else None
    )
    window.wheel_panel.show_placement(view)
    if view is not None:
        window.transport.set_status(view.instruction, "info")
