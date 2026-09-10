"""Snapshot, data-slice, video-clip, and A/B region-statistics export.

Every job here hands immutable captures or worker-safe reader references to a
background thread and reports the outcome through the feedback surface.

**These four used to run outside :class:`~avialsync.ui.job_manager.JobManager`**
(D-107).  Each kept its own ``dict[QThread, object]`` on the window, wired its
own ``started``/``finished``/``error`` connections, reported progress by writing
the transport status line directly, and announced its result in a raw
``QMessageBox`` — a modal *on success*, for work the user had already been told
was running.  Four consequences, all of them things the user met:

* **Cancel did nothing.**  The activity area's cancel button drives
  ``_active_cancel``, which only the CSV import and the proxy builder ever set,
  so a running export offered no way to stop.
* **A stall was invisible.**  ``JobManager``'s watchdog is what separates "slow"
  from "stuck"; a wedged ffmpeg on a network share merely looked busy.
* **The status line contradicted itself.**  ``_on_jobs_changed`` writes "Ready"
  whenever the manager empties, so saving a session while an export ran wiped
  the export's own status text.
* **Neighbouring menu items behaved differently.**  Export Changes reported
  through the notification strip while the three items under it in the same
  menu raised modals, two of them on success.

So they go through ``window._run_job`` like everything else, and say what
happened through ``window.notifications``.  Failures go through
``window.report_failure`` so a worker's raw text lands behind "Show details"
rather than in the message itself (AGENTS rule 12).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QFileDialog

from avialsync.core.errors import ExportError
from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.snapshot import SnapshotFigure
from avialsync.ui.i18n import tr
from avialsync.ui.snapshot_capture import capture_figure, capture_pane_figure

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def reader_references(window: MainWindow) -> list[ReaderReference]:
    """Return worker-safe references for the currently visible data channels."""
    return [
        ReaderReference(
            channel.reader.cache_dir,
            channel.reader.channel_id,
            channel.reader.time_map.offset,
            channel.reader.time_map.drift_ppm,
        )
        for channel in window.plot_pane.channels
    ]


# ── A/B region statistics ────────────────────────────────────────────


def start_region_stats(window: MainWindow, t0: float, t1: float) -> None:
    """Calculate A/B statistics in a dedicated worker thread.

    Registered like every other job even though it reports into the readout
    rather than to the user: registration is what gives it an owner, a stall
    watchdog, and an orderly abandonment at shutdown.  Superseded requests are
    filtered by id on arrival, so several may legitimately be in flight.
    """
    if t0 >= t1:
        window.readout_panel.clear_region_stats()
        return

    from avialsync.engine.export_worker import RegionStatsWorker

    window._region_stats_request += 1
    request_id = window._region_stats_request
    worker = RegionStatsWorker(request_id, window._reader_references(), t0, t1)

    def _wire(thread: QThread) -> None:
        worker.finished.connect(window._on_region_stats_finished)
        worker.error.connect(window._on_region_stats_error)

    window._run_job(worker, label=tr("Measuring the A/B region"), configure=_wire)


def on_region_stats_finished(window: MainWindow, request_id: int, stats: object) -> None:
    """Display only the newest completed region-statistics request."""
    if request_id != window._region_stats_request:
        return
    if isinstance(stats, list):
        window.readout_panel.display_region_stats(stats)


def on_region_stats_error(window: MainWindow, request_id: int, error: str) -> None:
    """Keep stale or failed background requests out of the readout."""
    if request_id == window._region_stats_request:
        logger.warning("Could not calculate A/B region statistics: %s", error)
        window.readout_panel.clear_region_stats()


# ── Snapshot ─────────────────────────────────────────────────────────


def export_snapshot_for_pane(window: MainWindow, path: str) -> None:
    """Export a snapshot of a single video pane.

    Captured before the file dialog, as in :func:`export_snapshot`: the figure
    records the frame the user was looking at when they asked, not whatever the
    pane had decoded by the time they finished naming a file.
    """
    try:
        idx = window.video_grid._paths.index(path)
    except ValueError:
        return
    pane = window.video_grid.panes[idx]
    figure = capture_pane_figure(window, pane, Path(path).name)
    if figure.is_empty:
        window.notifications.show_warning(
            tr("There is nothing to snapshot in {name} yet.").format(name=Path(path).name)
        )
        return
    out_path, _ = QFileDialog.getSaveFileName(
        window,
        tr("Snapshot — {name}").format(name=Path(path).name),
        f"snapshot_{Path(path).stem}.png",
        tr("PNG Images (*.png)"),
    )
    if not out_path:
        return
    window._start_snapshot_export(figure, Path(out_path))


def export_snapshot(window: MainWindow) -> None:
    """Compose the displayed cameras, 3D pose, and channel stack into one figure.

    The capture happens before the file dialog is raised, so the figure records
    the instant the user asked for rather than whatever the window drifted to
    while they picked a filename.
    """
    figure = capture_figure(window)
    if figure.is_empty:
        window.notifications.show_warning(
            tr("There is nothing to snapshot: load a video or a data file first.")
        )
        return

    path, _ = QFileDialog.getSaveFileName(
        window,
        tr("Export Snapshot"),
        "snapshot.png",
        tr("PNG Images (*.png)"),
    )
    if not path:
        return

    window._start_snapshot_export(figure, Path(path))


def start_snapshot_export(window: MainWindow, figure: SnapshotFigure, path: Path) -> None:
    """Hand an immutable captured figure to a background composer and encoder."""
    from avialsync.engine.export_worker import SnapshotWorker

    worker = SnapshotWorker(figure, path)

    def _wire(thread: QThread) -> None:
        worker.finished.connect(window._on_snapshot_finished)
        worker.error.connect(window._on_snapshot_error)

    window._run_job(
        worker,
        label=tr("Exporting snapshot {name}").format(name=path.name),
        configure=_wire,
    )


def on_snapshot_finished(window: MainWindow, path: str) -> None:
    """Report background snapshot completion on the UI thread."""
    window.notifications.show_success(tr("Snapshot saved: {name}").format(name=Path(path).name))


def on_snapshot_error(window: MainWindow, error: str) -> None:
    """Report background snapshot failure on the UI thread."""
    window.report_failure(ExportError(error), doing=tr("The snapshot could not be saved"))


# ── Data slice ───────────────────────────────────────────────────────


def export_data_slice(window: MainWindow) -> None:
    if not window.plot_pane.channels:
        window.notifications.show_warning(tr("Load sensor data before exporting a data slice."))
        return

    # Use A/B loop region if set, else full bounds
    t0, t1 = window.clock.state.bounds
    if window.player._ab_in is not None and window.player._ab_out is not None:
        t0 = min(window.player._ab_in, window.player._ab_out)
        t1 = max(window.player._ab_in, window.player._ab_out)

    path, filt = QFileDialog.getSaveFileName(
        window,
        tr("Export Data Slice"),
        "data_export.csv",
        tr("CSV files (*.csv);;Parquet files (*.parquet)"),
    )
    if not path:
        return

    window._start_data_export(t0, t1, Path(path))


def start_data_export(window: MainWindow, t0: float, t1: float, path: Path) -> None:
    """Write a cached data slice on a worker thread."""
    from avialsync.engine.export_worker import DataExportWorker

    worker = DataExportWorker(window._reader_references(), t0, t1, path)

    def _wire(thread: QThread) -> None:
        worker.finished.connect(window._on_data_export_finished)
        worker.error.connect(window._on_data_export_error)

    window._run_job(
        worker,
        label=tr("Exporting data to {name}").format(name=path.name),
        configure=_wire,
    )


def on_data_export_finished(window: MainWindow, path: str) -> None:
    """Report a completed data export on the UI thread."""
    window.notifications.show_success(tr("Data exported to {name}").format(name=Path(path).name))


def on_data_export_error(window: MainWindow, error: str) -> None:
    """Show a worker-side export failure on the UI thread."""
    window.report_failure(ExportError(error), doing=tr("The data slice could not be written"))


# ── Video clip ───────────────────────────────────────────────────────


def export_video_clip(window: MainWindow) -> None:
    """Export a trimmed video clip for all loaded videos based on A/B loop."""
    if not window.video_grid._paths:
        window.notifications.show_warning(tr("Load a video before exporting a clip."))
        return

    t0 = window.transport._ab_in_t
    t1 = window.transport._ab_out_t
    if t0 is None or t1 is None:
        window.notifications.show_warning(
            tr("Set an A/B loop first — the [ and ] buttons mark where a clip starts and ends.")
        )
        return

    if t0 > t1:
        t0, t1 = t1, t0

    if len(window.video_grid._paths) == 1:
        path, _ = QFileDialog.getSaveFileName(
            window,
            tr("Export Trimmed Video"),
            "",
            tr("Video files (*.mp4 *.mkv *.mov *.avi)"),
        )
        if not path:
            return
        clips = [(window.video_grid._paths[0], t0, t1, Path(path))]
    else:
        dir_path = QFileDialog.getExistingDirectory(
            window, tr("Select Directory for Trimmed Clips")
        )
        if not dir_path:
            return

        out_dir = Path(dir_path)
        clips = [
            (
                orig_path,
                t0,
                t1,
                out_dir / f"{Path(orig_path).stem}_trim{Path(orig_path).suffix}",
            )
            for orig_path in window.video_grid._paths
        ]
    window._start_video_clip_export(clips)


def start_video_clip_export(
    window: MainWindow, clips: list[tuple[str, float, float, Path]]
) -> None:
    """Run ffmpeg trim work in a worker thread."""
    from avialsync.engine.export_worker import VideoClipWorker

    worker = VideoClipWorker(clips)

    def _wire(thread: QThread) -> None:
        worker.finished.connect(window._on_video_clip_finished)
        worker.error.connect(window._on_video_clip_error)

    label = (
        tr("Exporting 1 video clip")
        if len(clips) == 1
        else tr("Exporting {count} video clips").format(count=len(clips))
    )
    window._run_job(worker, label=label, configure=_wire)


def on_video_clip_finished(window: MainWindow, successful: int, total: int) -> None:
    """Show ffmpeg trim results once all worker jobs finish."""
    if successful == total:
        window.notifications.show_success(tr("Exported {count} clips.").format(count=successful))
    else:
        window.notifications.show_warning(
            tr("Exported {done} of {total} clips.").format(done=successful, total=total)
        )


def on_video_clip_error(window: MainWindow, error: str) -> None:
    """Show an ffmpeg worker failure on the UI thread."""
    window.report_failure(ExportError(error), doing=tr("The clip could not be exported"))
