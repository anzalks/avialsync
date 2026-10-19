"""Generate a scrubbing proxy for the selected camera, as a registered job.

Moved from MainWindow (WINDOW_COMPOSITION_PLAN A3), which keeps one delegator
per function (D-066). The worker signals still reach the window's own methods,
so delivery stays queued onto the UI thread. The worker is no longer also held
on the window: :class:`~avialsync.ui.job_manager.JobManager` owns it until its
thread finishes (D-148), and nothing read the duplicate handles.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread

from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


def generate_proxy(window: MainWindow) -> None:
    """Ask where to write a proxy of the selected camera, then build it in the background."""
    if not window.video_grid._paths:
        window.notifications.show_warning(tr("Load a video before generating a proxy."))
        return

    from avialsync.engine.proxy import ProxyWorker
    from avialsync.ui import export_destinations

    # The selected camera, as a nudge moves it. This was the first camera
    # whatever was selected, so with three loaded only one could be proxied.
    path = window._focused_video_path()
    if path is None:
        window.notifications.show_warning(
            tr("Click the camera you want a proxy of first, or open one fullscreen.")
        )
        return
    video_path = Path(path)
    chosen = export_destinations.choose_proxy(window, video_path)  # D-244
    if chosen is None:
        return
    worker = ProxyWorker(video_path, chosen)

    # Proxy generation is minutes of transcoding. Behind a modal that was
    # minutes of unusable application, for work the user started so they
    # could keep looking at the session.
    window.activity_bar.begin(f"Generating proxy for {video_path.name}")
    window._active_cancel = worker.cancel

    def _wire(_thread: QThread) -> None:
        worker.progress.connect(window.activity_bar.set_progress)
        worker.finished.connect(window._on_proxy_finished)
        worker.error.connect(window._on_proxy_error)

    # Registered rather than hand-wired. `JobManager` connects
    # `started -> run` and quits the thread on `finished`/`error`, and a
    # transcode that wedges is reported as not responding instead of merely
    # looking busy.
    window._run_job(worker, label=f"Generating proxy for {video_path.name}", configure=_wire)


def on_proxy_finished(window: MainWindow, proxy: str) -> None:
    """Offer the finished proxy, rather than leaving it on disk unmentioned."""
    window.activity_bar.end()
    window._active_cancel = None
    window.notifications.show_success(
        tr("Proxy ready: {name} (720p 8-bit, for scrubbing)").format(name=Path(proxy).name),
        action_label=tr("Open Proxy"),
        on_action=lambda: window._load_video(Path(proxy)),
    )


def on_proxy_error(window: MainWindow, error: str) -> None:
    """End the activity and report the failure, raw text behind "Show details"."""
    window.activity_bar.end()
    window._active_cancel = None
    window.notifications.show_error(tr("Could not generate the proxy"), details=error)
