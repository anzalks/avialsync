"""Measure the cache folder off the UI thread.

A large cache is thousands of files, and walking them is file IO the UI thread
must not wait on. Register through ``MainWindow._run_job``, like every other worker.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core import cache_store

logger = logging.getLogger(__name__)


class CacheSizeWorker(QObject):
    """Report how many bytes the cache folder at *root* holds."""

    finished = Signal(object)  # int, bytes
    error = Signal(str)

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root

    @Slot()
    def run(self) -> None:
        try:
            size = cache_store.cache_size(self._root)
        except OSError as error:
            logger.warning("Could not measure the cache under %s", self._root, exc_info=True)
            self.error.emit(str(error))
            return
        self.finished.emit(size)
