"""Drag-and-drop intake and capability-resolved import routing.

Everything a dropped path goes through before it becomes a normal load: the Qt
drag/drop overrides, the background scan that classifies what was dropped, and
the routing of each resolved candidate to the video or time-series path.
``MainWindow.open_path`` enters here too, so ``avialsync open <path>`` and a
drop cannot drift apart.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from avialsync.core.errors import FileUnreadableError
from avialsync.core.source import SessionLayout, TimeSeriesSource, VideoSource
from avialsync.ui.time_format import TimeDisplayMode

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def drag_enter(window: MainWindow, event: QDragEnterEvent) -> None:
    if event.mimeData().hasUrls():
        event.acceptProposedAction()


def drop_event(window: MainWindow, event: QDropEvent) -> None:
    if not event.mimeData().hasUrls():
        event.ignore()
        return
    event.acceptProposedAction()

    paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
    paths = [p for p in paths if p.exists()]

    if not paths:
        return

    window._start_drop_scan(paths)


def start_drop_scan(window: MainWindow, paths: list[Path]) -> None:
    """Launch background scanning for dropped paths."""
    from avialsync.engine.drop_worker import DropScanWorker

    window.transport.set_status("Scanning files…")
    worker = DropScanWorker(paths, window._registry)

    # Wired through `configure`, which runs before the thread starts. Connecting
    # after `_run_job` returns is a race: the thread is already running, and a
    # scan of one small file can finish before the main thread gets here, so
    # `finished` is emitted with no receiver and the drop is silently a no-op —
    # the exact defect tests/test_worker_lifetime.py exists to catch.
    def _wire(thread: QThread) -> None:
        worker.finished.connect(window._on_drop_scan_finished)
        worker.session_found.connect(window._on_drop_session_found)
        worker.error.connect(window._on_drop_scan_error)

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


def on_drop_session_found(window: MainWindow, path: str) -> None:
    """Handle a .avv file found during drop scanning."""
    window._start_session_load(Path(path))


def on_drop_scan_error(window: MainWindow, error_msg: str) -> None:
    window.transport.set_status("")
    window.report_failure(
        FileUnreadableError(error_msg), doing="Those dropped files could not be scanned"
    )


def apply_session_layout(window: MainWindow, layout: object) -> None:
    """Adopt the settings a session plugin reported for the folder it laid out.

    Format-neutral: these are properties any session may declare, not one lab's
    fields. A drop that no session plugin claimed carries an empty layout and
    changes nothing, so an ordinary file drop never disturbs the current time
    mode.

    Typed ``object`` and checked, because it arrives over a Qt signal declared
    ``Signal(list, object)`` — Qt cannot enforce the payload type, so anything
    still connected from an older build would otherwise crash the drop handler
    rather than be ignored.
    """
    if not isinstance(layout, SessionLayout):
        return

    window._session_camera_fps = layout.camera_fps
    window._session_anchor_epoch = layout.anchor_epoch
    # A session knows what each item is; the dialog can only re-derive a name
    # from the path. Keyed by path rather than carried in the candidate tuple,
    # which several consumers and any third-party signal reader unpack by arity.
    window._session_item_labels = {
        str(item.path): item.label for item in layout.items if item.label
    }
    window._session_item_kinds = {str(item.path): item.kind for item in layout.items if item.kind}
    # Which items share one Data Streams lane is the session's call for the same
    # reason: seven files extracted from three videos cover one span, and only
    # the thing that laid them out knows that they do.
    window._session_coverage_groups = {
        str(item.path): item.coverage_group for item in layout.items if item.coverage_group
    }
    # What instant each file's timestamps count from. The session is the only
    # thing that knows -- a camera counts from its own first frame, a MATLAB
    # log from midnight -- and declaring it is what lets every one of them be
    # placed on one clock without anybody typing an offset (D-110).
    window._declared_source_epochs = {
        str(item.path): float(item.source_epoch)
        for item in layout.items
        if item.source_epoch is not None
    }

    # The session sees every item at once, so it -- not whichever probe happens
    # to finish first -- declares where master zero is. Through
    # `adopt_session_start`, because that is the one authority for the session
    # zero: this used to write `transport.set_t_epoch` directly and leave
    # `_session_start_time` at 0.0, so the clock read correct wall time while
    # the placement machinery believed the session had no wall clock at all and
    # left every AOL source to carry its own 34526 s by hand (D-110).
    declared = layout.session_epoch or layout.anchor_epoch
    if declared > 0.0:
        window.adopt_session_start(declared)
        # Times become readable wall clock rather than seconds-from-zero.
        window._set_time_mode(TimeDisplayMode.UTC)

    # Set unconditionally, including to nothing: a session that declares no
    # skeleton must not inherit the previous one's bones, and an empty list is
    # what hands the 3D view over to its own detection (D-082).
    window.tracking_3d_pane.set_skeleton(list(layout.skeleton or []))
    # Likewise the wheel: which channel turns it is the rig's to say, and it
    # only pre-fills Add Wheel -- it is never applied on its own (D-113).
    window._session_rotary = layout.rotary

    # A scan that left something out has to say so on screen.  The log already
    # holds the detail; what belongs here is the fact that the session in front
    # of the user is not everything the folder contained (D-085).
    if layout.warnings:
        first = layout.warnings[0]
        more = len(layout.warnings) - 1
        window.transport.set_status(
            first + (f" (and {more} more)" if more else ""), severity="warning"
        )


def on_drop_scan_finished(
    window: MainWindow,
    candidates: list[tuple[Path, type | None, dict | None]],
    layout: object = None,
) -> None:
    window.transport.set_status("")

    apply_session_layout(window, layout)

    if not candidates:
        return

    if len(candidates) == 1:
        # Bypass dialog for single files only
        for path, loader_cls, config in candidates:
            if loader_cls is not None:
                window.video_grid.begin_batch_add()
                try:
                    window._route_import_candidate(path, loader_cls, config)
                finally:
                    window.video_grid.end_batch_add()
        return

    window._process_drop_candidates(candidates)


def route_import_candidate(
    window: MainWindow,
    path: Path,
    loader_cls: type[TimeSeriesSource | VideoSource],
    config: dict | None = None,
) -> None:
    """Route one capability-resolved source through its normal loader path."""
    if loader_cls is None:
        logger.warning("Ignoring import candidate with no loader: %s", path)
        return
    config = config or {}
    if issubclass(loader_cls, VideoSource):
        offset = config.get("offset", 0.0)
        if "offset" in config:
            config = dict(config)
            del config["offset"]
        window._load_video(path, offset=offset, config=config)
    else:
        window._start_data_import(path, loader_cls, pre_config=config)


def process_drop_candidates(
    window: MainWindow, candidates: list[tuple[Path, type | None, dict | None]]
) -> None:
    """Present the batch import dialog and route accepted items."""
    from PySide6.QtWidgets import QDialog

    from avialsync.ui.batch_import_dialog import BatchImportDialog

    dialog = BatchImportDialog(
        candidates,
        window,
        labels=window._session_item_labels,
        kinds=window._session_item_kinds,
    )
    if dialog.exec() == QDialog.DialogCode.Accepted:
        selections = dialog.get_selections()
        window.video_grid.begin_batch_add()
        try:
            for path, loader_cls, config in selections:
                window._route_import_candidate(path, loader_cls, config)
        finally:
            window.video_grid.end_batch_add()
