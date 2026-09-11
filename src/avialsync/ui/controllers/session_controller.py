"""Session persistence, window geometry, autosave, and the recent-files menu.

Everything that reads or writes state which must outlive the process: the
``.avv`` session document, the ``QSettings`` window/splitter geometry, the
two-minute autosave, and the recent-files list they both feed.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
from PySide6.QtCore import QSettings, QThread
from PySide6.QtWidgets import QFileDialog

from avialsync.core.errors import CacheError, FileUnreadableError, SourceOpenError
from avialsync.core.inspection import SourceInspection
from avialsync.core.session import (
    MarkerEntry,
    SensorEntry,
    SessionState,
    VideoEntry,
)
from avialsync.ui import recovery
from avialsync.ui.controllers import corrections_controller
from avialsync.ui.i18n import tr
from avialsync.ui.recent_files import add_recent, get_recent

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def _disconnect(signal: object, slot: object) -> None:
    """Detach a result handler when a reset makes its work obsolete."""
    disconnect = getattr(signal, "disconnect", None)
    if not callable(disconnect):
        return
    try:
        disconnect(slot)
    except (RuntimeError, TypeError):
        pass


def restore_geometry(window: MainWindow) -> None:
    settings = QSettings("AvialSync", "AvialSync")
    geom = settings.value("window/geometry")
    if geom:
        window.restoreGeometry(geom)
    h_state = settings.value("splitter/horizontal")
    if h_state:
        window._h_splitter.restoreState(h_state)
    v_state = settings.value("splitter/vertical")
    if v_state:
        window._v_splitter.restoreState(v_state)
    media_state = settings.value("splitter/media")
    if media_state:
        window._media_splitter.restoreState(media_state)
    content_state = settings.value("splitter/content")
    if content_state:
        window._content_splitter.restoreState(content_state)
    tab_index = cast(int, settings.value("inspector/tab", 0, type=int))
    window._left_tabs.setCurrentIndex(max(0, min(tab_index, window._left_tabs.count() - 1)))
    # restoreState also restores the collapsible flag and may carry a zero
    # pane from an older layout; re-assert the policy and repair.
    window._enforce_splitter_policy()
    window._repair_collapsed_panes()
    # The restored arrangement is the user's own, so it becomes the ratio to
    # hold. Recording it here rather than letting the first resize adopt it
    # keeps a session that opens already-resized from drifting.
    window._pane_proportions.record_all()


def save_geometry(window: MainWindow) -> None:
    settings = QSettings("AvialSync", "AvialSync")
    settings.setValue("window/geometry", window.saveGeometry())
    settings.setValue(
        "splitter/horizontal",
        window._h_splitter.saveState(),
    )
    settings.setValue(
        "splitter/vertical",
        window._v_splitter.saveState(),
    )
    settings.setValue("splitter/content", window._content_splitter.saveState())
    settings.setValue("splitter/media", window._media_splitter.saveState())
    settings.setValue("inspector/tab", window._left_tabs.currentIndex())


def build_session_state(window: MainWindow) -> SessionState:
    """Snapshot current app state into a SessionState."""
    from avialsync.ui.sidebar import SensorInfoWidget

    bounds = window.clock.state.bounds
    videos = []
    for p, pane in zip(window.video_grid._paths, window.video_grid.panes, strict=False):
        ins = window._inspections.get(p)
        videos.append(
            VideoEntry(
                path=p,
                offset=pane.time_map.offset,
                drift_ppm=pane.time_map.drift_ppm,
                integrity_flags=ins.integrity_flags.as_dict() if ins else {},
                metadata=ins.import_config if ins else {},
            )
        )

    sensors: list[SensorEntry] = []
    for i in range(window.sidebar.sensors_layout.count()):
        item = window.sidebar.sensors_layout.itemAt(i)
        if item and item.widget():
            w = item.widget()
            if isinstance(w, SensorInfoWidget):
                ins = window._inspections.get(w.path)
                offset, drift_ppm = w.mapping()
                sensors.append(
                    SensorEntry(
                        path=w.path,
                        channels=[],
                        loader_id=ins.loader_id if ins else "",
                        import_config=dict(ins.import_config) if ins else {},
                        import_report=(
                            ins.import_report.as_dict() if ins and ins.import_report else None
                        ),
                        offset=offset,
                        drift_ppm=drift_ppm,
                    )
                )

    markers = [
        MarkerEntry(
            t_start=m.t_start,
            t_end=m.t_end,
            label=m.label,
            video_frames=[dataclasses.asdict(vf) for vf in m.video_frames],
        )
        for m in window.annotation_store.markers
    ]

    # The fixed sweep always displays 0..window_duration.
    plot_x0 = 0.0 if window.plot_pane.channels else None
    plot_x1 = window.plot_pane.window_duration if window.plot_pane.channels else None

    return SessionState(
        videos=videos,
        sensors=sensors,
        markers=markers,
        sync_provenance=list(window._sync_provenance),
        session_start_time=window.session_start_time,
        t_start=bounds[0],
        t_end=bounds[1],
        plot_x0=plot_x0,
        plot_x1=plot_x1,
        overlays=window.overlay_state.to_dict(),
        point_edits=corrections_controller.build_manifest(window),
    )


def save_session(window: MainWindow) -> None:
    path, _ = QFileDialog.getSaveFileName(
        window,
        "Save Session",
        "",
        "AvialSync Session (*.avv)",
    )
    if not path:
        return
    if not path.endswith(".avv"):
        path += ".avv"

    window._start_session_save(Path(path), is_autosave=False)


def start_session_save(window: MainWindow, path: Path, is_autosave: bool = False) -> None:
    if window._save_in_progress:
        return

    window._save_in_progress = True
    state = window._build_session_state()
    session_generation = window._session_generation

    from avialsync.engine.session_worker import SessionSaveWorker

    worker = SessionSaveWorker(state, path)

    if not is_autosave:
        window.transport.set_status("Saving session…")

    def on_finished():
        if session_generation != window._session_generation:
            return
        window._session_path = path
        add_recent(str(path))
        # The work is now in a file the user chose, so the recovery snapshot
        # describes nothing they could still lose. Leaving it would offer a
        # pointless restore on the next launch and train them to dismiss the
        # bar without reading it.
        recovery.clear_recovery()
        window._mark_session_saved()
        if not is_autosave:
            window.transport.set_status("")

    def on_error(msg: str):
        if not is_autosave:
            window.transport.set_status("")
            window.report_failure(CacheError(msg), doing="The session could not be saved")
        else:
            logger.exception("Autosave failed for %s: %s", path, msg)

    # Wired before the thread starts. `_run_job` returns an already-running
    # thread, so connecting afterwards races a fast save: losing `finished`
    # skips the recent-files entry, and losing `thread.finished` leaves
    # `_save_in_progress` latched, which blocks every later save for the rest
    # of the session.
    def _wire(thread: QThread) -> None:
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)

        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        # No `worker.deleteLater` here: these signals are emitted in the
        # worker thread, where the worker also lives, so the connection is
        # direct and ~QObject runs inside that thread — severing connections
        # while holding one of Qt's pooled signal/slot mutexes and then
        # taking the GIL for PySide's disconnectNotify, which deadlocks a UI
        # thread holding the GIL and waiting on a colliding mutex (D-062).
        # The owning registry drops its reference on the UI thread instead.
        # Un-latch even if the thread ends abnormally (e.g. worker deleted
        # without emitting finished/error), so a stuck save cannot
        # permanently block every later save.
        thread.finished.connect(lambda: setattr(window, "_save_in_progress", False))

    window._run_job(worker, configure=_wire)


def open_session(window: MainWindow) -> None:
    path, _ = QFileDialog.getOpenFileName(
        window,
        "Open Session",
        "",
        "AvialSync Session (*.avv)",
    )
    if not path:
        return

    window._start_session_load(Path(path))


def start_session_load(window: MainWindow, path: Path) -> None:
    from avialsync.engine.session_worker import SessionLoadWorker

    window.transport.set_status("Loading session…")
    worker = SessionLoadWorker(path)
    session_generation = window._session_generation

    def on_finished(state: SessionState):
        if session_generation != window._session_generation:
            return
        window.transport.set_status("")
        window._session_path = path
        add_recent(str(path))
        window._restore_session(state)

    def on_error(msg: str):
        window.transport.set_status("")
        window.report_failure(FileUnreadableError(msg), doing="That session could not be opened")

    # Wired before the thread starts: `_run_job` returns an already-running
    # thread, and a session that loads quickly can emit `finished` before a
    # connection made afterwards exists — the window would keep "Loading
    # session…" forever and never restore anything.
    def _wire(thread: QThread) -> None:
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)

        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        # No `worker.deleteLater` here: these signals are emitted in the
        # worker thread, where the worker also lives, so the connection is
        # direct and ~QObject runs inside that thread — severing connections
        # while holding one of Qt's pooled signal/slot mutexes and then
        # taking the GIL for PySide's disconnectNotify, which deadlocks a UI
        # thread holding the GIL and waiting on a colliding mutex (D-062).
        # The owning registry drops its reference on the UI thread instead.

    window._run_job(worker, configure=_wire)


def reset_session(window: MainWindow) -> None:
    """Return the workspace to its empty, ready-to-open state."""
    window._session_generation += 1
    window._session_path = None
    # A reset empties the workspace and drops the path. Any snapshot still on
    # disk describes work this reset has just discarded on purpose; keeping it
    # would resurrect it at the next launch, and letting the close-time write
    # replace it with an empty workspace would destroy genuinely unsaved work
    # from before the reset. Clear it, do not overwrite it (D-089).
    recovery.clear_recovery()

    for worker in list(window._video_load_jobs.values()):
        _disconnect(getattr(worker, "opened", None), window._on_video_opened)
        _disconnect(getattr(worker, "error", None), window._on_video_open_error)
        cancel = getattr(worker, "cancel", None)
        if callable(cancel):
            cancel()
    window._pending_video_loads.clear()
    window._video_request_order.clear()
    window._probed_videos.clear()
    window._video_load_offsets.clear()
    window._video_load_drifts.clear()
    window._video_pane_initializing = None

    import_worker = window._import_worker
    if import_worker is not None:
        # The progress dialog this used to disconnect from is gone (D-091);
        # the activity bar takes its place and is dismissed below. Cancelling
        # the worker on reset is the behaviour that mattered and is unchanged.
        _disconnect(getattr(import_worker, "progress", None), window.activity_bar.set_progress)
        _disconnect(getattr(import_worker, "finished", None), window._on_import_finished)
        _disconnect(getattr(import_worker, "error", None), window._on_import_error)
        cancel = getattr(import_worker, "cancel", None)
        if callable(cancel):
            cancel()
    window.activity_bar.end()
    window._active_cancel = None
    window._pending_imports.clear()

    for job in window._job_manager.jobs():
        worker = job.worker
        _disconnect(getattr(worker, "finished", None), window._on_drop_scan_finished)
        _disconnect(getattr(worker, "session_found", None), window._on_drop_session_found)
        _disconnect(getattr(worker, "error", None), window._on_drop_scan_error)
    window._job_manager.cancel_all()

    source_paths = set(window.video_grid.pane_paths())
    source_paths.update(window._sensor_cache_dirs)
    source_paths.update(window._overlay_sources)
    source_paths.update(window._pose_3d_sources)
    for path in source_paths:
        window.transport.set_source_coverage(path, 0.0, 0.0, "data")

    # `reset`, never `stop`: stop is teardown and halts the 60 Hz tick that is
    # the only caller of MasterClock.advance. Nothing restarts it, so a reset
    # that used it left the playhead dead for the rest of the process.
    window.player.reset()
    for path in list(window.video_grid.pane_paths()):
        window.video_grid.remove_pane(path)
    window.sidebar.clear_sources()
    window.plot_pane.clear_sources()
    window.plot_pane.clear_measure()
    window.annotation_store.clear()
    window.message_store.clear()

    window._video_fps.clear()
    window._video_frame_times.clear()
    window._video_source_bounds.clear()
    window._video_time_mappings.clear()
    window._sync_provenance.clear()
    window._session_start_time = 0.0
    window._pending_exact_mappings.clear()
    window._overview_gaps.clear()
    window._frame_indexed_sources.clear()
    window._overlay_sources.clear()
    window._pose_3d_sources.clear()
    window.point_edits.clear()
    window._point_edit_storage.clear()
    window._expected_correction_counts.clear()
    window._announced_correction_files.clear()
    window._plotted_readers.clear()
    window._inspections.clear()
    window._channel_units.clear()
    window._sensor_cache_dirs.clear()
    window._pending_bounds_sources.clear()
    window._pending_sensor_mappings.clear()
    window._session_camera_fps = 0.0
    window._session_anchor_epoch = 0.0
    window._session_item_labels.clear()
    window._session_item_kinds.clear()
    window._session_coverage_groups.clear()

    window._refresh_pose_3d()
    window.clock.set_bounds(0.0, 0.0)
    window.plot_pane.set_timeline_bounds(0.0, 0.0)
    window.transport.set_bounds(0.0, 0.0)
    window.transport.set_time(0.0)
    window.transport.set_ttl_events([])
    window.transport.set_gap_events([])
    window.transport.set_message_events([])
    window.transport.set_annotation_markers([])
    window.transport.set_status("Ready")


def on_session_load_error(window: MainWindow, error: str) -> None:
    window.statusBar().clearMessage()
    logger.error("Session load failed: %s", error)
    window.report_failure(FileUnreadableError(error), doing="That session could not be opened")


def restore_session(window: MainWindow, state: SessionState) -> None:
    """Load all sources from a SessionState object."""
    # Sources arrive asynchronously and are indistinguishable from the user
    # opening them; `_note_source_loaded` clears this once they drain.
    window._session_restoring = True
    # Restored before the panes exist, so each one is built already showing the
    # right layers rather than flashing the defaults first (D-090).
    window.overlay_state.load(state.overlays)
    window._apply_overlay_state()
    # Corrections live beside their pose files, so this only takes up what the
    # session claims: the counts to check each source against as it imports, and
    # the coordinates for any source that had to fall back to session storage
    # because its folder could not be written (D-099).
    window.point_edits.clear()
    corrections_controller.restore_manifest(window, state.point_edits)
    # Collect missing files for relink
    missing: list[str] = []
    kind_labels: dict[str, str] = {}

    for ve in state.videos:
        if not Path(ve.path).exists():
            missing.append(ve.path)
            kind_labels[ve.path] = "video"

    for se in state.sensors:
        if not Path(se.path).exists():
            missing.append(se.path)
            kind_labels[se.path] = "sensor"

    relink_map: dict[str, str] = {}
    if missing:
        from avialsync.ui.relink_dialog import RelinkDialog

        dlg = RelinkDialog(missing, kind_labels, window)
        if dlg.exec() == RelinkDialog.DialogCode.Rejected:
            return
        relink_map = dlg.resolved_mapping()

    for old_path, new_path in relink_map.items():
        # Corrections are keyed by the pose file's path; without this a session
        # whose CSV moved would open with every correction silently inactive,
        # and its expected count would be checked against a file that is gone.
        corrections_controller.remap(window, str(old_path), str(new_path))

    # Before any source loads: the reference is declared once, and a restored
    # session already declared it. Adopting it here stops the first file to
    # arrive from re-declaring a different one and renumbering the session.
    window._session_start_time = float(state.session_start_time)
    window._publish_session_epoch()
    window._sync_provenance = list(state.sync_provenance)
    window._pending_exact_mappings.clear()
    for provenance in state.sync_provenance:
        if len(provenance.exact_master) and len(provenance.exact_source):
            target = relink_map.get(provenance.target_id, provenance.target_id)
            window._pending_exact_mappings[target] = (
                np.asarray(provenance.exact_master, dtype=np.float64),
                np.asarray(provenance.exact_source, dtype=np.float64),
            )

    for ve in state.videos:
        p = Path(relink_map.get(ve.path, ve.path))
        if p.exists():
            window._load_video(p, offset=ve.offset, drift_ppm=ve.drift_ppm)
            if ve.integrity_flags or ve.metadata:
                from avialsync.core.inspection import IntegrityFlags

                ins = SourceInspection(
                    path=str(p),
                    integrity_flags=IntegrityFlags.from_dict(ve.integrity_flags),
                    import_config=ve.metadata,
                )
                window._inspections[str(p)] = ins

    for se in state.sensors:
        p = Path(relink_map.get(se.path, se.path))
        if p.exists():
            # Import is asynchronous, so the accepted mapping is held until
            # the worker reports the cache back (see _on_import_finished).
            window._pending_sensor_mappings[str(p)] = (se.offset, se.drift_ppm)
            window._start_data_import(p)
            if se.loader_id or se.import_report:
                from avialsync.core.inspection import ImportReport

                ins = SourceInspection(
                    path=str(p),
                    loader_id=se.loader_id,
                    import_config=dict(se.import_config),
                    import_report=(
                        ImportReport.from_dict(se.import_report) if se.import_report else None
                    ),
                )
                window._inspections[str(p)] = ins

    # Restore annotations
    from avialsync.ui.annotations import VideoFrame

    for me in state.markers:
        vfs = [
            VideoFrame(
                path=str(vf["path"]),
                frame_index=int(vf["frame_index"]),
                media_timestamp=float(vf["media_timestamp"]),
            )
            for vf in me.video_frames
        ]
        if me.t_end is not None:
            window.annotation_store.add_range(me.t_start, me.t_end, me.label, video_frames=vfs)
        else:
            window.annotation_store.add_point(me.t_start, me.label, video_frames=vfs)

    # Restore the shared fixed-window duration even while sources load asynchronously.
    if state.plot_x0 is not None and state.plot_x1 is not None:
        window.plot_pane.set_window_duration(state.plot_x1 - state.plot_x0)


def autosave(window: MainWindow) -> None:
    """Silently autosave, to the session file or to the recovery snapshot.

    Runs on the same worker path as an explicit save, so a large session
    never stalls playback on the two-minute timer.

    This used to return early when there was no session path, which meant the
    two-minute autosave protected only sessions that were already safe. A
    session that had never been saved had no protection at all (D-089), so an
    untitled session now writes a recovery snapshot instead of nothing.
    """
    if window._save_in_progress:
        return
    if window._session_path is None:
        _write_recovery_snapshot(window)
        return
    window._start_session_save(window._session_path, is_autosave=True)


def offer_pending_recovery(window: MainWindow) -> bool:
    """Offer unsaved work from a previous run, if there is any. Non-modal.

    The other half of D-089. The snapshot has been written on every quit since
    that decision landed, but nothing ever offered it back, so the work was
    preserved on disk and unreachable from the interface -- and the payload
    nests the session under a ``state`` key, so Open Session could not read it
    either.

    An offer, never a gate: it is one line in the notification strip with a
    Restore button beside it, and dismissing it declines without touching the
    snapshot. Law 1 forbids blocking the user to tell them something, and a
    launch-time "restore your work?" modal is exactly that.
    """
    snapshot = recovery.pending_recovery()
    if snapshot is None:
        return False

    when = time.strftime("%H:%M on %d %b", time.localtime(snapshot.recovered_at))
    if snapshot.describes_untitled_session:
        message = tr("Unsaved work from {when} is available.").format(when=when)
    else:
        message = tr("Work from {when} is newer than {name}.").format(
            when=when, name=Path(str(snapshot.session_path)).name
        )
    window.notifications.show_warning(
        message,
        action_label=tr("Restore"),
        on_action=lambda: restore_pending_recovery(window, snapshot),
    )
    return True


def restore_pending_recovery(window: MainWindow, snapshot: recovery.RecoverySnapshot) -> None:
    """Load a recovery snapshot into the window, as an ordinary session restore.

    The snapshot is cleared only once the restore has actually gone through.
    Clearing first would turn a failure to decode into the data loss the
    snapshot exists to prevent, and there is no second copy.
    """
    try:
        state = SessionState.from_dict(snapshot.state)
    except Exception as error:
        logger.exception("Could not decode the recovery snapshot")
        window.notifications.show_error(
            tr("That unsaved work could not be restored."), details=str(error)
        )
        return

    window._session_path = Path(snapshot.session_path) if snapshot.session_path else None
    window._restore_session(state)
    recovery.clear_recovery()
    # Restored work is unsaved work: it went back to the window, not to a file.
    window.document.mark_dirty()
    window.notifications.show_warning(
        tr("Restored. Save the session to keep it."),
    )


def _write_recovery_snapshot(window: MainWindow) -> bool:
    """Persist unsaved work for an untitled session. Returns whether it wrote.

    An empty workspace writes nothing and clears whatever was there. Reset
    Session empties the workspace and sets ``_session_path`` to ``None``, so
    without this a reset followed by a quit would overwrite a good snapshot
    with an empty one — the safety net causing the loss it exists to prevent.

    Serialising is inside the guard, not before it. One call site is
    ``closeEvent``, where the workspace can hold whatever a half-finished load
    or a test double left behind, and ``SessionState.to_dict`` raises on state
    it cannot encode. A safety net that throws on the way up is worse than no
    safety net: the surrounding ``_close_step`` would log and continue, but the
    snapshot this function exists to write would silently not happen.
    """
    try:
        state = window._build_session_state().to_dict()
    except Exception:
        logger.exception("Could not serialise the workspace for recovery; skipping the snapshot")
        return False
    if recovery.is_empty_state(state):
        recovery.clear_recovery()
        return False
    return recovery.write_recovery(state, None)


def write_session_snapshot(window: MainWindow) -> None:
    """Write the session synchronously, if one is open.

    Threading this is not an option at either call site: the window is about to
    go away, or a media client is about to be torn down in a way that can kill
    the process outright. Both are bounded by a single small JSON write, which
    is why this is the one legitimate blocking write in the application.

    With no session path the same state goes to the recovery snapshot instead,
    so closing an untitled session preserves it rather than discarding it.
    """
    if window._session_path is None:
        _write_recovery_snapshot(window)
        return
    from avialsync.engine.session_worker import SessionSaveWorker

    SessionSaveWorker(window._build_session_state(), window._session_path).run()


def autosave_before_close(window: MainWindow) -> None:
    """Flush a final synchronous autosave before the window closes.

    A threaded save started here could never finish: the window (and its
    worker registry) is gone right after this returns. It runs after the final
    paint, so the write is not competing with a UI-thread budget.

    Quitting still never prompts (D-088). It is lossless instead, which is what
    removes the reason to prompt.
    """
    write_session_snapshot(window)


def rebuild_recent_menu(window: MainWindow) -> None:
    window._recent_menu.clear()
    recent = get_recent()
    if not recent:
        act = window._recent_menu.addAction(tr("(no recent files)"))
        act.setEnabled(False)
        return
    for rpath in recent:
        act = window._recent_menu.addAction(Path(rpath).name)
        act.setToolTip(rpath)
        act.triggered.connect(lambda _checked, p=rpath: window._open_recent(p))


def open_recent(window: MainWindow, path: str) -> None:
    p = Path(path)
    if not p.exists():
        # Open Recent is one of the four paths rule 10 names: it may not put a
        # modal in front of the user, not even to say the file is gone. The
        # presenter's Locate action is the useful half of that message anyway.
        window.report_failure(
            SourceOpenError(f"Session file no longer exists: {path}"),
            doing=f"opening {p.name}",
        )
        return
    window._start_session_load(p)
