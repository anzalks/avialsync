"""Live physical-prop editing, sidecar jobs, and camera projections (D-149)."""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QThread

from avialsync.core.calibration import CameraModel
from avialsync.core.commands import MoveLadderStepCommand, SetLadderCommand, SetLadderStepCommand
from avialsync.core.errors import PropModelError
from avialsync.core.physical_props import Ladder, LadderPoint, LadderStep, PropStore, StepClick
from avialsync.core.prop_file import PropFileIssue, prop_path
from avialsync.engine.prop_file_worker import PropFileReadWorker, PropFileWriteWorker
from avialsync.ui.controllers import calibration_controller, rig_paths, wheel_display
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


class PropsApp:
    """Small coordinator for props; the document bus owns accepted edits."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window
        self.store = PropStore()
        self.store.observe(self._changed)
        self.panel: PropsPanel | None = None
        self.tab: PropsTab | None = None
        self.draft: StepDraft | None = None
        self._adopted: set[Path] = set()
        self._edited: set[str] = set()
        self._writing: set[Path] = set()
        self._pending: dict[Path, dict[str, Ladder | None]] = {}
        self._known_sidecars: set[tuple[Path, str]] = set()
        self._display_key: tuple[tuple[str, int], ...] | None = None
        self._display_ladders: tuple[Ladder, ...] = ()

    def make_panel(self) -> PropsTab:
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
        self.panel = panel
        panel.kind.currentIndexChanged.connect(self._update_create_availability)
        self.tab = PropsTab(panel, self.window)
        self._update_create_availability()
        return self.tab

    def show(self) -> None:
        """Show the inspector from the live Edit action."""
        if self.panel is not None and self.tab is not None:
            self._update_create_availability()
            self.window._left_tabs.setCurrentWidget(self.tab)
            self.panel.name.setFocus()

    def _update_create_availability(self) -> None:
        """Explain missing video context before a creation gesture (D-107)."""
        panel = self.panel
        if panel is None:
            return
        if panel.kind.currentData() == "wheel":
            available = (
                self.window._act_add_wheel.isEnabled()
                if hasattr(self.window, "_act_add_wheel")
                else False
            )
            reason = (
                self.window._act_add_wheel.toolTip()
                if hasattr(self.window, "_act_add_wheel")
                else tr("Load two camera videos first.")
            )
        else:
            available = rig_paths.pose3d_dir(self.window.rig_paths) is not None
            reason = tr("Open a recording before adding a prop.")
        panel.create_button.setEnabled(available)
        panel.create_button.setToolTip("" if available else reason)

    def create(self, name: str) -> None:
        """Accept one named static ladder, or open the existing wheel editor."""
        if self.panel is not None and self.panel.kind.currentData() == "wheel":
            self.window._left_tabs.setCurrentWidget(self.window.wheel_tab)
            self.window._act_add_wheel.trigger()
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
            if self.store.get(name) is not None or self.window.wheels.get(name) is not None:
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
            self.panel.select(name)

    def start_step(self, name: str, label: str, rung: bool) -> None:
        """Start collecting a foothold or explicit rung endpoints."""
        ladder = self.store.get(name)
        if ladder is None:
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
        """Discard only the unfinished click draft."""
        self.draft = None
        self.window.video_grid.set_marker_place_mode(False)
        self.refresh()

    def remove_step(self, name: str, step_id: str) -> None:
        """Delete one step without changing its neighbours."""
        ladder = self.store.get(name)
        if ladder is None:
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
        if ladder is None:
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
        if ladder is None:
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
        if ladder is None:
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
        if previous is not None:
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
        return steps

    def reset(self) -> None:
        """Forget this session's props and discovery state."""
        self.cancel_step()
        self.store.clear()
        self._adopted.clear()
        self._edited.clear()
        self._known_sidecars.clear()

    def persist(self, name: str) -> None:
        """Queue the latest accepted revision, serialized per recording folder."""
        self._edited.add(name)
        folder = rig_paths.pose3d_dir(self.window.rig_paths)
        if folder is None:
            return
        self._pending.setdefault(folder, {})[name] = self.store.get(name)
        self._write_next(folder)

    def _write_next(self, folder: Path) -> None:
        if folder in self._writing or not self._pending.get(folder):
            return
        name, ladder = self._pending[folder].popitem()
        self._writing.add(folder)
        worker = PropFileWriteWorker(
            folder, name, ladder, overwrite_existing=(folder, name) in self._known_sidecars
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

        def finished(props: list[Ladder], issues: list[PropFileIssue]) -> None:
            if generation != self.window.session_runtime.generation:
                return
            for issue in issues:
                self.window.notifications.show_warning(
                    tr("Saved prop {file} could not be shown.").format(file=issue.filename),
                    details=issue.reason,
                )
            existing = {ladder.name: ladder for ladder in self.store}
            for ladder in props:
                if (
                    ladder.name not in self._edited
                    and ladder.name not in existing
                    and self.window.wheels.get(ladder.name) is None
                ):
                    existing[ladder.name] = ladder
                    self._known_sidecars.add((folder, ladder.name))
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
