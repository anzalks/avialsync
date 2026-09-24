"""Add 3D Marker: name a point, click it in every camera, see it in 3D.

The flow, end to end:

1. The action asks for a name (:mod:`avialsync.ui.custom_marker_dialogs`).
2. The calibration is resolved (:mod:`avialsync.core.calibration_ref`). When
   there is none the user imports one -- which writes ``calibration_ref.txt``
   naming it -- or has one fitted from the session's own tracking in a
   background job (:mod:`avialsync.engine.calibration_worker`).
3. Every pane takes a left click as the marker's position, in any order;
   clicking a pane again re-places it there. Playback is paused, as for Fix
   Tracker, and the marker belongs to the frame on screen.
4. Once every calibrated camera has a click the point is triangulated and the
   marker goes through the command bus (rule 14), so it can be undone.

Afterwards a marker is a regular point: Fix Tracker drags it (re-triangulating
on release), and with Fix Tracker off the pane's context menu deletes it.

**Where markers live.** Beside the data, never in it (D-099's rule, applied
here): a DLC-layout CSV per camera next to that camera's 2D pose file, and an
anipose-layout CSV next to the 3D pose file (see
:mod:`avialsync.core.custom_markers`). They are written on every change, from
the mutation funnel, and read back as pose sources are imported.

**Frames.** A marker is keyed by the video frame the panes show when it is
placed. On an AOL session every camera shows the same frame number for the same
instant, and that number is the anipose ``fnum``; a click in a pane that has
moved to another frame starts the placement over on that frame rather than
mixing two instants in one triangulation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QFileDialog
from scipy.spatial.transform import Rotation

from avialsync.core import calibration_ref, custom_markers
from avialsync.core.calibration import CameraModel, read_calibration, triangulate
from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.commands import SetCustomMarkerCommand
from avialsync.core.custom_markers import CustomMarker
from avialsync.core.errors import CalibrationError
from avialsync.ui.custom_marker_dialogs import (
    COMPUTE,
    IMPORT,
    ask_calibration_source,
    ask_marker_name,
)
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

#: The overlay layer drawing 3D points projected back into each camera.
REPROJECTION_OVERLAY = "tracking.reprojection"


@dataclass
class Placement:
    """A marker being placed: its name, its frame, and the clicks so far."""

    name: str
    frame: int
    #: Video path -> ``(x, y)`` in that video's pixels.
    clicks: dict[str, tuple[float, float]] = field(default_factory=dict)


@dataclass
class CalibrationState:
    """The calibration in force, and which camera each video path is."""

    path: Path
    cameras: dict[str, CameraModel]


# ── where things are ─────────────────────────────────────────────────


def camera_name(video: str) -> str:
    """The name a marker file and a fitted calibration give a video's camera."""
    return Path(video).stem


def _videos(window: MainWindow) -> list[str]:
    return list(window.video_grid.pane_paths())


def _pose3d_dir(window: MainWindow) -> Path | None:
    if window._pose_3d_sources:
        return calibration_ref.pose3d_dir_for(next(iter(window._pose_3d_sources)))
    videos = _videos(window)
    if videos:
        return calibration_ref.pose3d_dir_for(Path(videos[0]).parent)
    return None


def _pose_2d_file(window: MainWindow, video: str) -> Path | None:
    """The 2D pose file drawn over *video* -- the ensemble when there are several."""
    entries = window._overlay_sources.get(video, {})
    for source_id, entry in entries.items():
        if entry.get("is_ensemble"):
            return Path(source_id)
    return Path(next(iter(entries))) if entries else None


def _marker_file_2d(window: MainWindow, video: str) -> Path:
    pose = _pose_2d_file(window, video)
    return custom_markers.marker_file_for(pose if pose is not None else Path(video))


def _marker_file_3d(window: MainWindow) -> Path | None:
    if window._pose_3d_sources:
        return custom_markers.marker_file_for(next(iter(window._pose_3d_sources)))
    folder = _pose3d_dir(window)
    return None if folder is None else folder / f"pose{custom_markers.MARKER_SUFFIX}"


