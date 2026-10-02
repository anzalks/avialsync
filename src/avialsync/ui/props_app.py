"""Live physical-prop editing, sidecar jobs, and camera projections (D-149)."""

from __future__ import annotations

import dataclasses
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QWidget

from avialsync.core.calibration import CameraModel
from avialsync.core.commands import (
    MoveLadderStepCommand,
    SetLadderCommand,
    SetLadderStepCommand,
    SetPhysicalPropCommand,
)
from avialsync.core.errors import PropModelError
from avialsync.core.physical_props import (
    BallBinding,
    BallProp,
    BallSurface,
    BallVisualFrame,
    BeltBinding,
    BeltProp,
    BeltTrack,
    BeltVisualFrame,
    Ladder,
    LadderPoint,
    LadderStep,
    Point3,
    PropStore,
    StepClick,
    UnitQuaternion,
    WheelView,
)
from avialsync.core.prop_file import PropFileIssue, PropKind, PropRecord, prop_kind, prop_path
from avialsync.core.visual_prop_tracking import (
    BallVisualState,
    BeltVisualState,
    belt_visual_travel,
)
from avialsync.engine.prop_file_worker import PropFileReadWorker, PropFileWriteWorker
from avialsync.ui import prop_motion
from avialsync.ui.controllers import (
    calibration_controller,
    rig_paths,
    wheel_controller,
    wheel_display,
)
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread
from avialsync.ui.prop_overlay import PropDrawing, PropPixel
from avialsync.ui.props_panel import PropsPanel, PropsTab

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


@dataclass
class StepDraft:
    """Unaccepted image observations for one step."""

    ladder: str
    label: str
    points: list[LadderPoint] = field(default_factory=lambda: [LadderPoint()])
    active: int = 0
    minimum_points: int = 1
    before: LadderStep | None = None


