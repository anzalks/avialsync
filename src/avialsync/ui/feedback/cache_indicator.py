"""The status bar's cache readout: how much disk the cache holds, and Delete All Cache.

The cache was visible only as File → Cache, which says nothing about its size
until something is deleted. The readout keeps the size in view, beside the
command that frees it.

Measured on a background job, because a large cache is thousands of files. It
is measured once the window first shows, and again whenever every other
background job has finished -- imports and deletions are what change it -- so
nothing polls the disk. The measuring job is kept out of the Tasks panel unless
it runs long.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QShowEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from avialsync.core.cache import cache_root
from avialsync.engine.cache_size_worker import CacheSizeWorker
from avialsync.ui.action_button import ActionButton
from avialsync.ui.design_tokens import spacing
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.job_manager import JobManager

__all__ = ["CacheIndicator", "format_size", "is_measuring"]

#: Settle time after the last job ends, so a queue of imports is measured once.
_SETTLE_MS = 750

#: A measurement this quick never appears in the Tasks panel.
_ANNOUNCE_AFTER_S = 2.0


def format_size(count: int) -> str:
    """A byte count as people read it: ``12.3 GB``."""
    if count < 1000:
        return f"{count} B"
    value = count / 1000
    for unit in ("KB", "MB"):
        if value < 1000:
            return f"{value:.1f} {unit}"
        value /= 1000
    return f"{value:.1f} GB"


def is_measuring(job: Any) -> bool:
    """Whether *job* is only this readout reading the cache's size."""
    return isinstance(getattr(job, "worker", None), CacheSizeWorker)


class CacheIndicator(QWidget):
    """``Cache: 1.2 GB`` and the Delete All Cache button, in the status bar."""

    def __init__(
        self,
        jobs: JobManager,
        run_job: Callable[..., object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._jobs = jobs
        self._run_job = run_job
        self._measuring = False
        self._stale = True
        self._shown_once = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(spacing("s"), 0, spacing("s"), 0)
        layout.setSpacing(spacing("s"))
        self.label = QLabel(tr("Cache: …"), self)
        self.label.setAccessibleName(tr("Cache size"))
        self.label.setToolTip(self._where())
        layout.addWidget(self.label)
        # Hidden until the File menu's own command is adopted: the button's
        # name, enablement and reason come from that action (rule 15).
        self.clear_button = ActionButton(self)
        layout.addWidget(self.clear_button)
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(_SETTLE_MS)
        self._settle.timeout.connect(self.refresh)
        jobs.jobs_changed.connect(self._on_jobs_changed)

    def set_clear_action(self, action: QAction) -> None:
        """Offer *action* (File → Cache → Delete All Cache) beside the size."""
        self.clear_button.set_action(action)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """Measure when first on screen, not at construction."""
        super().showEvent(event)
        if not self._shown_once:
            self._shown_once = True
            self._settle.start()

    def refresh(self) -> None:
        """Measure the cache now, or as soon as the measurement running ends."""
        if self._measuring or self._jobs.is_shutting_down() or not self.isVisible():
            # A closing window starts nothing: a thread still running at exit aborts.
            self._stale = True
            return
        self._measuring = True
        self._stale = False
        worker = CacheSizeWorker(cache_root())

        def wire(_thread: object) -> None:
            worker.finished.connect(on_ui_thread(self._show_size, self))
            worker.error.connect(on_ui_thread(self._show_failure, self))

        self._run_job(
            worker,
            label=tr("Measuring the cache"),
            configure=wire,
            announce_after_s=_ANNOUNCE_AFTER_S,
        )

    def _show_size(self, size: int) -> None:
        self._measuring = False
        self.label.setText(tr("Cache: {size}").format(size=format_size(int(size))))
        self.label.setToolTip(self._where())
        if self._stale:
            self._settle.start()

    def _show_failure(self, message: str) -> None:
        self._measuring = False
        self.label.setText(tr("Cache: size unknown"))
        self.label.setToolTip(f"{self._where()}\n{message}")

    def _on_jobs_changed(self) -> None:
        if any(not is_measuring(job) for job in self._jobs.jobs()):
            # Something that may write to the cache is running; measure after it.
            self._stale = True
            self._settle.stop()
            return
        if self._stale and self._shown_once and not self._measuring:
            self._settle.start()

    @staticmethod
    def _where() -> str:
        return tr(
            "Disk used by cached imports in {folder}. Recordings, corrections and "
            "sessions are never stored there."
        ).format(folder=cache_root())
