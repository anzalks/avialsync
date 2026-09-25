"""What a wheel looks like on each frame, in each view (D-113).

Split from :mod:`avialsync.ui.controllers.wheel_controller`, which decides what
happens, and :mod:`avialsync.ui.controllers.wheel_placement`, which holds the
wheel being labelled; this module decides what is drawn. Three rules hold here:

* **Per frame, not per paint.** A wheel's bars are generated once for the frame
  on screen and cached by frame index (rule 6); every pane only projects them.
* **The frame's time, not the clock's.** The encoder is read at the
  presentation time of the frame shown -- the clock sits anywhere inside that
  frame's interval, and a fast wheel turns visibly within one.
* **The encoder's live mapping.** The reading goes through the same
  :class:`~avialsync.core.timeline.TimeMap` its plot rows use, so re-aligning
  the encoder moves the wheel with it; the reference frame is re-read the same
  way, so it stays at zero turn.

No file is read here: the paint path must not block (rule 3).
"""

from __future__ import annotations

import dataclasses
import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from avialsync.core.calibration import CameraModel
from avialsync.core.pyramid import PyramidReader
from avialsync.core.timeline import TimeMap
from avialsync.core.wheel import (
    EncoderBinding,
    Wheel,
    WheelGeometry,
    bar_widths,
    fit_issue,
    project_bars,
)
from avialsync.core.wheel_check import settle_sign
from avialsync.ui.controllers import rig_paths
from avialsync.ui.controllers.wheel_placement import Marks, Placement, placement_view
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
    """Eight displayed pixels at this pane's current zoom, in source pixels (D-120)."""
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
    videos = rig_paths.open_videos(window)
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


def sample(window: MainWindow, channel: tuple[str, str], t_master: float) -> float | None:
    """The encoder reading at *t_master*, or None where it has none."""
    found = _encoder_map(window, channel[0])
    if found is None:
        return None
    cache_dir, time_map = found
    key = (str(cache_dir), channel[1])
    reader = window._wheel_readers.get(key)
    if reader is None:
        reader = window._wheel_readers[key] = PyramidReader(cache_dir, channel[1])
    try:
        value = float(reader.value_at(time_map.to_source(t_master)))
    except (OSError, ValueError, KeyError):
        logger.warning("Could not read %s from %s", channel[1], cache_dir, exc_info=True)
        return None
    return value if math.isfinite(value) else None


def encoder_binding(
    window: MainWindow, placement: Placement, previous: Wheel | None
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
            binding, ratio=previous.binding.ratio, checks=previous.binding.checks
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
    reference_time = frame_master_time(window, wheel.frame)
    then = sample(window, channel, reference_time) if reference_time is not None else None
    if now is None:
        return None
    # Both readings through today's mapping, so re-aligning the encoder after
    # placing the wheel keeps the reference frame at zero turn.
    return (
        binding.sign * binding.ratio * (now - (binding.reference_angle if then is None else then))
    )


def _ends(window: MainWindow, wheel: Wheel, t_master: float) -> np.ndarray | None:
    """*wheel*'s bars on the frame at *t_master*, generated once per frame."""
    found = frame_and_time(window, t_master)
    if found is None:
        return None
    frame, t_frame = found
    mapping = None
    if wheel.binding is not None:
        encoder = _encoder_map(window, wheel.binding.source_id)
        mapping = None if encoder is None else (encoder[1].offset, encoder[1].drift_ppm)
    key = (frame, mapping)
    cached = window._wheel_cache.get(wheel.name)
    if cached is not None and cached[0] == key:
        hit: np.ndarray | None = cached[1]
        return hit
    turn = _turn(window, wheel, frame, t_frame)
    ends = None if turn is None else wheel.geometry.bar_ends(turn)
    window._wheel_cache[wheel.name] = (key, ends)
    return ends


# ── what each view draws ─────────────────────────────────────────────


def _bars(
    geometry: WheelGeometry,
    ends: np.ndarray,
    camera: CameraModel,
    preview: bool,
    diameter: float | None = None,
) -> list[WheelBar]:
    pixels, in_front, facing = project_bars(geometry, ends, camera)
    widths = bar_widths(ends, diameter, camera) if diameter else np.zeros(len(ends))
    return [
        WheelBar(
            float(pixels[i, 0, 0]),
            float(pixels[i, 0, 1]),
            float(pixels[i, 1, 0]),
            float(pixels[i, 1, 1]),
            facing=bool(facing[i]),
            preview=preview,
            first=i == 0,
            width=float(widths[i]),
        )
        for i in range(len(ends))
        if in_front[i]
    ]


def _placement_on_screen(window: MainWindow, t_master: float) -> Placement | None:
    placement = window._wheel_placement
    if placement is None:
        return None
    found = frame_and_time(window, t_master)
    return placement if found is not None and found[0] == placement.frame else None


def pane_drawing(window: MainWindow, video: str, t_master: float) -> WheelDrawing | None:
    """Every wheel -- and the one being placed -- projected into *video*'s camera."""
    state = window._calibration_state
    camera = state.cameras.get(video) if state is not None else None
    if camera is None:
        return None
    bars: list[WheelBar] = []
    clicks: Marks = ()
    projections: Marks = ()
    prompt = ""
    placement = _placement_on_screen(window, t_master)
    if placement is not None:
        if placement.fit is not None:
            geometry = placement.fit.geometry
            bars += _bars(geometry, geometry.bar_ends(), camera, preview=True)
        clicks, projections, prompt = placement.marks(rig_paths.camera_name(video))
    replacing = window._wheel_placement.replacing if window._wheel_placement else None
    for wheel in window.wheels:
        if wheel.name == replacing:
            continue
        ends = _ends(window, wheel, t_master)
        if ends is not None:
            bars += _bars(wheel.geometry, ends, camera, False, diameter(window, wheel))
    if not bars and not clicks and not projections and not prompt:
        return None
    return WheelDrawing(tuple(bars), clicks, projections, prompt)


def diameter(window: MainWindow, wheel: Wheel) -> float | None:
    """The bar diameter to draw: the slider's while it is dragged, else the wheel's."""
    return window._wheel_diameter_preview.get(wheel.name, wheel.bar_diameter)


def scene(window: MainWindow, t_master: float) -> list[tuple[np.ndarray, bool, float | None]]:
    """Every wheel's bars for the 3D view: ``(ends, preview, bar diameter)``."""
    out: list[tuple[np.ndarray, bool, float | None]] = []
    placement = _placement_on_screen(window, t_master)
    if placement is not None and placement.fit is not None:
        out.append((placement.fit.geometry.bar_ends(), True, None))
    replacing = window._wheel_placement.replacing if window._wheel_placement else None
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


def refresh(window: MainWindow) -> None:
    """Push wheels, the placement, and the panel to every view."""
    window._wheel_cache.clear()
    placement = window._wheel_placement
    if placement is not None:
        placement.quality_issue = (
            fit_issue(placement.fit, placement.ordered()) if placement.fit is not None else None
        )
    active = len(window.wheels) > 0 or window._wheel_placement is not None
    window.video_grid.set_wheel_source(window._wheel_pane_source if active else None)
    window.video_grid.refresh_point_edits()
    window.tracking_3d_pane.canvas.set_cursor(window.clock.state.t)
    window._update_tracking_pane_visibility()
    window.wheel_panel.set_wheels(
        list(window.wheels), window._wheel_checking, encoder_offsets(window)
    )
    view = (
        placement_view(placement, sorted(camera_models(window))) if placement is not None else None
    )
    window.wheel_panel.show_placement(view)
    if view is not None:
        window.transport.set_status(view.instruction, "info")