def frame_at(window: MainWindow, t_master: float) -> int | None:
    """The video frame the panes show at *t_master*, from the first calibrated one."""
    state = window._calibration_state
    videos = _videos(window)
    ordered = [v for v in videos if state is not None and v in state.cameras] or videos
    if not ordered:
        return None
    pane = window.video_grid.panes[videos.index(ordered[0])]
    return int(pane.frame_record_at(t_master)[0])


# ── calibration ──────────────────────────────────────────────────────


def _load_calibration(window: MainWindow, path: Path, sources: tuple[str, ...]) -> bool:
    """Adopt the calibration at *path*; report and return False if it is unusable."""
    try:
        calibration = read_calibration(path)
    except CalibrationError as error:
        window.notifications.show_error(tr("The calibration could not be used"), details=str(error))
        return False
    videos = _videos(window)
    names = calibration_ref.camera_names(calibration, videos, sources)
    cameras = {
        video: model
        for video, name in names.items()
        if (model := calibration.camera(name)) is not None
    }
    if len(cameras) < 2:
        window.notifications.show_error(
            tr("The calibration does not match these cameras"),
            details=tr("{file} names {names}; the videos are {videos}.").format(
                file=path.name,
                names=", ".join(calibration.names),
                videos=", ".join(Path(v).name for v in videos),
            ),
        )
        return False
    window._calibration_state = CalibrationState(path=path, cameras=cameras)
    missing = [Path(v).name for v in videos if v not in cameras]
    if missing:
        window.notifications.show_warning(
            tr("{videos} are not in the calibration; markers will skip them.").format(
                videos=", ".join(missing)
            )
        )
    return True


#: Video sets a quiet lookup has already been tried for, per window.
_QUIET_TRIED: dict[int, tuple[str, ...]] = {}


def _calibration_quietly(window: MainWindow) -> None:
    """Load the session's calibration without asking or reporting anything.

    For drawing only -- markers read back from disk, carried by the wheel --
    so a miss is silent: the user has not asked for anything yet. Tried once
    per set of open videos, since panes arrive one at a time.
    """
    if window._calibration_state is not None:
        return
    videos = tuple(_videos(window))
    if len(videos) < 2 or _QUIET_TRIED.get(id(window)) == videos:
        return
    _QUIET_TRIED[id(window)] = videos
    folder = _pose3d_dir(window)
    link = calibration_ref.locate(folder) if folder is not None else None
    if link is None or not link.calibration.is_file():
        return
    try:
        calibration = read_calibration(link.calibration)
    except CalibrationError:
        return
    names = calibration_ref.camera_names(calibration, list(videos), link.sources)
    cameras = {
        video: model
        for video, name in names.items()
        if (model := calibration.camera(name)) is not None
    }
    if len(cameras) >= 2:
        window._calibration_state = CalibrationState(path=link.calibration, cameras=cameras)


def _resolve_calibration(window: MainWindow) -> bool:
    """Use the calibration already found, or look for one; False if none."""
    if window._calibration_state is not None:
        return True
    folder = _pose3d_dir(window)
    if folder is None:
        return False
    link = calibration_ref.locate(folder)
    if link is None:
        return False
    if not link.calibration.is_file():
        window.notifications.show_warning(
            tr("{ref} names {path}, which does not exist.").format(
                ref=link.ref_file.name if link.ref_file else calibration_ref.REF_NAME,
                path=link.calibration,
            )
        )
        return False
    return _load_calibration(window, link.calibration, link.sources)


def _import_calibration(window: MainWindow, folder: Path) -> bool:
    chosen, _ = QFileDialog.getOpenFileName(
        window, tr("Choose calibration.toml"), str(folder), tr("Calibration (*.toml)")
    )
    if not chosen:
        return False
    sources = tuple(Path(v).name for v in _videos(window))
    if not _load_calibration(window, Path(chosen), sources):
        return False
    try:
        written = calibration_ref.write_ref(folder, sources, chosen)
    except OSError as error:
        window.notifications.show_warning(
            tr("The calibration is in use, but {file} could not be written.").format(
                file=calibration_ref.REF_NAME
            ),
            details=str(error),
        )
        return True
    window.notifications.show_success(
        tr("Calibration linked in {file}. Copy it to other experiments from this rig.").format(
            file=written
        )
    )
    return True


