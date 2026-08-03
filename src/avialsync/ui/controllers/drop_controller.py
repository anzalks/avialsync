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

from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QMessageBox

from avialsync.core.source import TimeSeriesSource, VideoSource
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
    thread = window._run_job(worker)

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

    thread.start()


def on_drop_session_found(window: MainWindow, path: str) -> None:
    """Handle a .avv file found during drop scanning."""
    window._start_session_load(Path(path))


def on_drop_scan_error(window: MainWindow, error_msg: str) -> None:
    window.transport.set_status("")
    QMessageBox.critical(window, "Import Error", f"Failed to scan dropped files:\n{error_msg}")


def on_drop_scan_finished(
    window: MainWindow,
    candidates: list[tuple[Path, type | None, dict | None]],
    is_aol_session: bool,
) -> None:
    window.transport.set_status("")

    if not candidates:
        return

    # Check for the virtual AOL setup candidate. Compare Path objects: a
    # string round-trip does not survive Windows path normalisation, which
    # previously leaked this marker row into the import dialog and skipped
    # the session's fps/anchor/skeleton setup entirely.
    from avialsync.engine.drop_worker import AOL_SESSION_SETUP

    setup_idx = next((i for i, c in enumerate(candidates) if c[0] == AOL_SESSION_SETUP), -1)
    if setup_idx >= 0:
        _, _, config = candidates.pop(setup_idx)
        if config:
            window._aol_camera_fps = config.get("camera_fps", 0.0)
            window._aol_anchor_epoch = config.get("anchor_epoch", 0.0)
            if window._aol_anchor_epoch > 0.0:
                window.plot_pane.set_time_mode(TimeDisplayMode.UTC, window._aol_anchor_epoch)
                window.transport.set_t_epoch(window._aol_anchor_epoch)

            skeleton = config.get("skeleton")
            if skeleton:
                window.tracking_3d_pane.set_skeleton(skeleton)

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

    dialog = BatchImportDialog(candidates, window)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        selections = dialog.get_selections()
        window.video_grid.begin_batch_add()
        try:
            for path, loader_cls, config in selections:
                window._route_import_candidate(path, loader_cls, config)
        finally:
            window.video_grid.end_batch_add()
