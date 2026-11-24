"""Background workers for cached-data export and A/B-region statistics."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.edit_cache import GenerationPin, pin_reader_directory
from avialsync.core.errors import AvialSyncError, CacheError
from avialsync.core.pyramid import RAW_CHUNK_SAMPLES, PyramidReader
from avialsync.core.session import SyncProvenance
from avialsync.core.timeline import TimeMap
from avialsync.engine.export import (
    compute_region_stats,
    export_data_slice_csv,
    export_data_slice_parquet,
    trim_video_clip,
)
from avialsync.engine.snapshot import SnapshotFigure, save_figure

_MAX_SIMULTANEOUS_EXPORT_READERS = 64


def _close_reader(reader: object) -> None:
    """Release any underlying PyramidReader mmaps and generation pins."""
    close = getattr(reader, "close", None)
    if callable(close):
        close()
        return
    source_reader = getattr(reader, "source_reader", None)
    source_close = getattr(source_reader, "close", None)
    if callable(source_close):
        source_close()


@dataclass(frozen=True)
class ReaderReference:
    """The stable information needed to open one mapped reader in a worker.

    The source's accepted offset/drift travel with the reference rather than the
    reader object, because a ``QThread`` worker must open its own mmaps.  Exports
    and statistics therefore report master time, matching what the user sees.
    """

    cache_dir: Path
    channel_id: str
    offset: float = 0.0
    drift_ms_per_hour: float = 0.0
    source_id: str = ""
    time_map: TimeMap | None = None
    _pin: GenerationPin | None = None
    _pinned_snapshot: bool = False

    @classmethod
    def from_reader(cls, reader: MappedChannelReader) -> ReaderReference:
        """Snapshot the displayed generation and its complete accepted clock."""
        directory = reader.source_reader.cache_dir
        return cls(
            directory,
            reader.channel_id,
            reader.time_map.offset,
            reader.time_map.drift_ms_per_hour,
            reader.source_id,
            reader.time_map.copy(),
            pin_reader_directory(directory),
            True,
        )

    def open(self) -> MappedChannelReader:
        """Open a fresh mmap reader owned by the calling thread."""
        if self._pinned_snapshot and (
            self._pin is None or self._pin.directory != self.cache_dir.absolute()
        ):
            raise CacheError("Cached reader is in use or unavailable; retry when the job finishes")
        mapping = (
            self.time_map.copy()
            if self.time_map is not None
            else TimeMap(self.offset, self.drift_ms_per_hour)
        )
        return MappedChannelReader(
            PyramidReader(self.cache_dir, self.channel_id),
            mapping,
            self.source_id,
        )


class _LazyExportReader:
    """Open and close one channel's mmap reader strictly around its chunk scan."""

    def __init__(self, reference: ReaderReference) -> None:
        if reference._pinned_snapshot and (
            reference._pin is None or reference._pin.directory != reference.cache_dir.absolute()
        ):
            raise CacheError("Cached reader is in use or unavailable; retry when the job finishes")
        self._reference = reference
        self.cache_dir = reference.cache_dir
        self.channel_id = reference.channel_id
        self.source_id = reference.source_id
        self.time_map = (
            reference.time_map.copy()
            if reference.time_map is not None
            else TimeMap(reference.offset, reference.drift_ms_per_hour)
        )
        self._active: MappedChannelReader | None = None

    def iter_raw_chunks_with_gaps(
        self,
        chunk_size: int = RAW_CHUNK_SAMPLES,
        t0: float | None = None,
        t1: float | None = None,
    ) -> Iterator[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        reader = self._reference.open()
        self._active = reader
        try:
            yield from reader.iter_raw_chunks_with_gaps(chunk_size, t0=t0, t1=t1)
        finally:
            self._active = None
            _close_reader(reader)

    def close(self) -> None:
        if self._active is not None:
            active, self._active = self._active, None
            _close_reader(active)


class DataExportWorker(QObject):
    """Write a requested data range without blocking the Qt event loop."""

    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        readers: list[ReaderReference],
        t0: float,
        t1: float,
        path: Path,
        session: Path | None = None,
        alignment_evidence: tuple[SyncProvenance, ...] = (),
    ) -> None:
        super().__init__()
        self._readers = readers
        self._t0 = t0
        self._t1 = t1
        self._path = path
        self._session = session
        self._alignment_evidence = alignment_evidence

    @Slot()
    def run(self) -> None:
        """Open worker-local readers and persist the requested range."""
        readers: list[object] = []
        try:
            if len(self._readers) > _MAX_SIMULTANEOUS_EXPORT_READERS:
                readers = [_LazyExportReader(reference) for reference in self._readers]
            else:
                readers = [reference.open() for reference in self._readers]
            if self._path.suffix.lower() == ".parquet":
                output = export_data_slice_parquet(
                    readers,
                    self._t0,
                    self._t1,
                    self._path,
                    session=self._session,
                    alignment_evidence=self._alignment_evidence,
                )
            else:
                export_data_slice_csv(
                    readers,
                    self._t0,
                    self._t1,
                    self._path,
                    session=self._session,
                    alignment_evidence=self._alignment_evidence,
                )
                output = self._path
            self.finished.emit(str(output))
        except (AvialSyncError, OSError, RuntimeError, ValueError) as error:
            self.error.emit(str(error))
        finally:
            for reader in readers:
                _close_reader(reader)


