"""Background workers for cached-data export and A/B-region statistics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.edit_cache import GenerationPin, pin_reader_directory
from avialsync.core.errors import AvialSyncError, CacheError
from avialsync.core.pyramid import PyramidReader
from avialsync.core.timeline import TimeMap
from avialsync.engine.export import (
    compute_region_stats,
    export_data_slice_csv,
    export_data_slice_parquet,
    trim_video_clip,
)
from avialsync.engine.snapshot import SnapshotFigure, save_figure


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
    ) -> None:
        super().__init__()
        self._readers = readers
        self._t0 = t0
        self._t1 = t1
        self._path = path
        self._session = session

    @Slot()
    def run(self) -> None:
        """Open worker-local readers and persist the requested range."""
        try:
            readers = [reference.open() for reference in self._readers]
            if self._path.suffix.lower() == ".parquet":
                output = export_data_slice_parquet(
                    readers, self._t0, self._t1, self._path, session=self._session
                )
            else:
                export_data_slice_csv(
                    readers, self._t0, self._t1, self._path, session=self._session
                )
                output = self._path
            self.finished.emit(str(output))
        except (AvialSyncError, OSError, RuntimeError, ValueError) as error:
            self.error.emit(str(error))


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
            readers = [reference.open() for reference in self._readers]
            stats = compute_region_stats(readers, self._t0, self._t1)
            self.finished.emit(self._request_id, stats)
        except (AvialSyncError, OSError, RuntimeError, ValueError) as error:
            self.error.emit(self._request_id, str(error))


class VideoClipWorker(QObject):
    """Run ffmpeg clipping jobs outside the Qt event loop."""

    finished = Signal(int, int)  # successful, total
    error = Signal(str)

    def __init__(self, clips: list[tuple[str, float, float, Path]]) -> None:
        super().__init__()
        self._clips = clips

    @Slot()
    def run(self) -> None:
        """Trim every requested clip sequentially without blocking UI input."""
        try:
            successful = sum(
                trim_video_clip(video_path, t0, t1, output_path)
                for video_path, t0, t1, output_path in self._clips
            )
            self.finished.emit(successful, len(self._clips))
        except (AvialSyncError, OSError, RuntimeError, ValueError) as error:
            self.error.emit(str(error))


class SnapshotWorker(QObject):
    """Compose and encode a captured snapshot figure off the Qt event loop.

    The figure arrives fully captured: laying it out and painting it can cost
    tens of milliseconds at a multi-camera figure's size, which is well past
    what the UI thread may spend (AGENTS rule 3).
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
