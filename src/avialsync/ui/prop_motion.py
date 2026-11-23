"""Read prop motion at presented video frames and compare later camera clicks."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from avialsync.core.physical_props import BallProp, BeltProp, MotionCheck, Point3, UnitQuaternion
from avialsync.core.visual_prop_tracking import (
    BallVisualState,
    BeltVisualState,
    ball_visual_state,
    belt_visual_state,
)
from avialsync.ui import prop_context
from avialsync.ui.controllers import rig_paths, wheel_display

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


def frame_time(window: MainWindow, video: str, t_master: float) -> tuple[int, float] | None:
    """The named camera's displayed frame and its master presentation time."""
    paths = window.video_grid.pane_paths()
    if video not in paths:
        return None
    pane = window.video_grid.panes[paths.index(video)]
    index, pts = pane.frame_record_at(t_master)
    return int(index), float(pane.time_map.to_master(pts))


def scalar_reading(
    window: MainWindow, source_id: str, channel: str, t_frame: float
) -> float | None:
    """Read an interpolated displacement inside the loaded channel's actual time coverage."""
    cache = window._sensor_cache_dirs.get(source_id)
    if cache is None:
        return None
    for row in window.plot_pane.channels:
        reader = row.reader
        if reader.cache_dir != cache or reader.channel_id != channel:
            continue
        try:
            interp = getattr(reader, "interpolated_sample_at", None)
            if callable(interp):
                val = interp(t_frame)
                return None if val is None or not math.isfinite(val) else float(val)
            found = reader.available_sample_at(t_frame)
        except (OSError, ValueError, KeyError):
            return None
        return None if found is None or not math.isfinite(found[1]) else float(found[1])
    return None


def _slerp_quaternions(
    q0: tuple[float, float, float, float],
    q1: tuple[float, float, float, float],
    alpha: float,
) -> tuple[float, float, float, float]:
    """Spherical linear interpolation along the shortest arc on S^3."""
    u0 = np.asarray(q0, dtype=np.float64) / math.hypot(*q0)
    u1 = np.asarray(q1, dtype=np.float64) / math.hypot(*q1)
    dot = float(np.dot(u0, u1))
    if dot < 0.0:
        u1 = -u1
        dot = -dot
    if dot > 1.0 - 1e-7:
        blended = (1.0 - alpha) * u0 + alpha * u1
        blended /= float(np.linalg.norm(blended))
    else:
        theta = math.acos(min(1.0, dot))
        sin_theta = math.sin(theta)
        blended = (
            math.sin((1.0 - alpha) * theta) / sin_theta * u0
            + math.sin(alpha * theta) / sin_theta * u1
        )
    return (float(blended[0]), float(blended[1]), float(blended[2]), float(blended[3]))


def orientation_values(
    window: MainWindow, ball: BallProp, t_frame: float
) -> tuple[float, float, float, float] | None:
    """Read synchronized quaternion components, SLERPed to *t_frame* between samples."""
    binding = ball.binding
    if binding is None:
        return None
    cache = window._sensor_cache_dirs.get(binding.source_id)
    if cache is None:
        return None
    by_channel = {
        row.reader.channel_id: row.reader
        for row in window.plot_pane.channels
        if row.reader.cache_dir == cache
    }
    if any(channel not in by_channel for channel in binding.channels):
        return None
    readers = [by_channel[channel] for channel in binding.channels]
    try:
        samples = [reader.available_sample_at(t_frame) for reader in readers]
    except (OSError, ValueError, KeyError):
        return None
    if any(item is None for item in samples):
        return None
    found = [item for item in samples if item is not None]
    if len({item[0] for item in found}) != 1:
        return None
    index = int(found[0][0])
    values = (float(found[0][1]), float(found[1][1]), float(found[2][1]), float(found[3][1]))
    if not all(math.isfinite(value) for value in values) or math.hypot(*values) < 1e-12:
        return None
    if all(hasattr(reader, "source_reader") and hasattr(reader, "time_map") for reader in readers):
        try:
            source_time = float(readers[0].time_map.to_source(t_frame))
            cols = [reader.source_reader.mapped_columns() for reader in readers]
            t_col = cols[0][0]
            if index + 1 < len(t_col) and source_time > float(t_col[index]):
                spans = [(float(c[0][index]), float(c[0][index + 1])) for c in cols]
                if len(set(spans)) == 1 and spans[0][1] > spans[0][0]:
                    next_vals = (
                        float(cols[0][1][index + 1]),
                        float(cols[1][1][index + 1]),
                        float(cols[2][1][index + 1]),
                        float(cols[3][1][index + 1]),
                    )
                    if all(math.isfinite(v) for v in next_vals) and math.hypot(*next_vals) >= 1e-12:
                        alpha = (source_time - spans[0][0]) / (spans[0][1] - spans[0][0])
                        return _slerp_quaternions(values, next_vals, min(max(alpha, 0.0), 1.0))
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return values
    return values


