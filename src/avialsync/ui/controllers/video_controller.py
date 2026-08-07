"""Video probing and pane construction.

Files are probed concurrently — metadata and presentation-timestamp extraction
are independent per file — but panes are still built one at a time, in the order
the user asked for them (D-040).

The original reason for serialising was libmpv: a client had to accept commands
on one pane before the next was constructed. That constraint is gone with D-075,
since a pane is now an ordinary widget plus its own decode thread. The order is
kept because it is also what makes panes appear in the order the user picked
them, which is user-visible; lifting the serialisation is a separate change with
its own DECISIONS entry, not a side effect of the decoder migration.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QMessageBox

from avialsync.core.inspection import SourceInspection
from avialsync.core.source import VideoSource
from avialsync.core.timeline import TimeMap

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

#: Concurrent ffprobe metadata/timestamp probes.  Bounded because each one
#: spawns a subprocess and reads from the same disk; unbounded fan-out on a
#: 32-camera session would thrash rather than parallelise.
MAX_VIDEO_PROBES = 3


def load_video(
    window: MainWindow,
    path: Path,
    offset: float = 0.0,
    drift_ppm: float = 0.0,
    config: dict[str, Any] | None = None,
) -> None:
    """Queue a video source for probing and, in request order, pane creation."""
    window._pending_video_loads.append((path, offset, drift_ppm, config))
    window._video_request_order.append(str(path))
    window._start_next_video_load()


def start_next_video_load(window: MainWindow) -> None:
    """Start probes up to the concurrency bound; pane creation stays serialized.

    Two different limits apply here (P3.5 P1 loading).  ffprobe metadata and
    presentation-timestamp extraction are independent per file and safe to
    overlap, so up to :data:`MAX_VIDEO_PROBES` run at once and a four-camera
    session stops paying four serial probe latencies.  Pane construction stays
    one at a time, gated by ``_video_pane_initializing``, so panes appear in the
    order the user picked them (D-040; see the module docstring for why the
    original libmpv reason no longer applies).
    """
    while len(window._video_load_jobs) < MAX_VIDEO_PROBES and window._pending_video_loads:
        window._start_one_video_probe()


def start_one_video_probe(window: MainWindow) -> None:
    """Spawn a single off-thread metadata/timestamp probe."""
    from avialsync.engine.video_worker import VideoOpenWorker

    path, offset, drift_ppm, config = window._pending_video_loads.popleft()
    thread = QThread(window)
    worker = VideoOpenWorker(path, config)
    window._video_load_jobs[thread] = worker
    window._video_load_offsets[str(path)] = offset
    window._video_load_drifts[str(path)] = drift_ppm
    remaining = len(window._pending_video_loads)
    suffix = f" ({remaining} queued)" if remaining else ""
    window.transport.set_status(f"Loading video: {path.name}{suffix}", "busy")
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    # These QObject slots are queued onto MainWindow's UI thread.  Do not
    # replace them with lambdas: a lambda runs in the emitting worker thread
    # and would create widgets off-thread.
    worker.opened.connect(window._on_video_opened)
    worker.error.connect(window._on_video_open_error)
    worker.opened.connect(thread.quit)
    worker.error.connect(thread.quit)
    worker.cancelled.connect(thread.quit)
    # `_on_video_thread_finished` drops the registry's reference, which is
    # the worker's only owner, so it is destroyed on the UI thread as that
    # slot promises. A `thread.finished.connect(worker.deleteLater)` here
    # would beat it: `finished` is emitted in the worker thread and the
    # worker lives there, making that connection direct and running
    # ~QObject inside the dying thread — where severing connections holds
    # one of Qt's pooled signal/slot mutexes and PySide's disconnectNotify
    # then blocks on the GIL, deadlocking the UI thread (D-062).
    thread.finished.connect(window._on_video_thread_finished)
    thread.start()


def set_video_coverage(
    window: MainWindow,
    path: str,
    source_bounds: tuple[float, float],
    offset: float,
    drift_ppm: float,
    exact_master: np.ndarray | None = None,
    exact_source: np.ndarray | None = None,
) -> None:
    """Project media bounds through its TimeMap before drawing master-time coverage."""
    if exact_master is not None and exact_source is not None and len(exact_master) >= 2:
        master_bounds = (float(exact_master[0]), float(exact_master[-1]))
    else:
        mapping = TimeMap(offset, drift_ppm)
        master_bounds = (
            mapping.to_master(source_bounds[0]),
            mapping.to_master(source_bounds[1]),
        )
    window._video_source_bounds[path] = source_bounds
    window._video_time_mappings[path] = (offset, drift_ppm)
    window._update_bounds(*master_bounds)
    window.transport.set_source_coverage(path, *master_bounds, "video")


def on_video_opened(
    window: MainWindow, original_path: str, loader: object, media_path: str
) -> None:
    """Hold the probe result until this file's turn to build a native pane.

    Probes finish out of order because they run concurrently.  Panes are
    still built one at a time, in the order the user asked for them, so the
    grid layout does not depend on which file happened to probe fastest.
    """
    window._probed_videos[original_path] = (loader, media_path)
    if original_path not in window._video_request_order:
        # Opened outside the queue (session restore, direct call): it still
        # takes its turn, appended at the end of the current order.
        window._video_request_order.append(original_path)
    window._build_next_video_pane()


def build_next_video_pane(window: MainWindow) -> None:
    """Build the next pane in request order, if one is ready and none is busy."""
    while window._video_pane_initializing is None and window._video_request_order:
        next_path = window._video_request_order[0]
        probed = window._probed_videos.pop(next_path, None)
        if probed is None:
            return  # Still probing; a later completion will call back here.
        window._video_request_order.pop(0)
        loader, media_path = probed
        window._create_video_pane(next_path, loader, media_path)


def _declared_exact_mapping(loader: VideoSource, path: str) -> tuple[np.ndarray, np.ndarray] | None:
    """Return per-frame timing the loader recorded, once it has been validated.

    A source that knows when each of its frames was exposed — from a timestamp
    sidecar or a trigger log — maps to master time piecewise, and no offset and
    drift pair can express that once frames have been dropped.  The contract is
    checked here rather than trusted: this arrives from a plugin, and a mapping
    that is not strictly increasing would corrupt every seek made through it.
    """
    try:
        mapping = loader.exact_time_mapping()
    except Exception:  # noqa: BLE001 - plugin boundary
        logger.warning("%s.exact_time_mapping failed", type(loader).__name__, exc_info=True)
        return None
    if mapping is None:
        return None

    master, source = (np.asarray(values, dtype=np.float64) for values in mapping)
    if master.ndim != 1 or source.ndim != 1 or len(master) != len(source) or len(master) < 2:
        logger.warning("%s: exact time mapping is not a pair of equal-length series.", path)
        return None
    if not (np.all(np.isfinite(master)) and np.all(np.isfinite(source))):
        logger.warning("%s: exact time mapping contains non-finite times.", path)
        return None
    if np.any(np.diff(master) <= 0) or np.any(np.diff(source) <= 0):
        logger.warning("%s: exact time mapping is not strictly increasing.", path)
        return None
    logger.info(
        "%s: using %d declared frame times spanning %.3f s of master time.",
        path,
        len(master),
        float(master[-1] - master[0]),
    )
    return master, source


def create_video_pane(
    window: MainWindow, original_path: str, loader: object, media_path: str
) -> None:
    """Create UI state only after asynchronous source opening succeeds."""
    offset = window._video_load_offsets.pop(original_path, 0.0)
    drift_ppm = window._video_load_drifts.pop(original_path, 0.0)
    exact_mapping = window._pending_exact_mappings.pop(original_path, None)
    if not isinstance(loader, VideoSource):
        window._on_video_open_error(original_path, "Selected loader is not a VideoSource.")
        return
    if exact_mapping is None:
        # A restored or accepted proposal outranks the loader's own evidence: the
        # user agreed to that mapping, and silently replacing it with what the
        # container's sidecar claims would undo an explicit decision.
        exact_mapping = _declared_exact_mapping(loader, original_path)
    exact_master = exact_mapping[0] if exact_mapping is not None else None
    exact_source = exact_mapping[1] if exact_mapping is not None else None
    bounds = loader.time_bounds()
    window._set_video_coverage(
        original_path,
        bounds,
        offset,
        drift_ppm,
        exact_master,
        exact_source,
    )
    window._video_pane_initializing = original_path
    pane = window.video_grid.add_pane(
        original_path,
        media_path=media_path,
        on_file_loaded=window._on_video_pane_ready,
    )
    video_metadata = loader.video_metadata()
    metadata = {
        "codec": video_metadata.codec,
        "fps": video_metadata.nominal_fps,
        "measured_fps": video_metadata.measured_fps,
        "is_vfr": video_metadata.is_vfr,
        "duration": video_metadata.duration,
        "file_size_bytes": video_metadata.file_size_bytes,
    }
    window.sidebar.add_video(original_path, metadata)
    window.sidebar.set_video_loader(original_path, loader)
    window.sidebar.set_video_pane(original_path, pane)
    if offset or drift_ppm or exact_mapping is not None:
        window.video_grid.set_sync_mapping(
            original_path,
            offset,
            drift_ppm,
            exact_master,
            exact_source,
        )
    window._video_fps[original_path] = loader.fps()
    frame_times = loader.frame_times()
    pane.set_frame_times(frame_times)
    pane.set_video_metadata(video_metadata)
    pane.set_source_bounds(bounds)
    is_vfr = video_metadata.is_vfr
    pane.set_vfr(is_vfr)
    # The pane is added asynchronously, after the current master-time seek
    # may already have run. Synchronize it now so paused media decodes its
    # first visible frame and availability reflects the active timeline.
    window.player.seek(window.clock.state.t, exact=True)
    from avialsync.core.inspection import IntegrityFlags

    inspection = SourceInspection(
        path=original_path,
        loader_id=type(loader).__name__,
        integrity_flags=IntegrityFlags(
            is_vfr=is_vfr,
            drift_nonzero=bool(drift_ppm),
            frames_dropped=video_metadata.dropped_frames > 0,
        ),
    )
    window._inspections[original_path] = inspection
    window.sidebar.set_video_inspection(original_path, inspection)
    if frame_times is not None:
        window._video_frame_times[original_path] = frame_times
    if window._frame_indexed_sources and len(window._video_fps) == 1:
        window._rebind_frame_indexed_sources(loader.fps())
    window.transport.set_status(f"Ready · loaded {Path(original_path).name}")


def on_video_open_error(window: MainWindow, path: str, error: str) -> None:
    """Show a source-open error without leaving a partially-created pane."""
    window._video_load_offsets.pop(path, None)
    window._video_load_drifts.pop(path, None)
    window._probed_videos.pop(path, None)
    # Drop the failed file from the ordering so later files still get built.
    if path in window._video_request_order:
        window._video_request_order.remove(path)
    window.transport.set_status(f"Video failed: {Path(path).name}", "error")
    QMessageBox.critical(window, "Video Error", f"Could not open video:\n{path}\n\n{error}")
    window._build_next_video_pane()


def on_video_thread_finished(window: MainWindow) -> None:
    """Release the worker ownership after its thread has stopped on the UI thread."""
    thread = window.sender()
    if isinstance(thread, QThread):
        window._video_load_jobs.pop(thread, None)
        thread.deleteLater()
        QTimer.singleShot(0, window._start_next_video_load)


def on_video_pane_ready(window: MainWindow) -> None:
    """Build the next pane only after this one accepts media commands (D-040)."""
    window._video_pane_initializing = None
    window._build_next_video_pane()
    window._start_next_video_load()