def _compute_calibration(
    window: MainWindow,
    folder: Path,
    on_ready: Callable[[], None],
    on_cancel: Callable[[], None],
) -> None:
    """Fit a calibration in the background, then call *on_ready* (or *on_cancel*)."""
    from avialsync.engine.calibration_worker import CalibrationFitWorker, CameraFitInput

    if not window._pose_3d_sources:
        window.notifications.show_error(
            tr("A calibration cannot be computed"),
            details=tr("Fitting one needs the session's 3D pose file, and none is loaded."),
        )
        on_cancel()
        return
    inputs = []
    for video, pane in zip(_videos(window), window.video_grid.panes, strict=False):
        pose = _pose_2d_file(window, video)
        size = getattr(pane, "video_size", None)
        if pose is None or not size:
            continue
        inputs.append(CameraFitInput(camera_name(video), (int(size[0]), int(size[1])), pose))
    if len(inputs) < 2:
        window.notifications.show_error(
            tr("A calibration cannot be computed"),
            details=tr("Fitting one needs 2D tracking in at least two cameras."),
        )
        on_cancel()
        return
    worker = CalibrationFitWorker(
        Path(next(iter(window._pose_3d_sources))),
        inputs,
        folder,
        [Path(v).name for v in _videos(window)],
    )

    def on_finished(path: str, summary: str) -> None:
        window.notifications.show_success(
            tr("Calibration fitted and saved as {file} ({summary}).").format(
                file=path, summary=summary
            )
        )
        if _load_calibration(window, Path(path), ()):
            on_ready()
        else:
            on_cancel()

    def on_error(message: str) -> None:
        window.notifications.show_error(tr("The calibration could not be fitted"), details=message)
        on_cancel()

    def _wire(thread: QThread) -> None:
        worker.finished.connect(on_ui_thread(on_finished, window))
        worker.error.connect(on_ui_thread(on_error, window))
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)

    window._run_job(worker, label=tr("Fitting camera calibration"), configure=_wire)


def acquire_calibration(
    window: MainWindow, on_ready: Callable[[], None], on_cancel: Callable[[], None]
) -> None:
    """Make a calibration available, asking the user when there is none.

    *on_ready* runs once one is loaded -- immediately, after an import, or when
    a background fit finishes; *on_cancel* when the user declines or it fails.
    Shared by Add 3D Marker and the 3D reprojection overlay, so both ask the
    same question the same way.
    """
    if _resolve_calibration(window):
        on_ready()
        return
    folder = _pose3d_dir(window)
    if folder is None:
        on_cancel()
        return
    choice = ask_calibration_source(window, str(folder))
    if choice == IMPORT and _import_calibration(window, folder):
        on_ready()
    elif choice == COMPUTE:
        _compute_calibration(window, folder, on_ready, on_cancel)
    else:
        on_cancel()


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
    acquire_calibration(
        window,
        lambda: _begin_placement(window, name),
        lambda: _set_action_checked(window, False),
    )


def _begin_placement(window: MainWindow, name: str) -> None:
    frame = frame_at(window, window.clock.state.t)
    if frame is None:
        _set_action_checked(window, False)
        return
    if window._act_fix_tracker.isChecked():
        window._act_fix_tracker.setChecked(False)
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
    frame = frame_at(window, window.clock.state.t)
    if frame is not None and frame != placement.frame:
        placement.frame = frame
        placement.clicks.clear()
    placement.clicks[video] = (float(x), float(y))
    if len(placement.clicks) < len(state.cameras):
        _report_progress(window)
        return
    marker = CustomMarker(name=placement.name, frame=placement.frame)
    for clicked, (cx, cy) in placement.clicks.items():
        marker = marker.with_view(camera_name(clicked), cx, cy)
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
    by_camera = {camera_name(video): model for video, model in state.cameras.items()}
    views = [(by_camera[camera], (x, y)) for camera, x, y in marker.views if camera in by_camera]
    try:
        xyz, error = triangulate(views)
    except CalibrationError as error_:
        window.notifications.show_warning(str(error_))
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
    moved = before.with_view(camera_name(video), x, y)
    if not _resolve_calibration(window):
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
    for video in set(_videos(window)) | set(window._overlay_sources):
        camera = camera_name(video)
        by_frame: dict[int, list[tuple[str, float, float]]] = {}
        for marker in window.custom_markers:
            view = marker.view(camera)
            if view is not None:
                by_frame.setdefault(marker.frame, []).append((marker.name, view[0], view[1]))
        window.video_grid.set_custom_markers(video, by_frame)
    window.tracking_3d_pane.canvas.set_cursor(window.clock.state.t)
    window._update_tracking_pane_visibility()


