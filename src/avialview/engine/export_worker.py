"""Background workers for cached-data export and A/B-region statistics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

from avialview.core.channel_reader import MappedChannelReader
from avialview.core.pyramid import PyramidReader
from avialview.core.timeline import TimeMap
from avialview.engine.export import (
    compute_region_stats,
    export_data_slice_csv,
    export_data_slice_parquet,
    save_snapshot_images,
    trim_video_clip,
)
from avialview.ui.annotations import Marker


class AnnotationExportWorker(QObject):
    """Export annotation markers to CSV off the UI thread."""

    finished = Signal(Path, int)  # path, count
    error = Signal(str)

    def __init__(self, markers: list[Marker], path: Path) -> None:
        super().__init__()
        import copy

        self._markers = copy.deepcopy(markers)
        self._path = path

    @Slot()
    def run(self) -> None:
        import csv

        try:
            with open(self._path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["label", "comment", "t_master", "video_path", "frame_index", "media_timestamp"]
                )
                for m in self._markers:
                    if m.video_frames:
                        for vf in m.video_frames:
                            writer.writerow(
                                [
                                    m.label,
                                    "",
                                    m.t_start,
                                    vf.path,
                                    vf.frame_index,
                                    vf.media_timestamp,
                                ]
                            )
                    else:
                        writer.writerow([m.label, "", m.t_start, "", "", ""])
            self.finished.emit(self._path, len(self._markers))
        except Exception as e:
            self.error.emit(str(e))


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
    drift_ppm: float = 0.0

    def open(self) -> MappedChannelReader:
        """Open a fresh mmap reader owned by the calling thread."""
        return MappedChannelReader(
            PyramidReader(self.cache_dir, self.channel_id),
            TimeMap(self.offset, self.drift_ppm),
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
    ) -> None:
        super().__init__()
        self._readers = readers
        self._t0 = t0
        self._t1 = t1
        self._path = path

    @Slot()
    def run(self) -> None:
        """Open worker-local readers and persist the requested range."""
        try:
            readers = [reference.open() for reference in self._readers]
            if self._path.suffix.lower() == ".parquet":
                export_data_slice_parquet(readers, self._t0, self._t1, self._path)
            else:
                export_data_slice_csv(readers, self._t0, self._t1, self._path)
            self.finished.emit(str(self._path))
        except (OSError, RuntimeError, ValueError) as error:
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
        except (OSError, RuntimeError, ValueError) as error:
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
        except (OSError, RuntimeError, ValueError) as error:
            self.error.emit(str(error))


class SnapshotWorker(QObject):
    """Encode UI-captured images without blocking the Qt event loop."""

    finished = Signal(str)
    error = Signal(str)

    def __init__(self, video_image: QImage | None, plot_image: QImage | None, path: Path) -> None:
        super().__init__()
        self._video_image = video_image
        self._plot_image = plot_image
        self._path = path

    @Slot()
    def run(self) -> None:
        """Compose and save the immutable image copies on this worker thread."""
        try:
            save_snapshot_images(self._video_image, self._plot_image, self._path)
            self.finished.emit(str(self._path))
        except OSError as error:
            self.error.emit(str(error))
