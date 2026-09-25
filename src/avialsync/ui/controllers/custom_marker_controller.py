"""Add 3D Marker: name a point, click it in every camera, see it in 3D.

The flow, end to end:

1. The action asks for a name (:mod:`avialsync.ui.custom_marker_dialogs`).
2. The calibration is resolved, imported or fitted
   (:mod:`avialsync.ui.controllers.calibration_controller`).
3. Every pane takes a left click as the marker's position, in any order;
   clicking a pane again re-places it there. Playback is paused, as for Fix
   Tracker, and the marker belongs to the frame on screen.
4. Once every calibrated camera has a click the point is triangulated and the
   marker goes through the command bus (rule 14), so it can be undone.

Afterwards a marker is a regular point: Fix Tracker drags it (re-triangulating
on release), and with Fix Tracker off the pane's context menu deletes it.

**Where markers live.** Beside the data, never in it (D-099's rule, applied
here): a DLC-layout CSV per camera next to that camera's 2D pose file (in
``pose-3d/`` for a camera without one), and an anipose-layout CSV next to the
3D pose file (see :mod:`avialsync.core.custom_markers`). They are written on every change, from
the mutation funnel, and read back as pose sources are imported.

**Frames.** A marker is keyed by the video frame the panes show when it is
placed. On an AOL session every camera shows the same frame number for the same
instant, and that number is the anipose ``fnum``; a click in a pane that has
moved to another frame starts the placement over on that frame rather than
mixing two instants in one triangulation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from avialsync.core import custom_markers
from avialsync.core.calibration import triangulate
from avialsync.core.commands import SetCustomMarkerCommand
from avialsync.core.custom_markers import CustomMarker
from avialsync.core.errors import CalibrationError
from avialsync.ui.controllers import calibration_controller as calibration
from avialsync.ui.controllers import rig_paths
from avialsync.ui.custom_marker_dialogs import ask_marker_name
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


@dataclass
class Placement:
    """A marker being placed: its name, its frame, and the clicks so far."""

    name: str
    frame: int
    #: Video path -> ``(x, y)`` in that video's pixels.
    clicks: dict[str, tuple[float, float]] = field(default_factory=dict)


# ── where things are ─────────────────────────────────────────────────


def _marker_file_2d(window: MainWindow, video: str) -> Path:
    """Beside the camera's 2D pose file; in ``pose-3d/`` when it has none.

    Never beside the video itself: a recording folder is the acquisition's, and
    ``pose-3d/`` is where this session's derived files already go.
    """
    pose = rig_paths.pose_2d_file(window, video)
    if pose is not None:
        return custom_markers.marker_file_for(pose)
    folder = rig_paths.pose3d_dir(window) or Path(video).parent
    return folder / f"{rig_paths.camera_name(video)}{custom_markers.MARKER_SUFFIX}"


def _marker_file_3d(window: MainWindow) -> Path | None:
    if window._pose_3d_sources:
        return custom_markers.marker_file_for(next(iter(window._pose_3d_sources)))
    folder = rig_paths.pose3d_dir(window)
    return None if folder is None else folder / f"pose{custom_markers.MARKER_SUFFIX}"


# ── the placement gesture ────────────────────────────────────────────


def _set_action_checked(window: MainWindow, checked: bool) -> None:
    action = window._act_add_marker
    blocked = action.blockSignals(True)
    try:
        action.setChecked(checked)
    finally:
        action.blockSignals(blocked)


def _taken_names(window: MainWindow) -> set[str]:
    names = set(window.custom_markers.names())
    for sources in window._overlay_sources.values():
        for entry in sources.values():
            names.update(entry.get("points", {}).keys())
    names.update(window.tracking_3d_pane.canvas.point_names)
    return names


def toggled(window: MainWindow, checked: bool) -> None:
    """The Add 3D Marker action: start a placement, or cancel the one running."""
    if not checked:
        cancel(window, tr("3D marker not added."))
        return
    name = ask_marker_name(window, _taken_names(window))
    if name is None:
        _set_action_checked(window, False)
        return
    calibration.acquire_calibration(
        window,
        lambda: _begin_placement(window, name),
        lambda: _set_action_checked(window, False),
    )


def _begin_placement(window: MainWindow, name: str) -> None:
    frame = rig_paths.frame_at(window, window.clock.state.t)
    if frame is None:
        _set_action_checked(window, False)
        return
    if window._act_fix_tracker.isChecked():
        window._act_fix_tracker.setChecked(False)
    # Both take the same click; a wheel being placed or checked gives way.
    from avialsync.ui.controllers import wheel_controller

    wheel_controller.cancel(window, tr("Wheel not added."))
    wheel_controller.stop_checking(window)
    if window.clock.state.playing:
        window.transport.play_toggled.emit(False)
    window._marker_placement = Placement(name=name, frame=frame)
    _set_action_checked(window, True)
    window.video_grid.set_marker_place_mode(True)
    _report_progress(window)


def _report_progress(window: MainWindow) -> None:
    placement = window._marker_placement
    state = window._calibration_state
    if placement is None or state is None:
        return
    remaining = [Path(v).stem for v in state.cameras if v not in placement.clicks]
    window.transport.set_status(
        tr("{name} at frame {frame}: {done}/{total} cameras — click it in {rest}.").format(
            name=placement.name,
            frame=placement.frame,
            done=len(placement.clicks),
            total=len(state.cameras),
            rest=", ".join(remaining),
        ),
        "info",
    )


def cancel(window: MainWindow, message: str | None = None) -> None:
    """Abandon a placement in progress, if there is one."""
    had = window._marker_placement is not None
    window._marker_placement = None
    window.video_grid.set_marker_place_mode(False)
    _set_action_checked(window, False)
    if had and message:
        window.transport.set_status(message, "info")


def on_clicked(window: MainWindow, video: str, x: float, y: float) -> None:
    """One click of a placement: record it, and finish once every camera has one."""
    placement = window._marker_placement
    state = window._calibration_state
    if placement is None or state is None:
        return
    if video not in state.cameras:
        window.transport.set_status(
            tr("{camera} is not in the calibration; click the marker in another camera.").format(
                camera=Path(video).stem
            ),
            "warning",
        )
        return
    frame = rig_paths.frame_at(window, window.clock.state.t)
    if frame is not None and frame != placement.frame:
        placement.frame = frame
        placement.clicks.clear()
    placement.clicks[video] = (float(x), float(y))
    if len(placement.clicks) < len(state.cameras):
        _report_progress(window)
        return
    marker = CustomMarker(name=placement.name, frame=placement.frame)
    for clicked, (cx, cy) in placement.clicks.items():
        marker = marker.with_view(rig_paths.camera_name(clicked), cx, cy)
    solved = _triangulated(window, marker)
    cancel(window)
    if solved is None:
        return
    window.document.execute(
        SetCustomMarkerCommand(solved.name, solved.frame, None, solved), window._mutations
    )
    window.transport.set_status(
        tr("{name} added at frame {frame} ({error:.1f} px reprojection).").format(
            name=solved.name, frame=solved.frame, error=solved.error or 0.0
        ),
        "info",
    )


def _triangulated(window: MainWindow, marker: CustomMarker) -> CustomMarker | None:
    """*marker* with its 3D position solved from every calibrated view."""
    state = window._calibration_state
    if state is None:
        return None
    by_camera = {rig_paths.camera_name(video): model for video, model in state.cameras.items()}
    views = [(by_camera[camera], (x, y)) for camera, x, y in marker.views if camera in by_camera]
    try:
        xyz, error = triangulate(views)
    except CalibrationError as failure:
        window.report_failure(
            failure, doing=tr("{name} could not be placed in 3D").format(name=marker.name)
        )
        return None
    return CustomMarker(
        name=marker.name,
        frame=marker.frame,
        views=marker.views,
        xyz=(float(xyz[0]), float(xyz[1]), float(xyz[2])),
        error=error,
    )


def on_moved(window: MainWindow, video: str, name: str, frame: int, x: float, y: float) -> None:
    """A Fix Tracker drag of a custom marker: re-triangulate, as one undo step."""
    before = window.custom_markers.get(name, frame)
    if before is None:
        return
    moved = before.with_view(rig_paths.camera_name(video), x, y)
    if not calibration.resolve_calibration(window):
        # No calibration to re-solve with: keep the click, keep the old 3D
        # rather than dropping it, and say so.
        moved = CustomMarker(moved.name, moved.frame, moved.views, before.xyz, before.error)
        window.notifications.show_warning(
            tr("No calibration is loaded, so {name}'s 3D position was not updated.").format(
                name=name
            )
        )
    else:
        moved = _triangulated(window, moved) or moved
    window.document.execute(SetCustomMarkerCommand(name, frame, before, moved), window._mutations)


def delete(window: MainWindow, name: str, frame: int) -> None:
    """Remove one marker from every camera and the 3D view, undoably."""
    before = window.custom_markers.get(name, frame)
    if before is None:
        return
    window.document.execute(SetCustomMarkerCommand(name, frame, before, None), window._mutations)


# ── display, persistence, adoption ───────────────────────────────────


def refresh(window: MainWindow) -> None:
    """Push the store to every pane and the 3D view."""
    for video in set(rig_paths.open_videos(window)) | set(window._overlay_sources):
        camera = rig_paths.camera_name(video)
        by_frame: dict[int, list[tuple[str, float, float]]] = {}
        for marker in window.custom_markers:
            view = marker.view(camera)
            if view is not None:
                by_frame.setdefault(marker.frame, []).append((marker.name, view[0], view[1]))
        window.video_grid.set_custom_markers(video, by_frame)
    window.tracking_3d_pane.canvas.set_cursor(window.clock.state.t)
    window._update_tracking_pane_visibility()


def points_at(window: MainWindow, t_master: float) -> list[tuple[str, np.ndarray]]:
    """The 3D view's hand-placed markers at *t_master*: those on the frame shown.

    A marker exists on the frame it was placed on and nowhere else (D-112). The
    earlier behaviour -- every marker assumed bolted to a wheel and carried by
    the encoder -- is the wheel model now (D-113), where it is declared,
    fitted, and checked rather than assumed.
    """
    if not len(window.custom_markers):
        return []
    frame = rig_paths.frame_at(window, t_master)
    if frame is None:
        return []
    return [
        (marker.name, np.asarray(marker.xyz, dtype=np.float64))
        for marker in window.custom_markers.at_frame(frame)
        if marker.xyz is not None
    ]


def persist(window: MainWindow) -> None:
    """Write every camera's marker file and the 3D one, now.

    Called only from the mutation funnel, so reading the files back in never
    echoes them straight out again (the D-099 rule for corrections).
    """
    markers = list(window.custom_markers)
    written: list[Path] = []
    try:
        for video in rig_paths.open_videos(window):
            target_2d = _marker_file_2d(window, video)
            # The pose-3d fallback may not exist yet; a pose file's folder does.
            target_2d.parent.mkdir(parents=True, exist_ok=True)
            written.append(
                custom_markers.write_2d(target_2d, rig_paths.camera_name(video), markers)
            )
        target = _marker_file_3d(window)
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            written.append(custom_markers.write_3d(target, markers))
    except OSError as error:
        logger.warning("Could not write custom markers", exc_info=True)
        window.notifications.show_warning(
            tr("3D markers could not be saved beside the data."), details=str(error)
        )
        return
    if written and not window._announced_marker_files:
        window._announced_marker_files = True
        window.notifications.show_success(
            tr("3D markers are saved beside the pose files, in {file} and its siblings.").format(
                file=written[-1].name
            )
        )


def adopt(window: MainWindow) -> None:
    """Read the marker files beside whatever pose data is loaded now.

    Called as each pose source registers; reading every file each time is a
    handful of short CSVs, and it means the order sources arrive in does not
    matter.
    """
    views: dict[tuple[str, int], list[tuple[str, float, float]]] = {}
    for video in set(rig_paths.open_videos(window)) | set(window._overlay_sources):
        camera = rig_paths.camera_name(video)
        source = _marker_file_2d(window, video)
        if not source.exists():
            # The first D-112 build wrote a camera without a pose file beside
            # its video; read that until this camera's file is written anew.
            source = custom_markers.marker_file_for(Path(video))
        for key, (x, y) in custom_markers.read_2d(source).items():
            views.setdefault(key, []).append((camera, x, y))
    target = _marker_file_3d(window)
    solved = custom_markers.read_3d(target) if target is not None else {}
    # A marker with a 3D position but no view in any camera is real too: one
    # placed by geometry rather than by clicking (a wheel's bars, most of them
    # out of shot) exists only in the 3D file.
    for key in solved:
        views.setdefault(key, [])
    if not views:
        return
    markers = []
    for (name, frame), placed in views.items():
        xyz, error = solved.get((name, frame), (None, None))
        markers.append(
            CustomMarker(
                name=name,
                frame=frame,
                views=tuple(sorted(placed)),
                xyz=xyz,
                error=error,
            )
        )
    # Markers on disk mean a calibration was in use: pick it up now, without
    # asking, so reprojection can draw them from the first frame shown rather
    # than only after Add 3D Marker is pressed.
    calibration.calibration_quietly(window)
    window.custom_markers.load(markers)
