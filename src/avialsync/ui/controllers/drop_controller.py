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
from PySide6.QtWidgets import QMessageBox

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
    QMessageBox.critical(window, "Import Error", f"Failed to scan dropped files:\n{error_msg}")


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

    if layout.anchor_epoch > 0.0:
        # The session knows what absolute instant its timestamps are relative
        # to, so times become readable wall clock rather than seconds-from-zero.
        window.plot_pane.set_time_mode(TimeDisplayMode.UTC, layout.anchor_epoch)
        window.transport.set_t_epoch(layout.anchor_epoch)

    if layout.skeleton:
        window.tracking_3d_pane.set_skeleton(layout.skeleton)


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

    dialog = BatchImportDialog(candidates, window, labels=window._session_item_labels)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        selections = dialog.get_selections()
        window.video_grid.begin_batch_add()
        try:
            for path, loader_cls, config in selections:
                window._route_import_candidate(path, loader_cls, config)
        finally:
            window.video_grid.end_batch_add()
