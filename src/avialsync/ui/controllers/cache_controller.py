"""File → Cache: delete this trial's cache, delete all of it, or show it (D-160).

The cache holds only what AvialSync can rebuild from the files beside it, so
these commands never ask "are you sure": nothing the user made can be lost,
only the time a re-import takes.  What they must not do is pull arrays out
from under a loaded trial, which is still reading them -- and on Windows cannot
let go of them while it does.  So a loaded workspace is captured, closed,
emptied of its cache and then put back exactly as it was: the same sources,
mappings and markers, re-imported from the original files, and still marked
unsaved when it was.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, QUrl
from PySide6.QtGui import QDesktopServices

from avialsync.core import cache_store
from avialsync.core.cache import cache_root
from avialsync.core.errors import CacheError
from avialsync.ui.controllers import session_controller
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.core.session import SessionState
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def loaded_sources(state: SessionState) -> list[str]:
    """Every file *state* was opened from."""
    return [
        *(entry.path for entry in state.videos),
        *(entry.path for entry in state.sensors),
        *(entry.path for entry in state.triggers),
    ]


def delete_trial_cache(window: MainWindow) -> None:
    """Delete the cache of every source in the loaded trial's folder."""
    state = session_controller.build_session_state(window)
    folders = cache_store.working_folders(loaded_sources(state))
    if not folders:
        return
    where = folders[0].name if len(folders) == 1 else tr("the loaded files")
    _remove(window, folders, where)


def delete_all_cache(window: MainWindow) -> None:
    """Delete every cached entry, for every recording ever opened."""
    _remove(window, None, tr("every recording"))


def show_cache_folder(window: MainWindow) -> None:
    """Open the cache folder in the platform's file manager."""
    root = cache_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        window.report_failure(CacheError(str(error)), doing="The cache folder could not be created")
        return
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))


def _remove(window: MainWindow, folders: list[Path] | None, where: str) -> None:
    """Close what is loaded, remove the entries in a job, then put it back."""
    from avialsync.engine.cache_worker import CacheRemovalWorker

    root = cache_root()
    state: SessionState | None = session_controller.build_session_state(window)
    path = window.session_runtime.path
    was_dirty = window.document.is_dirty
    if state is not None and loaded_sources(state):
        session_controller.reset_session(window, discard_recovery=False)
    else:
        state = None
    generation = window.session_runtime.generation
    worker = CacheRemovalWorker(root, folders)

    def on_finished(report: cache_store.RemovalReport) -> None:
        restored = False
        # A workspace the user opened meanwhile is theirs now; the one this
        # removal closed is not put back over it.
        if state is not None and generation == window.session_runtime.generation:
            window.session_runtime.path = path
            window.session_runtime.dirty_after_restore = generation if was_dirty else None
            session_controller.restore_session(window, state)
            restored = True
        _report(window, report, where, restored)

    def on_error(message: str) -> None:
        if state is not None and generation == window.session_runtime.generation:
            window.session_runtime.path = path
            window.session_runtime.dirty_after_restore = generation if was_dirty else None
            session_controller.restore_session(window, state)
        window.report_failure(CacheError(message), doing="The cache could not be deleted")

    def _wire(thread: QThread) -> None:
        # Wrapped: both rebuild panes, which must happen on the UI thread (D-051).
        worker.finished.connect(on_ui_thread(on_finished, window))
        worker.error.connect(on_ui_thread(on_error, window))

    window._run_job(worker, label=tr("Deleting cached imports"), configure=_wire)


def _report(
    window: MainWindow, report: cache_store.RemovalReport, where: str, restored: bool
) -> None:
    """Say what was removed, what was kept, and what happens next."""
    message = tr("Deleted {n} cached import(s) for {where}, freeing {size}.").format(
        n=report.removed, where=where, size=_size(report.freed_bytes)
    )
    if restored:
        message += " " + tr("Re-importing from the original files.")
    if report.failed:
        details = "\n".join(f"{directory}: {reason}" for directory, reason in report.failed)
        window.notifications.show_warning(
            message
            + " "
            + tr("{n} could not be removed and were kept.").format(n=len(report.failed)),
            details=details,
        )
        return
    window.notifications.show_success(message)


def _size(count: int) -> str:
    """A byte count as people read it: ``12.3 GB``."""
    if count < 1000:
        return f"{count} B"
    value = count / 1000
    for unit in ("KB", "MB"):
        if value < 1000:
            return f"{value:.1f} {unit}"
        value /= 1000
    return f"{value:.1f} GB"
