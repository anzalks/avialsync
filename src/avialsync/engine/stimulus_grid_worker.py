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


def _iter_continuous_segments(
    reader: object,
    cancel: threading.Event,
    falling_edge: bool,
    on_samples: object,
) -> Iterator[Iterator[tuple[np.ndarray, np.ndarray]]]:
    """Yield one chunk iterator per gap-free segment so mid-gap jumps never fake edges."""
    carry_t: list[np.ndarray] = []
    carry_v: list[np.ndarray] = []
    with_gaps = getattr(reader, "iter_raw_chunks_with_gaps", None)
    raw_iter = (
        with_gaps()
        if callable(with_gaps)
        else ((t, v, np.zeros(len(t), dtype=bool)) for t, v in reader.iter_raw_chunks())  # type: ignore[attr-defined]
    )
    for times, values, gaps in raw_iter:
        if cancel.is_set():
            raise TranscodeCancelled
        if callable(on_samples):
            on_samples(len(times))
        if len(times) == 0:
            continue
        scaled = -np.asarray(values, dtype=np.float64) if falling_edge else values
        gap_arr = np.asarray(gaps, dtype=bool)
        # Drop non-finite samples as segment breaks too so NaN runs reset edge state.
        if np.issubdtype(scaled.dtype, np.floating):
            nonfinite = ~np.isfinite(scaled)
            if np.any(nonfinite):
                gap_arr = gap_arr | nonfinite
        breaks = np.flatnonzero(gap_arr)
        if len(breaks) == 0:
            carry_t.append(times)
            carry_v.append(scaled)
            continue
        start = 0
        for brk in breaks.tolist():
            end = brk + 1
            seg_t, seg_v = times[start:end], scaled[start:end]
            if np.issubdtype(seg_v.dtype, np.floating) and not np.isfinite(seg_v[-1]):
                seg_t, seg_v = seg_t[:-1], seg_v[:-1]
            if len(seg_t):
                carry_t.append(seg_t)
                carry_v.append(seg_v)
            if carry_t:
                seg_chunks = list(zip(carry_t, carry_v, strict=True))
                carry_t, carry_v = [], []
                yield iter(seg_chunks)
            start = end
        if start < len(times):
            carry_t.append(times[start:])
            carry_v.append(scaled[start:])
    if carry_t:
        yield iter(list(zip(carry_t, carry_v, strict=True)))


class StimulusEventScanWorker(QObject):
    """Find threshold crossings without reading cached samples on the UI thread."""

    finished = Signal(object)
    error = Signal(str)
    cancelled = Signal()
    progress = Signal(int)

    def __init__(
        self,
        reference: ReaderReference,
        threshold: float,
        min_interval: float,
        *,
        falling_edge: bool = False,
    ) -> None:
        super().__init__()
        self._reference = reference
        self._threshold = threshold
        self._min_interval = min_interval
        self._falling_edge = bool(falling_edge)
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
            sign = -1.0 if self._falling_edge else 1.0

            def _report(count: int) -> None:
                nonlocal processed
                processed += count
                self.progress.emit(min(100, round(processed * 100 / sample_count)))

            detected: list[float] = []
            last_time = -np.inf
            for segment in _iter_continuous_segments(
                reader, self._cancel, self._falling_edge, _report
            ):
                train = extract_pulses(
                    segment,
                    source_id=self._reference.channel_id,
                    kind=TriggerKind.SPARSE_EVENTS,
                    threshold=sign * self._threshold,
                    min_interval=self._min_interval,
                )
                for ev_time in train.times:
                    t_val = float(ev_time)
                    if t_val - last_time >= self._min_interval:
                        detected.append(t_val)
                        last_time = t_val
        except TranscodeCancelled:
            self.cancelled.emit()
            return
        except (AvialSyncError, av.FFmpegError, OSError, RuntimeError, ValueError) as error:
            self.error.emit(str(error))
            return
        self.finished.emit(tuple(detected))


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
        sources: tuple[Path, ...] = (),
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
        self._sources = sources
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Request cancellation between rendered output frames."""
        self._cancel.set()

    def _destination_is_source(self) -> bool:
        from avialsync.engine.transcode import expanded_media_sources

        destination = self._destination.resolve()
        candidates: list[Path] = list(self._sources)
        for video in self._videos:
            candidates.extend(expanded_media_sources(video.path))
        for src_path in candidates:
            if destination == src_path.resolve():
                return True
            if self._destination.exists() and src_path.exists():
                if self._destination.samefile(src_path):
                    return True
        return False

    @Slot()
    def run(self) -> None:
        from avialsync.core.cache import cache_root

        temporary: Path | None = None
        replaced = False
        try:
            if self._destination_is_source():
                raise ExportError("Choose an output file separate from the source videos.")
            if self._destination.resolve().is_relative_to(cache_root().resolve()):
                raise ExportError("Choose a destination outside the disposable cache")
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
