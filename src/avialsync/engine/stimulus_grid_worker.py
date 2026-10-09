"""Registered background jobs for stimulus event scanning and grid export."""

from __future__ import annotations

import logging
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import av
import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.errors import AvialSyncError, ExportError
from avialsync.core.triggers import TriggerKind, extract_pulses
from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.stimulus_grid_export import (
    GridBand,
    GridLabels,
    GridSignal,
    export_stimulus_grid,
)
from avialsync.engine.stimulus_grid_layout import GridRow
from avialsync.engine.transcode import TranscodeCancelled

logger = logging.getLogger(__name__)


class StimulusTimelineWorker(QObject):
    """Fetch the bounded overview pyramid without cold-cache I/O on the UI."""

    finished = Signal(int, object)
    error = Signal(int, str)

    def __init__(self, index: int, reference: ReaderReference) -> None:
        super().__init__()
        self._index = index
        self._reference = reference

    @Slot()
    def run(self) -> None:
        """Return arrays owned by this result, independent of worker-local mmaps."""
        try:
            reader = self._reference.open()
            bounds = reader.coverage()
            if bounds is None or bounds[1] <= bounds[0]:
                result = None
            else:
                result = (
                    bounds,
                    *(np.asarray(part).copy() for part in reader.query(*bounds, max_points=1200)),
                )
            self.finished.emit(self._index, result)
        except (AvialSyncError, OSError, RuntimeError, ValueError) as error:
            self.error.emit(self._index, str(error))


class StimulusEventScanWorker(QObject):
    """Find threshold crossings without reading cached samples on the UI thread."""

    finished = Signal(object)
    error = Signal(str)
    cancelled = Signal()
    progress = Signal(int)

    def __init__(self, reference: ReaderReference, threshold: float, min_interval: float) -> None:
        super().__init__()
        self._reference = reference
        self._threshold = threshold
        self._min_interval = min_interval
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Request cancellation between cached sample chunks."""
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        try:
            reader = self._reference.open()
            sample_count = max(1, reader.sample_count())
            processed = 0

            def chunks() -> Iterator[tuple[np.ndarray, np.ndarray]]:
                nonlocal processed
                for times, values in reader.iter_raw_chunks():
                    if self._cancel.is_set():
                        raise TranscodeCancelled
                    processed += len(times)
                    self.progress.emit(min(100, round(processed * 100 / sample_count)))
                    yield times, values

            train = extract_pulses(
                chunks(),
                source_id=self._reference.channel_id,
                kind=TriggerKind.SPARSE_EVENTS,
                threshold=self._threshold,
                min_interval=self._min_interval,
            )
        except TranscodeCancelled:
            self.cancelled.emit()
            return
        except (AvialSyncError, av.FFmpegError, OSError, RuntimeError, ValueError) as error:
            self.error.emit(str(error))
            return
        self.finished.emit(tuple(float(time) for time in train.times))


class StimulusGridExportWorker(QObject):
    """Render and atomically publish the selected event-aligned video grid."""

    finished = Signal(str, bool)
    error = Signal(str)
    cancelled = Signal()
    progress = Signal(int)

    def __init__(
        self,
        videos: tuple[GridRow, ...],
        event_times: tuple[float, ...],
        before: float,
        after: float,
        destination: Path,
        fps: int,
        labels: GridLabels,
        signal: GridSignal | None = None,
        playback_speed: float = 1.0,
        high_detail: bool = False,
        bands: tuple[GridBand, ...] = (),
    ) -> None:
        super().__init__()
        self._bands = bands
        self._videos = videos
        self._event_times = event_times
        self._before = before
        self._after = after
        self._destination = destination
        self._fps = fps
        self._labels = labels
        self._signal = signal
        self._playback_speed = playback_speed
        self._high_detail = high_detail
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Request cancellation between rendered output frames."""
        self._cancel.set()

    def _destination_is_source(self) -> bool:
        destination = self._destination.resolve()
        for video in self._videos:
            if destination == video.path.resolve():
                return True
            if self._destination.exists() and video.path.exists():
                if self._destination.samefile(video.path):
                    return True
        return False

    @Slot()
    def run(self) -> None:
        temporary: Path | None = None
        replaced = False
        try:
            if self._destination_is_source():
                raise ExportError("Choose an output file separate from the source videos.")
            self._destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                prefix=f"{self._destination.stem}.exporting.",
                suffix=f".part{self._destination.suffix or '.mp4'}",
                dir=self._destination.parent,
                delete=False,
            ) as output:
                temporary = Path(output.name)

            export_stimulus_grid(
                self._videos,
                self._event_times,
                self._before,
                self._after,
                temporary,
                self._labels,
                fps=self._fps,
                playback_speed=self._playback_speed,
                signal=self._signal,
                bands=self._bands,
                high_detail=self._high_detail,
                progress=lambda value: self.progress.emit(round(value * 100)),
                should_cancel=self._cancel.is_set,
            )
            if self._cancel.is_set():
                self.cancelled.emit()
                return
            replaced = self._destination.exists()
            temporary.replace(self._destination)
        except TranscodeCancelled:
            self.cancelled.emit()
            return
        except Exception as error:  # noqa: BLE001 - worker boundary must report every job failure
            logger.exception("Stimulus grid export failed")
            self.error.emit(str(error) or "Unexpected failure while encoding the stimulus grid.")
            return
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    logger.warning(
                        "Could not remove temporary grid export %s", temporary, exc_info=True
                    )
        self.finished.emit(str(self._destination), replaced)