def _ball_rings(ball: BallProp) -> tuple[tuple[str, tuple[Point3, ...]], ...]:
    """Return declared great-circle guides, not an orientation estimate."""
    centre = ball.surface.centre
    radius = ball.surface.radius
    axes = (
        ("XY", (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        ("XZ", (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        ("YZ", (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    )
    rings: list[tuple[str, tuple[Point3, ...]]] = []
    for name, first_axis, second_axis in axes:
        points = tuple(
            (
                centre[0]
                + radius
                * (
                    math.cos(math.tau * index / 24) * first_axis[0]
                    + math.sin(math.tau * index / 24) * second_axis[0]
                ),
                centre[1]
                + radius
                * (
                    math.cos(math.tau * index / 24) * first_axis[1]
                    + math.sin(math.tau * index / 24) * second_axis[1]
                ),
                centre[2]
                + radius
                * (
                    math.cos(math.tau * index / 24) * first_axis[2]
                    + math.sin(math.tau * index / 24) * second_axis[2]
                ),
            )
            for index in range(24)
        )
        rings.append((name, points))
    return tuple(rings)


class PropsApp:
    """Small coordinator for props; the document bus owns accepted edits."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window
        self.store = PropStore()
        self.store.observe(self._changed)
        self.wheels = WheelView(self.store)
        self.panel: PropsPanel | None = None
        self.tab: PropsTab | None = None
        self.draft: StepDraft | None = None
        self.checking: str | None = None
        self.visual_tracking: tuple[str, str] | None = None
        self._adopted: set[Path] = set()
        self._known_kinds: dict[str, PropKind] = {}
        self._edited: set[str] = set()
        self._writing: set[Path] = set()
        self._pending: dict[Path, dict[str, tuple[PropRecord | None, PropKind]]] = {}
        self._known_sidecars: set[tuple[Path, str]] = set()
        self._display_key: tuple[tuple[str, int], ...] | None = None
        self._display_ladders: tuple[Ladder, ...] = ()

    def make_panel(self, wheel_tab: QWidget | None = None) -> PropsTab:
        """Create the one inspector and connect its controls."""
        panel = PropsPanel(self.store, self.window)
        panel.create_requested.connect(self.create)
        panel.place_requested.connect(self.start_step)
        panel.next_point_requested.connect(self.next_point)
        panel.save_step_requested.connect(self.save_step)
        panel.cancel_step_requested.connect(self.cancel_step)
        panel.remove_step_requested.connect(self.remove_step)
        panel.reclick_step_requested.connect(self.reclick_step)
        panel.relabel_step_requested.connect(self.relabel_step)
        panel.move_step_requested.connect(self.move_step)
        panel.remove_ladder_requested.connect(self.remove_ladder)
        panel.belt_save_requested.connect(self.save_belt)
        panel.ball_save_requested.connect(self.save_ball)
        panel.belt_bind_requested.connect(self.bind_belt)
        panel.ball_bind_requested.connect(self.bind_ball)
        panel.visual_track_requested.connect(self.start_visual_track)
        panel.visual_clear_requested.connect(self.clear_visual_track)
        panel.visual_lap_requested.connect(self.set_visual_lap)
        panel.motion_check_requested.connect(self.start_check)
        panel.remove_prop_requested.connect(self.remove_prop)
        panel.prop_selected.connect(self._show_selected_prop)
        self.panel = panel
        panel.kind.currentIndexChanged.connect(self._update_create_availability)
        self.window.video_grid.pane_attached.connect(self._update_create_availability)
        self.window.video_grid.pane_detached.connect(self._update_create_availability)
        self.tab = PropsTab(panel, wheel_tab, self.window)
        self._update_create_availability()
        return self.tab

    def show(self, kind: str | None = None) -> None:
        """Show the inspector from the live Edit action."""
        if self.panel is not None and self.tab is not None:
            if kind is not None:
                index = self.panel.kind.findData(kind)
                if index >= 0:
                    self.panel.kind.setCurrentIndex(index)
            self._update_create_availability()
            self._refresh_motion_channels()
            self.window._left_tabs.setCurrentWidget(self.tab)
            if self.panel.kind.currentData() != "wheel":
                self.panel.name.setFocus()

    def _update_create_availability(self) -> None:
        """Explain missing video context before a creation gesture (D-107)."""
        panel = self.panel
        if panel is None:
            return
        kind = panel.kind.currentData()
        if kind == "wheel":
            available = len(self.window.video_grid.pane_paths()) >= 2
            reason = tr("Load at least two camera videos to place a wheel.")
        else:
            available = rig_paths.pose3d_dir(self.window.rig_paths) is not None
            reason = tr("Open a recording before adding a prop.")
        panel.create_button.setEnabled(available)
        panel.create_button.setToolTip("" if available else reason)
        panel.save_belt.setEnabled(kind == "belt" and available)
        panel.save_ball.setEnabled(kind == "ball" and available)
        panel.save_belt.setToolTip("" if available else reason)
        panel.save_ball.setToolTip("" if available else reason)

    def create(self, name: str, checked: bool = False) -> None:
        """Add the selected prop kind or toggle wheel placement."""
        if self.panel is not None and self.panel.kind.currentData() == "wheel":
            wheel_controller.toggled(self.window, checked)
            return
        if not name:
            self._status(tr("Enter a ladder name first."))
            return
        try:
            folder = rig_paths.pose3d_dir(self.window.rig_paths)
            if folder is None:
                self._status(tr("Open a recording before adding a prop."))
                return
            prop_path(folder, name)
            if name.casefold() in {used.casefold() for used in self.store.names()}:
                self._status(tr("That prop name is already used in this recording."))
                return
            ladder = Ladder(name)
        except PropModelError:
            self._status(tr("Choose a filename-safe prop name."))
            return
        self.window.document.execute(
            SetLadderCommand(name, None, ladder, tr("Add ladder {name}").format(name=name)),
            self.window._mutations,
        )
        if self.panel is not None:
            self.panel.select_prop(name, "ladder")

    def _show_selected_prop(self, kind: str, name: str) -> None:
        """Load declared belt or ball fields for the selected saved record."""
        if self.panel is None or not name:
            return
        prop = self.store.get(name)
        self._refresh_motion_channels()
        self.panel.name.setText(name)
        if kind == "belt" and isinstance(prop, BeltProp):
            self.panel.set_belt_fields(prop)
        elif kind == "ball" and isinstance(prop, BallProp):
            self.panel.set_ball_fields(prop)

    def _refresh_motion_channels(self) -> None:
        if self.panel is None:
            return
        seen: set[tuple[str, str]] = set()
        channels: list[tuple[str, str, str]] = []
        for row in self.window.plot_pane.channels:
            key = (row.reader.source_id, row.reader.channel_id)
            if key[0] and key not in seen:
                seen.add(key)
                channels.append((*key, f"{key[1]} · {Path(key[0]).name}"))
        self.panel.set_motion_channels(channels)

    def save_belt(self) -> None:
        """Edit the fixed path, invalidating motion only if geometry changes."""
        panel = self.panel
        if panel is None:
            return
        name = panel.name.text().strip() or panel.current_ladder()
        try:
            folder = rig_paths.pose3d_dir(self.window.rig_paths)
            if folder is None:
                self._status(tr("Open a recording before adding a prop."))
                return
            prop_path(folder, name)
            before = self.store.get(name)
            if before is None and name.casefold() in {
                used.casefold() for used in self.store.names()
            }:
                self._status(tr("That prop name is already used in this recording."))
                return
            if before is not None and not isinstance(before, BeltProp):
                self._status(tr("That name belongs to a different prop kind."))
                return
            vertices, closed, units, direction = panel.belt_values()
            declared = BeltProp(name, BeltTrack(vertices, closed), units, direction)
            same_direction = isinstance(before, BeltProp) and (
                (before.travel_direction is None and declared.travel_direction is None)
                or (
                    before.travel_direction is not None
                    and declared.travel_direction is not None
                    and all(
                        math.isclose(a, b, abs_tol=1e-4)
                        for a, b in zip(
                            before.travel_direction, declared.travel_direction, strict=True
                        )
                    )
                )
            )
            binding = (
                before.binding
                if isinstance(before, BeltProp)
                and before.track == declared.track
                and before.units == units
                and same_direction
                else None
            )
            visual_frames = (
                before.visual_frames
                if isinstance(before, BeltProp) and before.track == declared.track
                else ()
            )
            visual_reference = (
                before.visual_reference_frame
                if isinstance(before, BeltProp) and visual_frames
                else None
            )
            belt = dataclasses.replace(
                declared,
                binding=binding,
                visual_frames=visual_frames,
                visual_reference_frame=visual_reference,
            )
        except PropModelError:
            self._status(tr("Check the belt path and choose a filename-safe prop name."))
            return
        label = (
            tr("Edit belt {name}").format(name=name)
            if before
            else tr("Add belt {name}").format(name=name)
        )
        self.window.document.execute(
            SetPhysicalPropCommand(name, before, belt, label), self.window._mutations
        )
        panel.select_prop(name, "belt")
        self._status(
            tr("Belt geometry saved; displacement binding kept.")
            if belt.binding
            else tr("Belt geometry saved; surface motion remains unknown.")
        )

    def save_ball(self) -> None:
        """Add or edit a declared sphere without inventing its orientation."""
        panel = self.panel
        if panel is None:
            return
        name = panel.name.text().strip() or panel.current_ladder()
        try:
            folder = rig_paths.pose3d_dir(self.window.rig_paths)
            if folder is None:
                self._status(tr("Open a recording before adding a prop."))
                return
            prop_path(folder, name)
            before = self.store.get(name)
            if before is None and name.casefold() in {
                used.casefold() for used in self.store.names()
            }:
                self._status(tr("That prop name is already used in this recording."))
                return
            if before is not None and not isinstance(before, BallProp):
                self._status(tr("That name belongs to a different prop kind."))
                return
            centre, radius, units = panel.ball_values()
            marks = before.surface_marks if isinstance(before, BallProp) else ()
            binding = before.binding if isinstance(before, BallProp) else None
            visual_frames = before.visual_frames if isinstance(before, BallProp) else ()
            visual_reference = (
                before.visual_reference_frame
                if isinstance(before, BallProp) and visual_frames
                else None
            )
            if isinstance(before, BallProp) and (
                before.surface != BallSurface(centre, radius) or before.units != units
            ):
                if binding is not None:
                    binding = dataclasses.replace(binding, checks=())
                visual_frames = ()
                visual_reference = None
            ball = BallProp(
                name,
                BallSurface(centre, radius),
                units,
                marks,
                binding,
                visual_reference,
                visual_frames,
            )
        except PropModelError:
            self._status(tr("Check the ball dimensions and choose a filename-safe prop name."))
            return
        label = (
            tr("Edit ball {name}").format(name=name)
            if before
            else tr("Add ball {name}").format(name=name)
        )
        self.window.document.execute(
            SetPhysicalPropCommand(name, before, ball, label), self.window._mutations
        )
        panel.select_prop(name, "ball")
        self._status(
            tr("Ball geometry saved; orientation binding kept.")
            if ball.binding
            else tr("Ball geometry saved; orientation remains unknown.")
        )

    def bind_belt(self) -> None:
        """Bind a measured displacement channel at the currently displayed frame."""
        panel = self.panel
        belt = self.store.get(panel.current_prop()) if panel is not None else None
        if panel is None or not isinstance(belt, BeltProp):
            return
        channel = panel.belt_channel.currentData()
        found = wheel_display.frame_and_time(self.window, self.window.clock.state.t)
        reading = (
            prop_motion.scalar_reading(self.window, channel[0], channel[1], found[1])
            if channel and found
            else None
        )
        if reading is None or found is None:
            self._status(tr("Choose a loaded displacement channel with a reading on this frame."))
            return
        try:
            binding = BeltBinding(
                channel[0],
                channel[1],
                found[0],
                reading,
                panel.belt_reference_distance.value(),
                panel.belt_scale.value(),
            )
            candidate = dataclasses.replace(
                belt, binding=binding, visual_reference_frame=None, visual_frames=()
            )
            candidate.material_point(reading)
        except PropModelError:
            self._status(tr("Set a travel direction along the path and a valid mark distance."))
            return
        self.window.document.execute(
            SetPhysicalPropCommand(belt.name, belt, candidate, tr("Bind belt displacement")),
            self.window._mutations,
        )
        self._status(
            tr("Belt displacement bound at frame {frame}; check a later frame.").format(
                frame=found[0]
            )
        )

    def bind_ball(self) -> None:
        """Bind four same-source quaternion channels and one identified mark."""
        panel = self.panel
        ball = self.store.get(panel.current_prop()) if panel is not None else None
        if panel is None or not isinstance(ball, BallProp):
            return
        keys = [combo.currentData() for combo in panel.ball_channels]
        if any(key is None for key in keys) or len({key[0] for key in keys if key}) != 1:
            self._status(tr("Choose four orientation channels from one source."))
            return
        typed_keys = [key for key in keys if key is not None]
        found = wheel_display.frame_and_time(self.window, self.window.clock.state.t)
        mark = tuple(float(field.value()) for field in panel.ball_mark_fields)
        norm = math.hypot(*mark)
        if found is None or norm < 1e-12:
            self._status(tr("Choose a displayed reference frame and a nonzero surface mark."))
            return
        mark = (mark[0] / norm, mark[1] / norm, mark[2] / norm)
        try:
            provisional = dataclasses.replace(ball, surface_marks=(mark,))
            binding = BallBinding(
                typed_keys[0][0],
                tuple(key[1] for key in typed_keys),
                found[0],
                # Read below from the same sample index before accepting the binding.
                UnitQuaternion.identity(),
            )
            provisional = dataclasses.replace(
                provisional, binding=binding, visual_reference_frame=None, visual_frames=()
            )
            raw = prop_motion.orientation_values(self.window, provisional, found[1])
            if raw is None:
                self._status(
                    tr("The four orientation components need one valid synchronized sample.")
                )
                return
            candidate = dataclasses.replace(
                provisional,
                binding=dataclasses.replace(
                    binding, reference_orientation=UnitQuaternion(*raw), reference_values=raw
                ),
            )
        except PropModelError:
            self._status(tr("Choose four distinct quaternion channels and a valid surface mark."))
            return
        self.window.document.execute(
            SetPhysicalPropCommand(ball.name, ball, candidate, tr("Bind ball orientation")),
            self.window._mutations,
        )
        self._status(
            tr("Ball orientation bound at frame {frame}; check a later frame.").format(
                frame=found[0]
            )
        )

    def start_visual_track(self, kind: str, name: str) -> None:
        """Collect named marks at displayed frames without inventing motion between them."""
        prop = self.store.get(name)
        if (
            (kind == "belt" and not isinstance(prop, BeltProp))
            or (kind == "ball" and not isinstance(prop, BallProp))
            or not isinstance(prop, (BeltProp, BallProp))
        ):
            return
        if isinstance(prop, BeltProp) and prop.travel_direction is None:
            self._status(tr("Set and save the belt travel direction before visual tracking."))
            return
        if isinstance(prop, BeltProp):
            assert prop.travel_direction is not None
            tangent = tuple(
                b - a for a, b in zip(prop.track.vertices[0], prop.track.vertices[1], strict=True)
            )
            alignment = sum(a * b for a, b in zip(tangent, prop.travel_direction, strict=True))
            if abs(alignment) < 1e-9 * math.hypot(*tangent):
                self._status(tr("Set the belt direction along its first path segment."))
                return
        if self.visual_tracking == (kind, name):
            self.cancel_step()
            return
        self.window._cancel_competing_placement("prop")
        if self.window.clock.state.playing:
            self.window.transport.play_toggled.emit(False)
        self.draft = None
        self.checking = None
        self.visual_tracking = (kind, name)
        self.window.video_grid.set_marker_place_mode(True)
        self._status(
            tr("Click the same belt mark in two calibrated cameras on each frame.")
            if kind == "belt"
            else tr("Choose A, B, or C; click that ball mark in two cameras on each frame.")
        )

    def clear_visual_track(self, kind: str, name: str) -> None:
        """Remove visual motion through an inverse command, preserving fixed geometry."""
        prop = self.store.get(name)
        if (
            (kind == "belt" and not isinstance(prop, BeltProp))
            or (kind == "ball" and not isinstance(prop, BallProp))
            or not isinstance(prop, (BeltProp, BallProp))
            or not prop.visual_frames
        ):
            return
        if isinstance(prop, BeltProp):
            changed: BeltProp | BallProp = dataclasses.replace(
                prop, visual_reference_frame=None, visual_frames=()
            )
        else:
            changed = dataclasses.replace(prop, visual_reference_frame=None, visual_frames=())
        self.window.document.execute(
            SetPhysicalPropCommand(name, prop, changed, tr("Clear visual prop track")),
            self.window._mutations,
        )
        self.cancel_step()

    def set_visual_lap(self, name: str) -> None:
        """Accept the user's explicit winding for one observed closed-path frame."""
        belt = self.store.get(name)
        panel = self.panel
        reference = wheel_display.frame_and_time(self.window, self.window.clock.state.t)
        if not isinstance(belt, BeltProp) or panel is None or reference is None:
            return
        if not belt.track.closed:
            return
        before = next((item for item in belt.visual_frames if item.frame == reference[0]), None)
        if before is None or not before.point.clicks:
            self._status(tr("Click the belt mark on this frame before setting its lap count."))
            return
        observed = dataclasses.replace(before, lap=panel.belt_lap.value())
        frames = tuple(
            observed if item.frame == before.frame else item for item in belt.visual_frames
        )
        changed = dataclasses.replace(belt, visual_frames=frames)
        self.window.document.execute(
            SetPhysicalPropCommand(name, belt, changed, tr("Set belt visual lap count")),
            self.window._mutations,
        )
        self._status(
            tr("Belt mark lap count set to {count} at frame {frame}.").format(
                count=observed.lap, frame=observed.frame
            )
        )

    def _record_visual_click(self, video: str, x: float, y: float) -> None:
        """Save one actual camera observation at the reference pane's current frame."""
        tracking = self.visual_tracking
        if tracking is None:
            return
        _kind, name = tracking
        prop = self.store.get(name)
        reference = wheel_display.frame_and_time(self.window, self.window.clock.state.t)
        camera_frame = prop_motion.frame_time(self.window, video, self.window.clock.state.t)
        if (
            reference is None
            or camera_frame is None
            or reference[0] < 0
            or camera_frame[0] < 0
            or not isinstance(prop, (BeltProp, BallProp))
        ):
            self._status(tr("Show a video frame before recording a visual prop mark."))
            return
        frame = reference[0]
        click = StepClick(rig_paths.camera_name(video), camera_frame[0], float(x), float(y))
        cameras = wheel_display.camera_models(self.window)
        changed: BeltProp | BallProp = (
            self._visual_belt_click(prop, frame, click, cameras)
            if isinstance(prop, BeltProp)
            else self._visual_ball_click(prop, frame, click, cameras)
        )
        self.window.document.execute(
            SetPhysicalPropCommand(name, prop, changed, tr("Record visual prop mark")),
            self.window._mutations,
        )
        self._visual_feedback(changed, frame, cameras)

    @staticmethod
    def _visual_belt_click(
        prop: BeltProp, frame: int, click: StepClick, cameras: dict[str, CameraModel]
    ) -> BeltProp:
        """Replace one camera's belt observation without losing its other views."""
        before = next((item for item in prop.visual_frames if item.frame == frame), None)
        observed = before or BeltVisualFrame(frame)
        observed = dataclasses.replace(
            observed, point=observed.point.with_click(click).resolved(cameras)
        )
        frames = tuple(item for item in prop.visual_frames if item.frame != frame) + (observed,)
        return dataclasses.replace(
            prop,
            binding=None,
            visual_reference_frame=prop.visual_reference_frame
            if prop.visual_reference_frame is not None
            else frame,
            visual_frames=tuple(sorted(frames, key=lambda item: item.frame)),
        )

    def _visual_ball_click(
        self, prop: BallProp, frame: int, click: StepClick, cameras: dict[str, CameraModel]
    ) -> BallProp:
        """Replace one named landmark's camera observation on this frame."""
        mark_index = int(self.panel.ball_visual_mark.currentData()) if self.panel else 0
        before = next((item for item in prop.visual_frames if item.frame == frame), None)
        observed = before or BallVisualFrame(frame)
        marks = list(observed.marks)
        marks[mark_index] = marks[mark_index].with_click(click).resolved(cameras)
        observed = dataclasses.replace(observed, marks=(marks[0], marks[1], marks[2]))
        frames = tuple(item for item in prop.visual_frames if item.frame != frame) + (observed,)
        return dataclasses.replace(
            prop,
            binding=None,
            visual_reference_frame=prop.visual_reference_frame
            if prop.visual_reference_frame is not None
            else frame,
            visual_frames=tuple(sorted(frames, key=lambda item: item.frame)),
        )

    def _visual_feedback(
        self, changed: BeltProp | BallProp, frame: int, cameras: dict[str, CameraModel]
    ) -> None:
        """Report fit quality and ambiguity without changing the raw observations."""
        result = prop_motion.visual_state(self.window, changed, frame)
        if isinstance(changed, BeltProp) and isinstance(result, BeltVisualState):
            travel = belt_visual_travel(changed, frame, cameras)
            detail = (
                tr("Signed travel {distance:g} {unit}.").format(
                    distance=travel, unit=changed.units or tr("calibration units")
                )
                if travel is not None
                else tr("Position solved; set lap counts for signed travel.")
            )
            self._status(
                tr("Frame {frame}: {detail} Offset {offset:.3g}; fit {error:.1f} px.").format(
                    frame=frame, detail=detail, offset=result.offset, error=result.error_px
                )
            )
        elif isinstance(result, BallVisualState):
            self._status(
                tr("Frame {frame}: rotation fit {residual:.3g}; pixel error {error:.1f}.").format(
                    frame=frame, residual=result.residual, error=result.error_px
                )
            )
        else:
            self._status(
                tr("Frame {frame} saved; more camera views or landmarks needed.").format(
                    frame=frame
                )
            )

    def start_check(self, kind: str, name: str) -> None:
        """Take the next video click as a later-frame motion check."""
        prop = self.store.get(name)
        if (
            (kind == "belt" and not isinstance(prop, BeltProp))
            or (kind == "ball" and not isinstance(prop, BallProp))
            or not isinstance(prop, (BeltProp, BallProp))
            or prop.binding is None
        ):
            return
        if self.checking == name:
            self.cancel_step()
            return
        self.window._cancel_competing_placement("prop")
        if self.window.clock.state.playing:
            self.window.transport.play_toggled.emit(False)
        self.draft = None
        self.checking = name
        self.window.video_grid.set_marker_place_mode(True)
        self._status(
            tr("Click the identified moving mark on a later frame in any calibrated camera.")
        )

    def remove_prop(self, kind: str, name: str) -> None:
        """Remove a selected belt or ball through an inverse command."""
        prop = self.store.get(name)
        if kind == "belt":
            if not isinstance(prop, BeltProp):
                return
        elif kind == "ball":
            if not isinstance(prop, BallProp):
                return
        else:
            return
        self.window.document.execute(
            SetPhysicalPropCommand(
                name, prop, None, tr("Remove {kind} {name}").format(kind=kind, name=name)
            ),
            self.window._mutations,
        )
        self._status(tr("Removed {kind} {name}.").format(kind=kind, name=name))

    def start_step(self, name: str, label: str, rung: bool) -> None:
        """Start collecting a foothold or explicit rung endpoints."""
        ladder = self.store.get(name)
        if not isinstance(ladder, Ladder):
            return
        self.window._cancel_competing_placement("prop")
        if self.window.clock.state.playing:
            self.window.transport.play_toggled.emit(False)
        self.draft = StepDraft(
            name,
            label or tr("Step {number}").format(number=len(ladder.steps) + 1),
            minimum_points=2 if rung else 1,
        )
        self.window.video_grid.set_marker_place_mode(True)
        self._status(tr("Click this point in each camera where it is visible."))
        self.refresh()

    def next_point(self) -> None:
        """Advance to another independently clicked point on this step."""
        draft = self.draft
        if draft is None or not draft.points[draft.active].clicks:
            self._status(tr("Click the current point in at least one camera first."))
            return
        if draft.active + 1 == len(draft.points):
            draft.points.append(LadderPoint())
        draft.active += 1
        self._status(
            tr("Click point {number} in its visible cameras.").format(number=draft.active + 1)
        )

    def on_clicked(self, video: str, x: float, y: float) -> bool:
        """Record exactly the clicked camera pixel and its displayed frame."""
        if self.visual_tracking is not None:
            self._record_visual_click(video, x, y)
            return True
        if self.checking is not None:
            prop = self.store.get(self.checking)
            if isinstance(prop, (BeltProp, BallProp)) and prop.binding is not None:
                check = prop_motion.check_click(self.window, prop, video, x, y)
                if check is None:
                    self._status(
                        tr("No predicted mark on this frame; check the camera and channels.")
                    )
                else:
                    if isinstance(prop, BeltProp):
                        belt_binding = dataclasses.replace(
                            prop.binding, checks=(*prop.binding.checks, check)
                        )
                        changed_belt = dataclasses.replace(prop, binding=belt_binding)
                    else:
                        ball_binding = dataclasses.replace(
                            prop.binding, checks=(*prop.binding.checks, check)
                        )
                        changed_ball = dataclasses.replace(prop, binding=ball_binding)
                    changed: BeltProp | BallProp = (
                        changed_belt if isinstance(prop, BeltProp) else changed_ball
                    )
                    self.window.document.execute(
                        SetPhysicalPropCommand(prop.name, prop, changed, tr("Check prop motion")),
                        self.window._mutations,
                    )
                    self._status(
                        tr("Frame {frame} check: {residual:.1f} px from predicted mark.").format(
                            frame=check.frame, residual=check.residual_px
                        )
                    )
                    self.cancel_step()
            return True
        draft = self.draft
        if draft is None:
            return False
        paths = self.window.video_grid.pane_paths()
        if video not in paths:
            return True
        pane = self.window.video_grid.panes[paths.index(video)]
        frame = int(pane.frame_record_at(self.window.clock.state.t)[0])
        click = StepClick(rig_paths.camera_name(video), frame, float(x), float(y))
        point = draft.points[draft.active].with_click(click)
        draft.points[draft.active] = point.resolved(wheel_display.camera_models(self.window))
        if draft.points[draft.active].xyz is not None:
            detail = tr("3D fit error {error:.1f} px.").format(
                error=draft.points[draft.active].error_px or 0.0
            )
        else:
            detail = tr("Still 2D; click this point in another calibrated camera.")
        self._status(
            tr("Recorded {camera} at frame {frame} for point {point}. {detail}").format(
                camera=click.camera, frame=frame, point=draft.active + 1, detail=detail
            )
        )
        self.refresh()
        return True

    def save_step(self) -> None:
        """Accept only the points the user actually clicked."""
        draft = self.draft
        if draft is None:
            return
        if len(draft.points) < draft.minimum_points or any(not p.clicks for p in draft.points):
            self._status(tr("Click every point in at least one camera before saving."))
            return
        closed = bool(self.panel.closed.isChecked()) if self.panel is not None else False
        if closed and len(draft.points) < 3:
            self._status(tr("A closed outline needs at least three clicked points."))
            return
        step = LadderStep(
            draft.before.step_id if draft.before is not None else uuid.uuid4().hex,
            draft.label,
            tuple(draft.points),
            closed,
        )
        self.window.document.execute(
            SetLadderStepCommand(
                draft.ladder,
                step.step_id,
                draft.before,
                step,
                tr("Edit step {label}").format(label=step.label)
                if draft.before is not None
                else tr("Add step {label}").format(label=step.label),
            ),
            self.window._mutations,
        )
        self.cancel_step()
        unresolved = sum(point.xyz is None for point in step.points)
        if unresolved:
            self._status(tr("Step saved; {count} point(s) are still 2D.").format(count=unresolved))
        else:
            self._status(tr("Step saved with its original clicks and 3D fit."))

    def cancel_step(self) -> None:
        """Discard an unfinished prop click or motion check."""
        self.draft = None
        self.checking = None
        self.visual_tracking = None
        self.window.video_grid.set_marker_place_mode(False)
        self.refresh()

    def remove_step(self, name: str, step_id: str) -> None:
        """Delete one step without changing its neighbours."""
        ladder = self.store.get(name)
        if not isinstance(ladder, Ladder):
            return
        for position, step in enumerate(ladder.steps):
            if step.step_id == step_id:
                self.window.document.execute(
                    SetLadderStepCommand(
                        name,
                        step_id,
                        step,
                        None,
                        tr("Remove step {label}").format(label=step.label),
                        position,
                    ),
                    self.window._mutations,
                )
                return

    def reclick_step(self, name: str, step_id: str) -> None:
        """Revisit the exact points and overwrite only cameras the user clicks."""
        ladder = self.store.get(name)
        if not isinstance(ladder, Ladder):
            return
        step = next((item for item in ladder.steps if item.step_id == step_id), None)
        if step is None:
            return
        self.window._cancel_competing_placement("prop")
        self.draft = StepDraft(
            name, step.label, list(step.points), minimum_points=len(step.points), before=step
        )
        if self.panel is not None:
            self.panel.closed.setChecked(step.closed)
        self.window.video_grid.set_marker_place_mode(True)
        self._status(tr("Re-click point 1 in the cameras you want to correct."))
        self.refresh()

    def relabel_step(self, name: str, step_id: str, label: str) -> None:
        """Rename one step without rebuilding any neighbour or pixel click."""
        ladder = self.store.get(name)
        if not isinstance(ladder, Ladder):
            return
        step = next((item for item in ladder.steps if item.step_id == step_id), None)
        if step is None or step.label == label:
            return
        changed = dataclasses.replace(step, label=label)
        self.window.document.execute(
            SetLadderStepCommand(
                name, step_id, step, changed, tr("Rename step {label}").format(label=label)
            ),
            self.window._mutations,
        )

    def move_step(self, name: str, step_id: str, offset: int) -> None:
        """Reorder one step by index, preserving each observation."""
        ladder = self.store.get(name)
        if not isinstance(ladder, Ladder):
            return
        old = next((i for i, s in enumerate(ladder.steps) if s.step_id == step_id), -1)
        new = old + offset
        if old < 0 or not 0 <= new < len(ladder.steps):
            return
        self.window.document.execute(
            MoveLadderStepCommand(name, step_id, old, new, tr("Reorder ladder step")),
            self.window._mutations,
        )

    def remove_ladder(self, name: str) -> None:
        """Remove the selected ladder with an inverse retaining its clicks."""
        previous = self.store.get(name)
        if isinstance(previous, Ladder):
            self.window.document.execute(
                SetLadderCommand(
                    name, previous, None, tr("Remove ladder {name}").format(name=name)
                ),
                self.window._mutations,
            )

    def _status(self, message: str) -> None:
        if self.panel is not None:
            self.panel.status.setText(message)
        self.window.transport.set_status(message, "info")

    def _changed(self, _name: str | None) -> None:
        self._display_key = None
        if _name is None:
            for prop in self.store:
                self._known_kinds[prop.name] = prop_kind(prop)
        else:
            changed_prop = self.store.get(_name)
            if changed_prop is not None:
                self._known_kinds[_name] = prop_kind(changed_prop)
        if self.panel is not None:
            self.panel.refresh()
        self.refresh()

    def _resolved_for_display(self, cameras: dict[str, CameraModel]) -> tuple[Ladder, ...]:
        """Cache derived positions against the current calibration and raw clicks."""
        key = tuple(sorted((name, id(model)) for name, model in cameras.items()))
        if key != self._display_key:
            self._display_ladders = tuple(
                dataclasses.replace(
                    ladder,
                    steps=tuple(step.resolved(cameras) for step in ladder.steps),
                )
                for ladder in self.store
                if isinstance(ladder, Ladder)
            )
            self._display_key = key
        return self._display_ladders

    def refresh(self) -> None:
        """Repaint every pane and the 3D view after a store or draft change."""
        if hasattr(self.window, "video_grid"):
            for pane in self.window.video_grid.panes:
                pane.paint_canvas.update()
        if hasattr(self.window, "tracking_3d_pane"):
            self.window.tracking_3d_pane.canvas.set_cursor(self.window.clock.state.t)

    def _motion_at(
        self, prop: BeltProp | BallProp, frame: int, t_frame: float
    ) -> tuple[Point3, ...]:
        """Return observed visual marks or the channel-driven mark at this frame."""
        if prop.visual_frames:
            state = prop_motion.visual_state(self.window, prop, frame)
            if isinstance(state, BeltVisualState):
                return (state.point,)
            if isinstance(state, BallVisualState):
                return state.marks
            return ()
        point = prop_motion.material_point(self.window, prop, t_frame)
        return () if point is None else (point,)

    def _visual_pixels(
        self, prop: BeltProp | BallProp, camera: str, frame: int, camera_frame: int
    ) -> list[PropDrawing]:
        """Show actual visual clicks on their own video frame, even before stereo fit."""
        observation = next((item for item in prop.visual_frames if item.frame == frame), None)
        if observation is None:
            return []
        points = (
            (observation.point,) if isinstance(observation, BeltVisualFrame) else observation.marks
        )
        drawings: list[PropDrawing] = []
        for index, point in enumerate(points):
            click = next(
                (
                    item
                    for item in point.clicks
                    if item.camera == camera and item.frame == camera_frame
                ),
                None,
            )
            if click is not None:
                label = (
                    tr("{name} visual belt mark").format(name=prop.name)
                    if isinstance(prop, BeltProp)
                    else tr("{name} visual ball mark {mark}").format(
                        name=prop.name, mark=("A", "B", "C")[index]
                    )
                )
                drawings.append((label, ((click.x, click.y, True),), False))
        return drawings

    def camera_drawing(self, video: str, _time: float) -> list[PropDrawing]:
        """Observed pixels first; only solved points may project to another view."""
        camera = rig_paths.camera_name(video)
        cameras = wheel_display.camera_models(self.window)
        model = cameras.get(camera)
        depth_axis = model.rotation_matrix()[2] if model is not None else None
        drawings: list[PropDrawing] = []
        for ladder in self._resolved_for_display(cameras):
            for step in ladder.steps:
                pixels: list[PropPixel] = []
                for point in step.points:
                    click = next((c for c in point.clicks if c.camera == camera), None)
                    if click is not None:
                        pixels.append((click.x, click.y, True))
                    elif model is not None and point.xyz is not None:
                        xyz = np.asarray(point.xyz, dtype=np.float64)
                        assert depth_axis is not None
                        depth = float(depth_axis @ xyz + model.translation[2])
                        if not np.isfinite(depth) or depth <= 0.0:
                            pixels.append(None)
                            continue
                        xy = model.project(xyz)[0]
                        if np.all(np.isfinite(xy)):
                            pixels.append((float(xy[0]), float(xy[1]), False))
                        else:
                            pixels.append(None)
                    else:
                        pixels.append(None)
                if any(pixel is not None for pixel in pixels):
                    drawings.append((step.label, tuple(pixels), step.closed))
        for prop in self.store:
            if isinstance(prop, BeltProp):
                camera_frame = prop_motion.frame_time(self.window, video, _time)
                reference = wheel_display.frame_and_time(self.window, _time)
                marks = self._motion_at(prop, reference[0], reference[1]) if reference else ()
                material = marks[0] if marks else None
                belt_pixels = tuple(
                    self._project_declared(model, point) for point in prop.track.vertices
                )
                if any(pixel is not None for pixel in belt_pixels):
                    drawings.append(
                        (
                            (
                                tr("{name} (declared; motion unknown)").format(name=prop.name)
                                if prop.binding is None and not prop.visual_frames
                                else tr("{name} (motion unavailable)").format(name=prop.name)
                                if material is None
                                else tr("{name} support").format(name=prop.name)
                            ),
                            belt_pixels,
                            prop.track.closed,
                        )
                    )
                if material is not None:
                    pixel = self._project_declared(model, material)
                    if pixel is not None:
                        drawings.append(
                            (tr("{name} moving mark").format(name=prop.name), (pixel,), False)
                        )
                if reference is not None and camera_frame is not None and prop.visual_frames:
                    drawings.extend(
                        self._visual_pixels(prop, camera, reference[0], camera_frame[0])
                    )
            elif isinstance(prop, BallProp):
                camera_frame = prop_motion.frame_time(self.window, video, _time)
                reference = wheel_display.frame_and_time(self.window, _time)
                marks = self._motion_at(prop, reference[0], reference[1]) if reference else ()
                material = marks[0] if marks else None
                for plane, points in _ball_rings(prop):
                    ball_pixels = tuple(self._project_declared(model, point) for point in points)
                    if any(pixel is not None for pixel in ball_pixels):
                        drawings.append(
                            (
                                (
                                    tr("{name} {plane} (declared; orientation unknown)").format(
                                        name=prop.name, plane=plane
                                    )
                                    if prop.binding is None and not prop.visual_frames
                                    else tr("{name} {plane} (orientation unavailable)").format(
                                        name=prop.name, plane=plane
                                    )
                                    if material is None
                                    else tr("{name} {plane} support").format(
                                        name=prop.name, plane=plane
                                    )
                                ),
                                ball_pixels,
                                True,
                            )
                        )
                for index, mark in enumerate(marks):
                    pixel = self._project_declared(model, mark)
                    if pixel is not None:
                        drawings.append(
                            (
                                tr("{name} moving mark {mark}").format(
                                    name=prop.name, mark=("A", "B", "C")[index]
                                )
                                if prop.visual_frames
                                else tr("{name} moving mark").format(name=prop.name),
                                (pixel,),
                                False,
                            )
                        )
                if reference is not None and camera_frame is not None and prop.visual_frames:
                    drawings.extend(
                        self._visual_pixels(prop, camera, reference[0], camera_frame[0])
                    )
        if self.draft is not None:
            pixels = []
            for point in self.draft.points:
                click = next((c for c in point.clicks if c.camera == camera), None)
                if click is not None:
                    pixels.append((click.x, click.y, True))
                else:
                    pixels.append(None)
            if any(pixel is not None for pixel in pixels):
                drawings.append((self.draft.label, tuple(pixels), False))
        return drawings

    def scene_steps(self, _time: float) -> list[tuple[str, tuple[np.ndarray | None, ...], bool]]:
        """Only triangulated points enter 3D; unsolved points stay in camera views."""
        steps: list[tuple[str, tuple[np.ndarray | None, ...], bool]] = []
        for ladder in self._resolved_for_display(wheel_display.camera_models(self.window)):
            for step in ladder.steps:
                positions = tuple(
                    None if point.xyz is None else np.asarray(point.xyz, dtype=np.float64)
                    for point in step.points
                )
                if any(position is not None for position in positions):
                    steps.append((step.label, positions, step.closed))
        for prop in self.store:
            if isinstance(prop, BeltProp):
                reference = (
                    wheel_display.frame_and_time(self.window, _time)
                    if prop.binding or prop.visual_frames
                    else None
                )
                marks = self._motion_at(prop, reference[0], reference[1]) if reference else ()
                material = marks[0] if marks else None
                steps.append(
                    (
                        (
                            tr("{name} (declared; motion unknown)").format(name=prop.name)
                            if prop.binding is None and not prop.visual_frames
                            else tr("{name} (motion unavailable)").format(name=prop.name)
                            if material is None
                            else tr("{name} support").format(name=prop.name)
                        ),
                        tuple(np.asarray(point, dtype=np.float64) for point in prop.track.vertices),
                        prop.track.closed,
                    )
                )
                if material is not None:
                    steps.append(
                        (
                            tr("{name} moving mark").format(name=prop.name),
                            (np.asarray(material),),
                            False,
                        )
                    )
            elif isinstance(prop, BallProp):
                reference = (
                    wheel_display.frame_and_time(self.window, _time)
                    if prop.binding or prop.visual_frames
                    else None
                )
                marks = self._motion_at(prop, reference[0], reference[1]) if reference else ()
                material = marks[0] if marks else None
                for plane, points in _ball_rings(prop):
                    steps.append(
                        (
                            (
                                tr("{name} {plane} (declared; orientation unknown)").format(
                                    name=prop.name, plane=plane
                                )
                                if prop.binding is None and not prop.visual_frames
                                else tr("{name} {plane} (orientation unavailable)").format(
                                    name=prop.name, plane=plane
                                )
                                if material is None
                                else tr("{name} {plane} support").format(
                                    name=prop.name, plane=plane
                                )
                            ),
                            tuple(np.asarray(point, dtype=np.float64) for point in points),
                            True,
                        )
                    )
                for index, mark in enumerate(marks):
                    steps.append(
                        (
                            tr("{name} moving mark {mark}").format(
                                name=prop.name, mark=("A", "B", "C")[index]
                            )
                            if prop.visual_frames
                            else tr("{name} moving mark").format(name=prop.name),
                            (np.asarray(mark),),
                            False,
                        )
                    )
        return steps

    @staticmethod
    def _project_declared(camera: CameraModel | None, point: Point3) -> PropPixel | None:
        """Project declared 3D geometry as a guide, not a clicked observation."""
        if camera is None:
            return None
        xyz = np.asarray(point, dtype=np.float64)
        camera_point = camera.rotation_matrix() @ xyz + camera.translation
        if not np.isfinite(camera_point).all() or camera_point[2] <= 0.0:
            return None
        pixel = camera.project(xyz)[0]
        if not np.isfinite(pixel).all():
            return None
        return (float(pixel[0]), float(pixel[1]), False)

    def reset(self) -> None:
        """Forget this session's props and discovery state."""
        self.cancel_step()
        self.store.clear()
        self._adopted.clear()
        self._known_kinds.clear()
        self._edited.clear()
        self._known_sidecars.clear()

    def persist(self, name: str) -> None:
        """Queue the latest accepted revision, serialized per recording folder."""
        self._edited.add(name)
        folder = rig_paths.pose3d_dir(self.window.rig_paths)
        if folder is None:
            return
        prop = self.store.get(name)
        kind = prop_kind(prop) if prop is not None else self._known_kinds.get(name, "ladder")
        self._pending.setdefault(folder, {})[name] = (prop, kind)
        self._write_next(folder)

    def _write_next(self, folder: Path) -> None:
        if folder in self._writing or not self._pending.get(folder):
            return
        name, (prop, kind) = self._pending[folder].popitem()
        self._writing.add(folder)
        worker = PropFileWriteWorker(
            folder,
            name,
            prop,
            kind=kind,
            overwrite_existing=(folder, name) in self._known_sidecars,
        )

        def complete(path: Path | None = None, error: str = "") -> None:
            self._writing.discard(folder)
            if error:
                self.window.notifications.show_warning(
                    tr("Prop {name} could not be saved beside the data.").format(name=name),
                    details=error,
                )
            elif path is not None:
                self._known_sidecars.add((folder, name))
                self.window.notifications.show_success(
                    tr("Prop {name} saved as {file}.").format(name=name, file=path.name)
                )
            self._write_next(folder)

        def wire(_thread: QThread) -> None:
            worker.finished.connect(on_ui_thread(lambda path: complete(path), self.window))
            worker.error.connect(on_ui_thread(lambda error: complete(error=error), self.window))

        self.window._run_job(worker, label=tr("Saving physical prop"), configure=wire)

    def adopt(self) -> None:
        """Load sidecars after the recording folder becomes known."""
        self._update_create_availability()
        folder = rig_paths.pose3d_dir(self.window.rig_paths)
        if folder is None or folder in self._adopted:
            return
        self._adopted.add(folder)
        generation = self.window.session_runtime.generation
        worker = PropFileReadWorker(folder)

        def finished(props: list[PropRecord], issues: list[PropFileIssue]) -> None:
            if generation != self.window.session_runtime.generation:
                return
            for issue in issues:
                self.window.notifications.show_warning(
                    tr("Saved prop {file} could not be shown.").format(file=issue.filename),
                    details=issue.reason,
                )
            existing = {prop.name: prop for prop in self.store}
            for prop in props:
                if prop.name not in self._edited and prop.name not in existing:
                    existing[prop.name] = prop
                    self._known_sidecars.add((folder, prop.name))
            self.store.load(existing.values())
            if existing:
                calibration_controller.calibration_quietly(self.window)
                self.refresh()

        def failed(error: str) -> None:
            if generation != self.window.session_runtime.generation:
                return
            self._adopted.discard(folder)
            self.window.notifications.show_warning(
                tr("Saved physical props could not be read."),
                details=error,
                action_label=tr("Retry"),
                on_action=self.adopt,
            )

        def wire(_thread: QThread) -> None:
            worker.finished.connect(on_ui_thread(finished, self.window))
            worker.error.connect(on_ui_thread(failed, self.window))

        self.window._run_job(worker, label=tr("Reading saved physical props"), configure=wire)
