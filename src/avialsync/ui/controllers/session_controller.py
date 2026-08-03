"""Session persistence, window geometry, autosave, and the recent-files menu.

Everything that reads or writes state which must outlive the process: the
``.avv`` session document, the ``QSettings`` window/splitter geometry, the
two-minute autosave, and the recent-files list they both feed.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QMessageBox

from avialsync.core.inspection import SourceInspection
from avialsync.core.session import (
    MarkerEntry,
    SensorEntry,
    SessionState,
    VideoEntry,
)
from avialsync.ui.recent_files import add_recent, get_recent

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


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
        t_start=bounds[0],
        t_end=bounds[1],
        plot_x0=plot_x0,
        plot_x1=plot_x1,
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

    from avialsync.engine.session_worker import SessionSaveWorker

    worker = SessionSaveWorker(state, path)
    thread = window._run_job(worker)

    if not is_autosave:
        window.transport.set_status("Saving session…")

    def on_finished():
        window._session_path = path
        add_recent(str(path))
        if not is_autosave:
            window.transport.set_status("")

    def on_error(msg: str):
        if not is_autosave:
            window.transport.set_status("")
            QMessageBox.critical(window, "Save Error", f"Could not save session:\n{msg}")
        else:
            logger.exception("Autosave failed for %s: %s", path, msg)

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

    thread.start()


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
    thread = window._run_job(worker)

    def on_finished(state: SessionState):
        window.transport.set_status("")
        window._session_path = path
        add_recent(str(path))
        window._restore_session(state)

    def on_error(msg: str):
        window.transport.set_status("")
        QMessageBox.critical(window, "Session Error", f"Could not load session:\n{msg}")

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

    thread.start()


def on_session_load_error(window: MainWindow, error: str) -> None:
    window.statusBar().clearMessage()
    logger.error("Session load failed: %s", error)
    QMessageBox.critical(window, "Session Error", f"Could not load session:\n{error}")


def restore_session(window: MainWindow, state: SessionState) -> None:
    """Load all sources from a SessionState object."""
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
    """Silently autosave if a session path is set.

    Runs on the same worker path as an explicit save, so a large session
    never stalls playback on the two-minute timer.
    """
    if window._session_path is None or window._save_in_progress:
        return
    window._start_session_save(window._session_path, is_autosave=True)


def autosave_before_close(window: MainWindow) -> None:
    """Flush a final synchronous autosave before the window closes.

    A threaded save started here could never finish: the window (and its
    worker registry) is gone right after this returns. This is the one
    legitimate blocking write in the app — it runs after the final paint
    and is bounded by a single small JSON write, not a UI-thread budget.
    """
    if window._session_path is None:
        return
    from avialsync.engine.session_worker import SessionSaveWorker

    SessionSaveWorker(window._build_session_state(), window._session_path).run()


def rebuild_recent_menu(window: MainWindow) -> None:
    window._recent_menu.clear()
    recent = get_recent()
    if not recent:
        act = window._recent_menu.addAction("(no recent files)")
        act.setEnabled(False)
        return
    for rpath in recent:
        act = window._recent_menu.addAction(Path(rpath).name)
        act.setToolTip(rpath)
        act.triggered.connect(lambda _checked, p=rpath: window._open_recent(p))


def open_recent(window: MainWindow, path: str) -> None:
    p = Path(path)
    if not p.exists():
        QMessageBox.warning(
            window,
            "File Not Found",
            f"Session file no longer exists:\n{path}",
        )
        return
    window._start_session_load(p)
