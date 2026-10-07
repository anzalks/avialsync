"""Coalesce authored-file revisions and register each write as a visible job."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, QUrl
from PySide6.QtGui import QDesktopServices

from avialsync.engine.artifact_write_worker import ArtifactWriteWorker
from avialsync.ui.export_sources import loaded_source_paths
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


def reveal(path: Path) -> None:
    """Open the containing folder for an output the user asked to locate."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def loaded_sources(window: MainWindow) -> tuple[Path, ...]:
    """Capture the loaded file paths before an export leaves the UI thread."""
    return loaded_source_paths(window)


def show_exported(window: MainWindow, message: str, path: Path) -> None:
    """Give a completed output one notification and a reveal affordance."""
    window.notifications.show_success(
        message,
        action_label=tr("Reveal"),
        on_action=lambda: reveal(path),
    )


@dataclass(slots=True)
class _Request:
    label: str
    write: Callable[[], Path]
    success: Callable[[Path], None]
    failure: Callable[[str], None]


class ArtifactWriteQueue:
    """Keep only the newest pending revision for each destination path."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window
        self._active: set[Path] = set()
        self._pending: dict[Path, _Request] = {}

    def enqueue(
        self,
        target: Path,
        *,
        label: str,
        write: Callable[[], Path],
        success: Callable[[Path], None],
        failure: Callable[[str], None],
    ) -> None:
        """Queue an immutable snapshot; a later snapshot replaces it by path."""
        self._pending[target] = _Request(label, write, success, failure)
        self._start(target)

    @property
    def idle(self) -> bool:
        """Whether no revision of any path is being written or waiting."""
        return not self._active and not self._pending

    def has_newer(self, target: Path) -> bool:
        """Whether an active revision has a later revision waiting for this path."""
        return target in self._pending

    def _start(self, target: Path) -> None:
        if target in self._active or target not in self._pending:
            return
        request = self._pending.pop(target)
        self._active.add(target)
        worker = ArtifactWriteWorker(request.write)

        def complete(path: Path | None = None, error: str = "") -> None:
            self._active.discard(target)
            if error:
                request.failure(error)
            elif path is not None:
                request.success(path)
            self._start(target)

        def wire(_thread: QThread) -> None:
            worker.finished.connect(on_ui_thread(lambda path: complete(path=path), self.window))
            worker.error.connect(on_ui_thread(lambda error: complete(error=error), self.window))

        self.window._run_job(worker, label=request.label, configure=wire)
