"""Present window feedback using supplied widgets and the existing job owner.

MainWindow retains its Qt receivers and job-start entry point. This component
only presents their state; it does not discover sources or own another registry.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow

from avialsync.ui.feedback import ActivityBar, JobsPanel, NotificationStrip
from avialsync.ui.feedback.cache_indicator import CacheIndicator
from avialsync.ui.feedback.error_presenter import present
from avialsync.ui.feedback.tasks_button import TasksButton
from avialsync.ui.feedback.text_dialog import show_text
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import JobManager
from avialsync.ui.transport import Transport


class WindowFeedback(QObject):
    """Own feedback presentation with the window's lifetime and thread affinity."""

    def __init__(
        self,
        owner: QMainWindow,
        jobs: JobManager,
        transport: Transport,
        activity: ActivityBar,
        notifications: NotificationStrip,
        panel: JobsPanel,
    ) -> None:
        super().__init__(owner)
        self.owner = owner
        self.jobs = jobs
        self.transport = transport
        self.activity = activity
        self.notifications = notifications
        self.panel = panel

    def install_status(
        self,
        run_job: Callable[..., object],
        clear_action: QAction,
    ) -> tuple[CacheIndicator, TasksButton]:
        """Install existing status widgets, retaining the window's registered job entry point."""
        bar = self.owner.statusBar()
        bar.addWidget(self.transport.status_line, 1)
        cache = CacheIndicator(self.jobs, run_job, self.owner)
        cache.set_clear_action(clear_action)
        bar.addPermanentWidget(cache)
        bar.addPermanentWidget(self.activity)
        tasks = TasksButton(self.panel, self.owner)
        bar.addPermanentWidget(tasks)
        return cache, tasks

    def cancel_active_task(self, cancel: Callable[[], None] | None) -> None:
        """Cancel through the existing legacy callback and the sole job registry."""
        if cancel is not None:
            try:
                cancel()
            except RuntimeError:
                pass  # Its worker's C++ object is already gone.
        self.jobs.cancel_all()
        self.activity.end()

    def show_task_details(self, details: str) -> None:
        """Show full failure text only in response to the user's details action."""
        show_text(self.owner, tr("Details"), details)

    def report_failure(self, error: BaseException, *, doing: str = "") -> None:
        """Present typed failures through the single error presenter."""
        presented = present(error, doing=doing)
        message = f"{presented.title}. {presented.cause}"
        if presented.recoverable:
            self.notifications.show_error(message, details=presented.details)
        else:  # pragma: no cover - no unrecoverable presenter exists yet
            show_text(self.owner, presented.title, presented.details, lead=message)

    def refresh_jobs_panel(self) -> None:
        """Read running-job rows from the sole registry for every refresh."""
        self.panel.refresh([job.panel_row() for job in self.jobs.announced_jobs()])

    def jobs_changed(
        self,
        refresh_availability: Callable[[], None],
        refresh_panel: Callable[[], None],
    ) -> None:
        """Refresh command availability and both busy and idle presentations."""
        refresh_availability()
        text = self.jobs.status_text()
        if not text:
            self.transport.set_status("Ready")
        else:
            kind = "error" if self.jobs.stalled_jobs() else "busy"
            self.transport.set_status(text, kind)
        refresh_panel()

    def ui_stalled(self, milliseconds: float) -> None:
        """Present the existing heartbeat's observation without another timer."""
        self.transport.set_status(f"Interface stalled for {milliseconds / 1000:.1f} s", "error")
