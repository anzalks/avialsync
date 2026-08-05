"""Snapshot, data-slice, video-clip, annotation, and A/B region-statistics export.

Every job here hands immutable captures or worker-safe reader references to a
background thread and reports the outcome through the transport status line.
The ``_on_*_thread_finished`` handlers rely on ``window.sender()``: the slot Qt
invokes is the window's own method, so the window is the receiver whose sender
is the finishing thread.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QFileDialog, QMessageBox

from avialsync.engine.export_worker import ReaderReference

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


def start_region_stats(window: MainWindow, t0: float, t1: float) -> None:
    """Calculate A/B statistics in a dedicated worker thread."""
    if t0 >= t1:
        window.readout_panel.clear_region_stats()
        return

    from avialsync.engine.export_worker import RegionStatsWorker

    window._region_stats_request += 1
    request_id = window._region_stats_request
    thread = QThread(window)
    worker = RegionStatsWorker(request_id, window._reader_references(), t0, t1)
    window._region_stats_jobs[thread] = worker
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(window._on_region_stats_finished)
    worker.error.connect(window._on_region_stats_error)
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)
    # No `worker.deleteLater` here: these signals are emitted in the
    # worker thread, where the worker also lives, so the connection is
    # direct and ~QObject runs inside that thread — severing connections
    # while holding one of Qt's pooled signal/slot mutexes and then
    # taking the GIL for PySide's disconnectNotify, which deadlocks a UI
    # thread holding the GIL and waiting on a colliding mutex (D-062).
    # The owning registry drops its reference on the UI thread instead.
    thread.finished.connect(window._on_region_stats_thread_finished)
    thread.start()


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


def on_region_stats_thread_finished(window: MainWindow) -> None:
    """Release ownership of a completed region-statistics worker."""
    thread = window.sender()
    if isinstance(thread, QThread):
        window._region_stats_jobs.pop(thread, None)
        thread.deleteLater()


def export_annotations(window: MainWindow) -> None:
    """Export annotation markers to CSV — one row per (marker, video)."""
    if not window.annotation_store.markers:
        QMessageBox.information(window, "No Annotations", "There are no markers to export.")
        return
    out_path, _ = QFileDialog.getSaveFileName(
        window, "Export Annotations", "annotations.csv", "CSV Files (*.csv)"
    )
    if not out_path:
        return
    from avialsync.engine.export_worker import AnnotationExportWorker

    worker = AnnotationExportWorker(window.annotation_store.markers, Path(out_path))

    def on_finished(path: Path, count: int):
        QMessageBox.information(
            window,
            "Export Complete",
            f"Exported {count} markers to:\n{path}",
        )

    def on_error(msg: str):
        QMessageBox.critical(window, "Export Failed", f"Could not export annotations:\n{msg}")

    # Wired before the thread starts: `_run_job` returns an already-running
    # thread, so a fast export can finish before a connection made afterwards
    # exists, leaving the user with no completion dialog at all.
    def _wire(thread: QThread) -> None:
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)

        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        # No `worker.deleteLater` here: these signals are emitted in the
        # worker thread, where the worker also lives, so the connection is
        # direct and ~QObject runs inside that thread — severing connections
        # while holding one of Qt's pooled signal/slot mutexes and then
        # taking the GIL for PySide's disconnectNotify, which deadlocks a UI
        # thread holding the GIL and waiting on a colliding mutex (D-062).
        # The owning registry drops its reference on the UI thread instead.

    window._run_job(worker, configure=_wire)


def export_snapshot_for_pane(window: MainWindow, path: str) -> None:
    """Export a snapshot of a single video pane."""
    try:
        idx = window.video_grid._paths.index(path)
    except ValueError:
        return
    pane = window.video_grid.panes[idx]
    from avialsync.engine.export import snapshot_widget

    px = snapshot_widget(pane)
    out_path, _ = QFileDialog.getSaveFileName(
        window,
        f"Snapshot — {Path(path).name}",
        f"snapshot_{Path(path).stem}.png",
        "PNG Images (*.png)",
    )
    if not out_path:
        return
    window._start_snapshot_export(px.toImage().copy(), None, Path(out_path))


def export_snapshot(window: MainWindow) -> None:
    from avialsync.engine.export import snapshot_widget

    path, _ = QFileDialog.getSaveFileName(
        window,
        "Export Snapshot",
        "snapshot.png",
        "PNG Images (*.png)",
    )
    if not path:
        return

    video_px = snapshot_widget(window._media_splitter)
    plot_px = snapshot_widget(window.plot_pane)
    window._start_snapshot_export(video_px.toImage().copy(), plot_px.toImage().copy(), Path(path))


def start_snapshot_export(
    window: MainWindow, video_image: QImage | None, plot_image: QImage | None, path: Path
) -> None:
    """Hand immutable UI captures to a background PNG encoder."""
    from avialsync.engine.export_worker import SnapshotWorker

    thread = QThread(window)
    worker = SnapshotWorker(video_image, plot_image, path)
    window._snapshot_jobs[thread] = worker
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(window._on_snapshot_finished)
    worker.error.connect(window._on_snapshot_error)
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)
    # No `worker.deleteLater` here: these signals are emitted in the
    # worker thread, where the worker also lives, so the connection is
    # direct and ~QObject runs inside that thread — severing connections
    # while holding one of Qt's pooled signal/slot mutexes and then
    # taking the GIL for PySide's disconnectNotify, which deadlocks a UI
    # thread holding the GIL and waiting on a colliding mutex (D-062).
    # The owning registry drops its reference on the UI thread instead.
    thread.finished.connect(window._on_snapshot_thread_finished)
    window.transport.set_status(f"Exporting snapshot: {path.name}", "busy")
    thread.start()


def on_snapshot_finished(window: MainWindow, path: str) -> None:
    """Report background snapshot completion on the UI thread."""
    window.transport.set_status(f"Exported snapshot: {Path(path).name}")


def on_snapshot_error(window: MainWindow, error: str) -> None:
    """Report background snapshot failure on the UI thread."""
    window.transport.set_status("Snapshot export failed", "error")
    QMessageBox.critical(window, "Export Error", error)


def on_snapshot_thread_finished(window: MainWindow) -> None:
    """Release ownership of a completed snapshot encoder."""
    thread = window.sender()
    if isinstance(thread, QThread):
        window._snapshot_jobs.pop(thread, None)
        thread.deleteLater()


def export_data_slice(window: MainWindow) -> None:
    if not window.plot_pane.channels:
        QMessageBox.information(
            window,
            "No Data",
            "Load sensor data before exporting.",
        )
        return

    # Use A/B loop region if set, else full bounds
    t0, t1 = window.clock.state.bounds
    if window.player._ab_in is not None and window.player._ab_out is not None:
        t0 = min(window.player._ab_in, window.player._ab_out)
        t1 = max(window.player._ab_in, window.player._ab_out)

    path, filt = QFileDialog.getSaveFileName(
        window,
        "Export Data Slice",
        "data_export.csv",
        "CSV files (*.csv);;Parquet files (*.parquet)",
    )
    if not path:
        return

    window._start_data_export(t0, t1, Path(path))


def start_data_export(window: MainWindow, t0: float, t1: float, path: Path) -> None:
    """Write a cached data slice on a worker thread."""
    from avialsync.engine.export_worker import DataExportWorker

    thread = QThread(window)
    worker = DataExportWorker(window._reader_references(), t0, t1, path)
    window._data_export_jobs[thread] = worker
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(window._on_data_export_finished)
    worker.error.connect(window._on_data_export_error)
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)
    # No `worker.deleteLater` here: these signals are emitted in the
    # worker thread, where the worker also lives, so the connection is
    # direct and ~QObject runs inside that thread — severing connections
    # while holding one of Qt's pooled signal/slot mutexes and then
    # taking the GIL for PySide's disconnectNotify, which deadlocks a UI
    # thread holding the GIL and waiting on a colliding mutex (D-062).
    # The owning registry drops its reference on the UI thread instead.
    thread.finished.connect(window._on_data_export_thread_finished)
    window.transport.set_status(f"Exporting data: {path.name}", "busy")
    thread.start()


def on_data_export_finished(window: MainWindow, path: str) -> None:
    """Report a completed data export on the UI thread."""
    window.transport.set_status(f"Exported data: {Path(path).name}")
    QMessageBox.information(window, "Export Complete", f"Data exported to:\n{path}")


def on_data_export_error(window: MainWindow, error: str) -> None:
    """Show a worker-side export failure on the UI thread."""
    window.transport.set_status("Data export failed", "error")
    QMessageBox.critical(window, "Export Error", error)


def on_data_export_thread_finished(window: MainWindow) -> None:
    """Release ownership of a completed data-export worker."""
    thread = window.sender()
    if isinstance(thread, QThread):
        window._data_export_jobs.pop(thread, None)
        thread.deleteLater()


def export_video_clip(window: MainWindow) -> None:
    """Export a trimmed video clip for all loaded videos based on A/B loop."""
    if not window.video_grid._paths:
        QMessageBox.warning(window, "Export", "No videos are loaded.")
        return

    t0 = window.transport._ab_in_t
    t1 = window.transport._ab_out_t
    if t0 is None or t1 is None:
        QMessageBox.warning(
            window, "Export Error", "Please set an A/B loop first ([ and ] buttons)."
        )
        return

    if t0 > t1:
        t0, t1 = t1, t0

    if len(window.video_grid._paths) == 1:
        path, _ = QFileDialog.getSaveFileName(
            window, "Export Trimmed Video", "", "Video files (*.mp4 *.mkv *.mov *.avi)"
        )
        if not path:
            return
        clips = [(window.video_grid._paths[0], t0, t1, Path(path))]
    else:
        dir_path = QFileDialog.getExistingDirectory(window, "Select Directory for Trimmed Clips")
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

    thread = QThread(window)
    worker = VideoClipWorker(clips)
    window._video_clip_jobs[thread] = worker
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(window._on_video_clip_finished)
    worker.error.connect(window._on_video_clip_error)
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)
    # No `worker.deleteLater` here: these signals are emitted in the
    # worker thread, where the worker also lives, so the connection is
    # direct and ~QObject runs inside that thread — severing connections
    # while holding one of Qt's pooled signal/slot mutexes and then
    # taking the GIL for PySide's disconnectNotify, which deadlocks a UI
    # thread holding the GIL and waiting on a colliding mutex (D-062).
    # The owning registry drops its reference on the UI thread instead.
    thread.finished.connect(window._on_video_clip_thread_finished)
    window.transport.set_status("Exporting video clip", "busy")
    thread.start()


def on_video_clip_finished(window: MainWindow, successful: int, total: int) -> None:
    """Show ffmpeg trim results once all worker jobs finish."""
    if successful == total:
        window.transport.set_status("Video clip export complete")
        QMessageBox.information(window, "Export Complete", f"Exported {successful} clips.")
    else:
        window.transport.set_status("Video clip export incomplete", "error")
        QMessageBox.warning(window, "Export Incomplete", f"Exported {successful} of {total} clips.")


def on_video_clip_error(window: MainWindow, error: str) -> None:
    """Show an ffmpeg worker failure on the UI thread."""
    window.transport.set_status("Video clip export failed", "error")
    QMessageBox.critical(window, "Export Failed", error)


def on_video_clip_thread_finished(window: MainWindow) -> None:
    """Release ownership of a completed ffmpeg worker."""
    thread = window.sender()
    if isinstance(thread, QThread):
        window._video_clip_jobs.pop(thread, None)
        thread.deleteLater()