class RegionStatsWorker(QObject):
    """Calculate A/B-region statistics from worker-local pyramid readers."""

    finished = Signal(int, object)  # request id, list[dict[str, float | str]]
    error = Signal(int, str)

    def __init__(
        self,
        request_id: int,
        readers: list[ReaderReference],
        t0: float,
        t1: float,
    ) -> None:
        super().__init__()
        self._request_id = request_id
        self._readers = readers
        self._t0 = t0
        self._t1 = t1

    @Slot()
    def run(self) -> None:
        """Calculate region statistics and tag the result with its request id."""
        try:
            stats: list[dict[str, float | str]] = []
            for reference in self._readers:
                reader = reference.open()
                try:
                    stats.extend(compute_region_stats([reader], self._t0, self._t1))
                finally:
                    _close_reader(reader)
            self.finished.emit(self._request_id, stats)
        except (AvialSyncError, OSError, RuntimeError, ValueError) as error:
            self.error.emit(self._request_id, str(error))


class VideoClipWorker(QObject):
    """Run ffmpeg clipping jobs outside the Qt event loop."""

    finished = Signal(int, int)  # successful, total
    error = Signal(str)

    def __init__(
        self,
        clips: list[tuple[str, float, float, Path]],
        sources: tuple[Path, ...] = (),
    ) -> None:
        super().__init__()
        self._clips = clips
        self._sources = sources

    @Slot()
    def run(self) -> None:
        """Trim every requested clip sequentially without blocking UI input."""
        try:
            successful = sum(
                (
                    trim_video_clip(video_path, t0, t1, output_path, sources=self._sources)
                    if self._sources
                    else trim_video_clip(video_path, t0, t1, output_path)
                )
                for video_path, t0, t1, output_path in self._clips
            )
            self.finished.emit(successful, len(self._clips))
        except (AvialSyncError, OSError, RuntimeError, ValueError) as error:
            self.error.emit(str(error))


class SnapshotWorker(QObject):
    """Compose and encode a captured snapshot figure off the Qt event loop.

    The figure arrives fully captured: laying it out and painting it can cost
    tens of milliseconds at a multi-camera figure's size, which is well past
    what the UI thread may spend.
    """

    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        figure: SnapshotFigure,
        path: Path,
        sources: tuple[Path, ...] = (),
        session: Path | None = None,
    ) -> None:
        super().__init__()
        self._figure = figure
        self._path = path
        self._sources = sources
        self._session = session

    @Slot()
    def run(self) -> None:
        """Compose and save the immutable image copies on this worker thread."""
        try:
            save_figure(self._figure, self._path, sources=self._sources, session=self._session)
            self.finished.emit(str(self._path))
        except (AvialSyncError, OSError) as error:
            self.error.emit(str(error))
