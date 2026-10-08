"""Background removal of cache entries (D-160).

A trial's cache can be tens of gigabytes across thousands of files, so
removing it is file IO the UI thread must not wait on (architecture rule 3).
Register through ``MainWindow._run_job``, like every other worker.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core import cache_store

logger = logging.getLogger(__name__)


class CacheRemovalWorker(QObject):
    """Remove the entries under *folders*, or every entry when it is None."""

    finished = Signal(object)  # cache_store.RemovalReport
    error = Signal(str)

    def __init__(
        self,
        root: Path,
        folders: list[Path] | None,
        *,
        trim: bool = False,
        protected_sources: list[str] | None = None,
    ) -> None:
        super().__init__()
        # Resolved by the caller, on the UI thread, so the folder the user was
        # shown and the folder emptied cannot differ.
        self._root = root
        self._folders = folders
        self._trim = trim
        self._protected_sources = protected_sources or []

    @Slot()
    def run(self) -> None:
        try:
            if self._trim:
                report = cache_store.trim_cache(
                    self._root, protected_sources=self._protected_sources
                )
            elif self._folders is None:
                report = cache_store.remove_all(self._root)
            else:
                entries = cache_store.entries_under(self._folders, self._root)
                report = cache_store.remove_entries(entries, self._root)
        except Exception as error:  # noqa: BLE001 - reported to the user, never swallowed
            logger.exception("Cache removal failed under %s", self._root)
            self.error.emit(str(error))
            return
        self.finished.emit(report)
