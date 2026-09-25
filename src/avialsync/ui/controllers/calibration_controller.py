"""The rig's calibration: finding it, importing it, fitting it, and projecting through it.

Split from :mod:`avialsync.ui.controllers.custom_marker_controller` (D-112): Add
3D Marker, Add Wheel (D-113) and the 3D reprojection overlay all need the same
calibration, found and asked for the same way.

**Resolution** is :func:`avialsync.core.calibration_ref.locate`:
``calibration_ref.txt``, then ``calibration.toml`` in ``pose-3d/``, then in the
session folder. When nothing is found, :func:`acquire_calibration` asks Import
or Compute -- **only when the user asked for something that needs it** (Add 3D
Marker, Add Wheel, or "Choose Calibration…"). A View-menu checkbox, Show All,
and undo are not such requests, so switching reprojection on without a
calibration posts a notification offering the question instead (rule 11).

**Failures go through the presenter** (rule 12): a :class:`CalibrationError`
reaches the user as :meth:`MainWindow.report_failure`, with the exception's text
behind Show details, never as the message itself.

**Nothing of the user's is overwritten.** Importing or fitting writes a new
``calibration_ref.txt``; an existing one is first kept aside under a dated name,
and a fitted ``.toml`` never takes the name of a file already there.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QFileDialog

from avialsync.core import calibration_ref
from avialsync.core.calibration import CameraModel, read_calibration
from avialsync.core.errors import CalibrationError
from avialsync.ui.controllers import rig_paths
from avialsync.ui.custom_marker_dialogs import COMPUTE, IMPORT, ask_calibration_source
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.engine.calibration_worker import CameraFitInput
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

__all__ = [
    "REPROJECTION_OVERLAY",
    "CalibrationState",
    "calibration_quietly",
    "resolve_calibration",
    "acquire_calibration",
    "reprojected",
    "reprojection_toggled",
]

#: The overlay layer drawing 3D points projected back into each camera.
REPROJECTION_OVERLAY = "tracking.reprojection"


@dataclass
class CalibrationState:
    """The calibration in force, and which camera each video path is."""

    path: Path
    cameras: dict[str, CameraModel]


def _load_calibration(window: MainWindow, path: Path, sources: tuple[str, ...]) -> bool:
    """Adopt the calibration at *path*; report and return False if it is unusable."""
    try:
        calibration = read_calibration(path)
    except CalibrationError as error:
        window.report_failure(error, doing=tr("The calibration could not be used"))
        return False
    videos = rig_paths.open_videos(window)
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
            tr("{videos} are not in the calibration; markers and wheels skip them.").format(
                videos=", ".join(missing)
            )
        )
    return True


#: Video sets a quiet lookup has already been tried for, per window.
_QUIET_TRIED: dict[int, tuple[str, ...]] = {}


def calibration_quietly(window: MainWindow) -> None:
    """Load the session's calibration without asking or reporting anything.

    For drawing only -- markers and wheels read back from disk -- so a miss is
    silent: the user has not asked for anything yet. Tried once per set of open
    videos, since panes arrive one at a time. Never called while painting.

    A calibration taken while only some cameras were open is extended as the
    rest open: a session reopened used to calibrate the first two panes and
    then never the third, so a wheel read back was drawn on two cameras only.
    """
    state = window._calibration_state
    videos = tuple(rig_paths.open_videos(window))
    if state is not None and set(videos) <= set(state.cameras):
        return
    if len(videos) < 2 or _QUIET_TRIED.get(id(window)) == videos:
        return
    _QUIET_TRIED[id(window)] = videos
    folder = rig_paths.pose3d_dir(window)
    link = calibration_ref.locate(folder) if folder is not None else None
    path = state.path if state is not None else link.calibration if link is not None else None
    if path is None or not path.is_file():
        return
    try:
        calibration = read_calibration(path)
    except CalibrationError:
        return
    sources = link.sources if link is not None else ()
    names = calibration_ref.camera_names(calibration, list(videos), sources)
    cameras = {
        video: model
        for video, name in names.items()
        if (model := calibration.camera(name)) is not None
    }
    if len(cameras) >= 2 and (state is None or len(cameras) > len(state.cameras)):
        window._calibration_state = CalibrationState(path=path, cameras=cameras)


def resolve_calibration(window: MainWindow) -> bool:
    """Use the calibration already found, or look for one; False if none."""
    if window._calibration_state is not None:
        return True
    folder = rig_paths.pose3d_dir(window)
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
    sources = tuple(Path(v).name for v in rig_paths.open_videos(window))
    if not _load_calibration(window, Path(chosen), sources):
        return False
    try:
        kept = calibration_ref.keep_aside(folder)
        written = calibration_ref.write_ref(folder, sources, chosen)
    except OSError as error:
        window.notifications.show_warning(
            tr("The calibration is in use, but {file} could not be written.").format(
                file=calibration_ref.REF_NAME
            ),
            details=str(error),
        )
        return True
    message = tr("Calibration linked in {file}. Copy it to other experiments from this rig.")
    if kept is not None:
        message += " " + tr("The previous one is kept as {old}.").format(old=kept.name)
    window.notifications.show_success(message.format(file=written))
    return True


def _fit_inputs(window: MainWindow) -> list[CameraFitInput]:
    """Each camera with 2D tracking and a known frame size; raises when a fit cannot run."""
    from avialsync.engine.calibration_worker import CameraFitInput

    if not window._pose_3d_sources:
        raise CalibrationError("Fitting a calibration needs the session's 3D pose; none is loaded.")
    inputs = []
    for video, pane in zip(rig_paths.open_videos(window), window.video_grid.panes, strict=False):
        pose = rig_paths.pose_2d_file(window, video)
        size = getattr(pane, "video_size", None)
        if pose is None or not size:
            continue
        inputs.append(
            CameraFitInput(rig_paths.camera_name(video), (int(size[0]), int(size[1])), pose)
        )
    if len(inputs) < 2:
        raise CalibrationError("Fitting a calibration needs 2D tracking in at least two cameras.")
    return inputs


def _compute_calibration(
    window: MainWindow,
    folder: Path,
    on_ready: Callable[[], None],
    on_cancel: Callable[[], None],
) -> None:
    """Fit a calibration in the background, then call *on_ready* (or *on_cancel*)."""
    from avialsync.engine.calibration_worker import CalibrationFitWorker

    try:
        inputs = _fit_inputs(window)
    except CalibrationError as error:
        window.report_failure(error, doing=tr("A calibration cannot be computed"))
        on_cancel()
        return
    videos = rig_paths.open_videos(window)
    worker = CalibrationFitWorker(
        Path(next(iter(window._pose_3d_sources))), inputs, folder, [Path(v).name for v in videos]
    )

    def on_finished(path: str, summary: str, kept: str) -> None:
        message = tr("Calibration fitted and saved as {file} ({summary}).").format(
            file=path, summary=summary
        )
        if kept:
            message += " " + tr("The previous calibration_ref.txt is kept as {old}.").format(
                old=Path(kept).name
            )
        window.notifications.show_success(message)
        if _load_calibration(window, Path(path), ()):
            on_ready()
        else:
            on_cancel()

    def on_error(message: str) -> None:
        window.report_failure(
            CalibrationError(message), doing=tr("The calibration could not be fitted")
        )
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

    Call only for a gesture that asked for something needing a calibration:
    the question is a modal, allowed because it was asked for (rule 11).
    *on_ready* runs once one is loaded -- immediately, after an import, or when
    a background fit finishes; *on_cancel* when the user declines or it fails.
    """
    if resolve_calibration(window):
        on_ready()
        return
    folder = rig_paths.pose3d_dir(window)
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


