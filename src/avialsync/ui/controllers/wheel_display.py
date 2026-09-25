"""What a wheel looks like on each frame, in each view (D-113).

Split from :mod:`avialsync.ui.controllers.wheel_controller`, which decides what
happens; this module decides what is drawn. Three rules hold here:

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

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from avialsync.core.calibration import CameraModel
from avialsync.core.pyramid import PyramidReader
from avialsync.core.timeline import TimeMap
from avialsync.core.wheel import (
    SIDES,
    EndClick,
    Wheel,
    WheelFit,
    WheelGeometry,
    WheelSpec,
    project_bars,
)
from avialsync.ui.controllers import rig_paths
from avialsync.ui.i18n import tr
from avialsync.ui.wheel_overlay import WheelBar, WheelDrawing
from avialsync.ui.wheel_panel import PlacementView, describe_fit

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow
    from avialsync.ui.video_pane import VideoPane

logger = logging.getLogger(__name__)


@dataclass
class Placement:
    """A wheel being clicked: what was declared, and the clicks so far."""

    spec: WheelSpec
    channel: tuple[str, str] | None
    frame: int
    clicks: dict[tuple[int, str], EndClick] = field(default_factory=dict)
    #: Which end is wanted: bar ``step // 2``, side ``SIDES[step % 2]``.
    step: int = 0
    #: ``(step, camera, what that camera had before)`` per click, for Undo Click.
    history: list[tuple[int, str, tuple[float, float] | None]] = field(default_factory=list)
    fit: WheelFit | None = None
    problem: str = ""
    flipped: bool = False
    #: The wheel this placement will replace on Accept (Re-place), if any.
    replacing: str | None = None

    @property
    def end(self) -> tuple[int, str]:
        return self.step // 2, SIDES[self.step % 2]

    def ordered(self) -> tuple[EndClick, ...]:
        return tuple(self.clicks[key] for key in sorted(self.clicks))

    def ready(self, cameras: set[str]) -> bool:
        """Two or three whole bars, with both ends seen in every calibrated view."""
        if len(cameras) < 2 or self.step not in (4, 6) or len(self.clicks) != self.step:
            return False
        return all(
            {camera for camera, _, _ in self.clicks.get((bar, side), EndClick(bar, side)).views}
            == cameras
            for bar in range(self.step // 2)
            for side in SIDES
        )


def _end_label(bar: int, side: str) -> str:
    return f"{bar + 1}{'ab'[SIDES.index(side)]}"


def camera_models(window: MainWindow) -> dict[str, CameraModel]:
    state = window._calibration_state
    if state is None:
        return {}
    return {rig_paths.camera_name(video): model for video, model in state.cameras.items()}


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
    geometry: WheelGeometry, ends: np.ndarray, camera: CameraModel, preview: bool
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
    clicks: tuple[tuple[str, float, float], ...] = ()
    placement = _placement_on_screen(window, t_master)
    if placement is not None:
        if placement.fit is not None:
            geometry = placement.fit.geometry
            bars += _bars(geometry, geometry.bar_ends(), camera, preview=True)
        name = rig_paths.camera_name(video)
        clicks = tuple(
            (_end_label(bar, side), x, y)
            for (bar, side), click in sorted(placement.clicks.items())
            for view_camera, x, y in click.views
            if view_camera == name
        )
    replacing = window._wheel_placement.replacing if window._wheel_placement else None
    for wheel in window.wheels:
        if wheel.name == replacing:
            continue
        ends = _ends(window, wheel, t_master)
        if ends is not None:
            bars += _bars(wheel.geometry, ends, camera, preview=False)
    if not bars and not clicks:
        return None
    return WheelDrawing(tuple(bars), clicks)


def scene(window: MainWindow, t_master: float) -> list[tuple[np.ndarray, bool]]:
    """Every wheel's bars for the 3D view: ``(ends, preview)``."""
    out: list[tuple[np.ndarray, bool]] = []
    placement = _placement_on_screen(window, t_master)
    if placement is not None and placement.fit is not None:
        out.append((placement.fit.geometry.bar_ends(), True))
    replacing = window._wheel_placement.replacing if window._wheel_placement else None
    for wheel in window.wheels:
        ends = None if wheel.name == replacing else _ends(window, wheel, t_master)
        if ends is not None:
            out.append((ends, False))
    return out


def refresh(window: MainWindow) -> None:
    """Push wheels, the placement, and the panel to every view."""
    window._wheel_cache.clear()
    active = len(window.wheels) > 0 or window._wheel_placement is not None
    window.video_grid.set_wheel_source(window._wheel_pane_source if active else None)
    window.video_grid.refresh_point_edits()
    window.tracking_3d_pane.canvas.set_cursor(window.clock.state.t)
    window._update_tracking_pane_visibility()
    window.wheel_panel.set_wheels(list(window.wheels), window._wheel_checking)
    view = _placement_view(window)
    window.wheel_panel.show_placement(view)
    if view is not None:
        window.transport.set_status(view.instruction, "info")


def _placement_view(window: MainWindow) -> PlacementView | None:
    placement = window._wheel_placement
    if placement is None:
        return None
    cameras = sorted(camera_models(window))
    if placement.step >= 6:
        instruction = tr("All three bars are marked in every camera. Review the fit and Accept.")
    else:
        bar, side = placement.end
        click = placement.clicks.get((bar, side))
        clicked = {c for c, _, _ in click.views} if click is not None else set()
        remaining = [c for c in cameras if c not in clicked]
        end = tr("first end") if side == SIDES[0] else tr("second end")
        instruction = tr("Bar {bar}, {end}: click it in {cameras}.").format(
            bar=bar + 1, end=end, cameras=", ".join(remaining)
        )
        if placement.step == 4:
            instruction = (
                tr("Two bars complete. Review and Accept, or add a third bar.") + " " + instruction
            )
    summary = (
        describe_fit(placement.spec, placement.fit)
        if placement.fit is not None
        else placement.problem or tr("Click both ends of at least two neighbouring bars.")
    )
    return PlacementView(
        spec=placement.spec,
        frame=placement.frame,
        instruction=instruction,
        summary=summary,
        can_undo=bool(placement.history),
        can_flip=placement.fit is not None and placement.fit.can_flip,
        can_accept=placement.fit is not None and placement.ready(set(cameras)),
    )