def reference_baseline(
    window: MainWindow, prop: BeltProp | BallProp
) -> tuple[float | None, UnitQuaternion | None]:
    """Read the prop's reference-frame sensor baseline through today's live TimeMap."""
    if prop.binding is None:
        return None, None
    reference_time = prop_context.frame_master_time(window, prop, prop.binding.reference_frame)
    if reference_time is None:
        return None, None
    if isinstance(prop, BeltProp):
        return (
            scalar_reading(window, prop.binding.source_id, prop.binding.channel, reference_time),
            None,
        )
    raw = orientation_values(window, prop, reference_time)
    return None, (None if raw is None else UnitQuaternion(*raw))


def orientation(window: MainWindow, ball: BallProp, t_frame: float) -> UnitQuaternion | None:
    """The measured unit orientation, or unknown if the samples disagree."""
    values = orientation_values(window, ball, t_frame)
    return None if values is None else UnitQuaternion(*values)


def sampled_point(
    window: MainWindow, prop: BeltProp | BallProp, t_frame: float
) -> tuple[Point3, tuple[float, ...]] | None:
    """Locate a mark using both current and reference readings on the live TimeMap."""
    if prop.binding is None:
        return None
    reference_time = prop_context.frame_master_time(window, prop, prop.binding.reference_frame)
    if reference_time is None:
        return None
    if isinstance(prop, BeltProp):
        binding = prop.binding
        assert binding is not None
        now = scalar_reading(window, binding.source_id, binding.channel, t_frame)
        then = scalar_reading(window, binding.source_id, binding.channel, reference_time)
        if now is None or then is None:
            return None
        point = prop.material_point(now, then)
        return None if point is None else (point, (now,))
    now_values = orientation_values(window, prop, t_frame)
    then_values = orientation_values(window, prop, reference_time)
    if now_values is None or then_values is None:
        return None
    point = prop.material_point(UnitQuaternion(*now_values), UnitQuaternion(*then_values))
    return None if point is None else (point, now_values)


def material_point(window: MainWindow, prop: BeltProp | BallProp, t_frame: float) -> Point3 | None:
    """The moving mark at a frame time, or unknown where evidence is absent."""
    found = sampled_point(window, prop, t_frame)
    return None if found is None else found[0]


def visual_state(
    window: MainWindow, prop: BeltProp | BallProp, frame: int
) -> BeltVisualState | BallVisualState | None:
    """Solve only the observed frame against the current camera calibration."""
    cameras = prop_context.models(window, prop)
    if isinstance(prop, BeltProp):
        return belt_visual_state(prop, frame, cameras)
    return ball_visual_state(prop, frame, cameras)


def check_click(
    window: MainWindow, prop: BeltProp | BallProp, video: str, x: float, y: float
) -> MotionCheck | None:
    """Compare one actual click with the mark predicted on that displayed frame."""
    found = frame_time(window, video, window.clock.state.t)
    if found is None:
        return None
    reference = prop.binding.reference_frame if prop.binding is not None else -1
    if found[0] == reference:
        return None
    sampled = sampled_point(window, prop, found[1])
    if sampled is None:
        return None
    point, source_values = sampled
    camera = rig_paths.camera_name(video)
    side = prop.side_view if isinstance(prop, BeltProp) else None
    if side is not None and isinstance(prop, BeltProp) and prop.rollers is not None:
        # A one-camera belt is only predicted in its own view.
        if side.camera != camera:
            return None
        pixel = side.plane_view(prop.rollers).pixel(point[0], point[1])
        if pixel is None:
            return None
        predicted = np.asarray(pixel, dtype=np.float64)
    else:
        model = (
            prop_context.camera_for(prop, video)
            if prop.context.cameras
            else wheel_display.camera_models(window).get(camera)
        )
        if model is None:
            return None
        xyz = np.asarray(point, dtype=np.float64)
        depth = float(model.rotation_matrix()[2] @ xyz + model.translation[2])
        if depth <= 0 or not math.isfinite(depth):
            return None
        predicted = model.project(xyz)[0]
        if not np.all(np.isfinite(predicted)):
            return None
    return MotionCheck(
        found[0],
        camera,
        float(x),
        float(y),
        math.hypot(float(predicted[0]) - x, float(predicted[1]) - y),
        source_values,
    )