# ── riding the wheel ─────────────────────────────────────────────────
#
# For now every custom marker is taken to be fixed to the wheel: on any frame
# other than the one it was placed on, it is drawn rotated about the wheel's
# axle by how far the encoder angle has turned since. The axle is read off the
# markers themselves -- centre = their mean, direction = their least spread,
# which for bars spread round a wheel is the axle -- and the encoder's positive
# sense and 1:1 ratio were checked against the video (D-112). Rotated copies are
# display-only; a marker is edited on its own frame.

_ANGLE_CHANNEL = "encoder_angle"
#: A rotated bar end facing further than this past the wheel's outline, as seen
#: from a camera, is behind the side plate or under a nearer bar: not drawn.
_FACING_LIMIT = -0.2


def _angle_reader(window: MainWindow) -> MappedChannelReader | None:
    for reader in window._plotted_readers:
        if isinstance(reader, MappedChannelReader) and reader.channel_id == _ANGLE_CHANNEL:
            return reader
    return None


def _angle_at(reader: MappedChannelReader, t_master: float) -> float | None:
    value = float(reader.value_at(t_master))
    return value if np.isfinite(value) else None


def _frame_master_time(window: MainWindow, frame: int) -> float | None:
    """Master time of *frame* on the reference camera (the one :func:`frame_at` uses)."""
    videos = _videos(window)
    state = window._calibration_state
    ordered = [v for v in videos if state is not None and v in state.cameras] or videos
    if not ordered:
        return None
    times = window._video_frame_times.get(ordered[0])
    if times is None or not 0 <= frame < len(times):
        return None
    pane = window.video_grid.panes[videos.index(ordered[0])]
    return float(pane.time_map.to_master(float(times[frame])))


