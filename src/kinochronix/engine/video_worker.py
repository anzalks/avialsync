"""Background video-source opening and preparation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from kinochronix.core.registry import LoaderRegistry
from kinochronix.core.source import VideoSource


class VideoOpenWorker(QObject):
    """Select, open, and optionally prepare one video source off the UI thread."""

    progress = Signal(int)
    opened = Signal(str, object, str)  # original path, VideoSource, playable media path
    error = Signal(str, str)  # original path, actionable error
    cancelled = Signal()

    def __init__(self, path: Path, config: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._path = path
        self._config = {} if config is None else config
        self._cancelled = False

    @Slot()
    def cancel(self) -> None:
        """Request cancellation between source operations."""
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        """Open the selected source and emit a usable media path on success."""
        try:
            loader_class = LoaderRegistry().find_best_loader(self._path)
            if loader_class is None or not issubclass(loader_class, VideoSource):
                raise ValueError(f"No video loader can open: {self._path}")
            if self._cancelled:
                self.cancelled.emit()
                return

            loader = loader_class()
            loader.open(self._path, self._config)
            if self._cancelled:
                self.cancelled.emit()
                return

            if loader.needs_conversion():
                media_path = loader.prepare(self._emit_progress)
            else:
                media_path = loader.media_path()
            if self._cancelled:
                self.cancelled.emit()
                return
            self.progress.emit(100)
            self.opened.emit(str(self._path), loader, str(media_path))
        except Exception as error:
            self.error.emit(str(self._path), str(error))

    def _emit_progress(self, progress: float) -> None:
        """Adapt the plugin's normalized progress callback to the UI signal."""
        self.progress.emit(max(0, min(100, round(progress * 100))))