# ── reprojection ─────────────────────────────────────────────────────


def reprojected(window: MainWindow, video: str, t_master: float) -> list[tuple[str, float, float]]:
    """Every 3D point the 3D view shows, projected into *video*'s pixels.

    The anipose pose plus the hand-placed markers, exactly as the 3D view is
    showing them, through this camera's calibration: drawn beside the 2D
    tracking, the gap between the two is the reconstruction's error on that
    body part. Empty until a calibration covers this camera.
    """
    del t_master  # the 3D view has already sampled this instant
    state = window._calibration_state
    model = state.cameras.get(video) if state is not None else None
    if model is None:
        return []
    canvas = window.tracking_3d_pane.canvas
    custom = canvas.custom_points
    names = [*canvas.point_names, *(name for name, _ in custom)]
    if not names:
        return []
    positions = np.vstack(
        [canvas.positions.reshape(-1, 3), *(xyz.reshape(1, 3) for _, xyz in custom)]
    )
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
    """Switching reprojection on: draw with the calibration in force, or offer to find one.

    Never a modal from here. This runs for the View-menu checkbox, for Show
    All, and for a pane's context menu -- a switch, not a request for a dialog
    -- so the overlay stays on (it draws nothing without a calibration) and a
    notification offers the question. The switch is recorded once, whatever
    the user then does, so undo matches what they did (rule 14).
    """
    if not visible:
        return
    if resolve_calibration(window):
        window.video_grid.refresh_point_edits()
        return
    window.notifications.show_warning(
        tr("3D reprojection draws nothing until the cameras' calibration is found."),
        action_label=tr("Choose Calibration…"),
        on_action=lambda: acquire_calibration(
            window, window.video_grid.refresh_point_edits, lambda: None
        ),
    )