def _wheel_axis(points: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    if len(points) < 3:
        return None
    centre = points.mean(axis=0)
    _, vectors = np.linalg.eigh(np.cov((points - centre).T))
    return centre, vectors[:, 0]


def _riding(window: MainWindow, t_master: float) -> list[tuple[CustomMarker, np.ndarray, bool]]:
    """Every marker's position at *t_master*: ``(marker, xyz, on_its_own_frame)``."""
    solved = [m for m in window.custom_markers if m.xyz is not None]
    if not solved:
        return []
    frame = frame_at(window, t_master)
    reader = _angle_reader(window)
    now = _angle_at(reader, t_master) if reader is not None else None
    axis = _wheel_axis(np.asarray([m.xyz for m in solved], dtype=np.float64))
    out: list[tuple[CustomMarker, np.ndarray, bool]] = []
    reference_angles: dict[int, float | None] = {}
    for marker in solved:
        xyz = np.asarray(marker.xyz, dtype=np.float64)
        if marker.frame == frame:
            out.append((marker, xyz, True))
            continue
        if now is None or axis is None or reader is None:
            continue
        if marker.frame not in reference_angles:
            t_ref = _frame_master_time(window, marker.frame)
            reference_angles[marker.frame] = None if t_ref is None else _angle_at(reader, t_ref)
        then = reference_angles[marker.frame]
        if then is None:
            continue
        centre, direction = axis
        rotation = Rotation.from_rotvec(
            direction * np.radians(now - then) * _wheel_sense(solved, direction)
        )
        out.append((marker, rotation.apply(xyz - centre) + centre, False))
    return out


def _wheel_sense(solved: list[CustomMarker], direction: np.ndarray) -> float:
    """+1 when the axle points from the L ends to the R ends, as on the reference rig.

    The eigenvector's sign is arbitrary; the encoder's positive sense was
    measured with the axle pointing L -> R, so it is re-oriented to match.
    """
    lefts = [m.xyz for m in solved if m.name.endswith("L")]
    rights = [m.xyz for m in solved if m.name.endswith("R")]
    if not lefts or not rights:
        return 1.0
    across = np.mean(np.asarray(rights), axis=0) - np.mean(np.asarray(lefts), axis=0)
    return 1.0 if float(across @ direction) >= 0 else -1.0


def points_at(window: MainWindow, t_master: float) -> list[tuple[str, np.ndarray]]:
    """The 3D view's source of hand-placed markers at *t_master*, riding the wheel."""
    if not len(window.custom_markers):
        return []
    return [(marker.name, xyz) for marker, xyz, _ in _riding(window, t_master)]


def riding_in(window: MainWindow, video: str, t_master: float) -> list[tuple[str, float, float]]:
    """Markers carried off their own frame by the wheel, projected into *video*."""
    if not len(window.custom_markers):
        return []
    _calibration_quietly(window)
    state = window._calibration_state
    model = state.cameras.get(video) if state is not None else None
    if model is None or not len(window.custom_markers):
        return []
    moved = [(m, xyz) for m, xyz, own in _riding(window, t_master) if not own]
    if not moved:
        return []
    axis = _wheel_axis(np.asarray([xyz for _, xyz in moved]))
    camera_centre = -model.rotation_matrix().T @ model.translation
    videos = _videos(window)
    size = window.video_grid.panes[videos.index(video)].video_size if video in videos else None
    out: list[tuple[str, float, float]] = []
    for marker, xyz in moved:
        if axis is not None:
            centre, direction = axis
            radial = xyz - centre
            radial -= (radial @ direction) * direction
            to_camera = camera_centre - xyz
            norm = np.linalg.norm(radial) * np.linalg.norm(to_camera)
            if norm > 0 and float(radial @ to_camera) / norm < _FACING_LIMIT:
                continue
        if float(xyz @ model.rotation_matrix()[2] + model.translation[2]) <= 0:
            continue
        x, y = model.project(xyz)[0]
        if size and not (0 <= x < size[0] and 0 <= y < size[1]):
            continue
        out.append((marker.name, float(x), float(y)))
    return out


def reprojected(window: MainWindow, video: str, t_master: float) -> list[tuple[str, float, float]]:
    """Every 3D point at *t_master*, projected into *video*'s pixels.

    The anipose pose as the 3D view is showing it, plus the hand-placed markers
    on the frame, through this camera's calibration: drawn beside the 2D
    tracking, the gap between the two is the reconstruction's error on that
    body part. Empty until a calibration covers this camera.
    """
    state = window._calibration_state
    model = state.cameras.get(video) if state is not None else None
    if model is None:
        return []
    canvas = window.tracking_3d_pane.canvas
    names = list(canvas.point_names)
    positions = canvas.positions
    for name, xyz in points_at(window, t_master):
        names.append(name)
        positions = np.vstack((positions.reshape(-1, 3), xyz.reshape(1, 3)))
    if not names:
        return []
    finite = np.all(np.isfinite(positions), axis=1)
    # A point behind the camera projects to a mirror image in front of it.
    depth = positions @ model.rotation_matrix()[2] + model.translation[2]
    keep = finite & (depth > 0)
    if not np.any(keep):
        return []
    pixels = model.project(positions[keep])
    kept = [name for name, k in zip(names, keep, strict=True) if k]
    return [(name, float(x), float(y)) for name, (x, y) in zip(kept, pixels, strict=True)]


def reprojection_toggled(window: MainWindow, visible: bool) -> None:
    """Switching the reprojection overlay on needs a calibration: find or ask."""
    if not visible:
        return

    def _declined() -> None:
        window._on_overlay_toggled(REPROJECTION_OVERLAY, False)

    acquire_calibration(window, window.video_grid.refresh_point_edits, _declined)


def persist(window: MainWindow) -> None:
    """Write every camera's marker file and the 3D one, now.

    Called only from the mutation funnel, so reading the files back in never
    echoes them straight out again (the D-099 rule for corrections).
    """
    markers = list(window.custom_markers)
    written: list[Path] = []
    try:
        for video in _videos(window):
            written.append(
                custom_markers.write_2d(_marker_file_2d(window, video), camera_name(video), markers)
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
    for video in set(_videos(window)) | set(window._overlay_sources):
        camera = camera_name(video)
        for key, (x, y) in custom_markers.read_2d(_marker_file_2d(window, video)).items():
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
    # asking, so the wheel can carry them onto every camera from the first
    # frame shown rather than only after Add 3D Marker is pressed.
    _calibration_quietly(window)
    window.custom_markers.load(markers)
