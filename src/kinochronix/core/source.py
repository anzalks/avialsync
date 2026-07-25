"""Source plugin abstract base classes."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class ChannelInfo:
    """Metadata for a single data channel."""

    name: str
    unit: str
    dtype: str
    rate_hz: float | None  # None indicates irregular sampling


class TimeSeriesSource(ABC):
    """Frozen v1 plugin contract for chunked time-series ingestion.

    Instances are created and used by :class:`engine.importer.ImportWorker` on a
    background thread.  Implementations must not retain Qt objects.  The importer
    owns cache construction, decimation, gap detection, and all subsequent reads.
    """

    @classmethod
    @abstractmethod
    def can_open(cls, path: Path) -> float:
        """Return a confidence in ``[0.0, 1.0]`` without expensive I/O."""
        pass

    @abstractmethod
    def open(self, path: Path, config: dict[str, Any]) -> None:
        """Read metadata required for :meth:`channels` and :meth:`read_chunks`.

        ``config`` is plugin-defined, JSON-serialisable import configuration.
        Raise a typed source error with actionable context when it cannot be read.
        """
        pass

    @abstractmethod
    def channels(self) -> list[ChannelInfo]:
        """Return stable metadata for every importable channel."""
        pass

    @abstractmethod
    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield one-dimensional ``float64`` time/value chunks for *ch*.

        Chunks, including their boundaries, must be globally chronological.
        Duplicate timestamps must keep the final value.  A loader may sort its
        input or raise :class:`NonMonotonicTimeError`; it must never silently emit
        decreasing times.  NaN and infinity values pass through.  Core computes
        gaps after ingest using a 10× median-sample-interval threshold.
        """
        pass

    def is_frame_indexed(self) -> bool:
        """Return True if this source stores frame numbers instead of wall-clock time.

        Frame-indexed sources require an explicit fps to convert frame indices to seconds.
        The UI uses this flag to drive automatic fps resolution from loaded video (D-019).
        Default False; loaders that store raw frame counters should override to return True.
        """
        return False


class VideoSource(ABC):
    """Frozen v1 plugin contract for video sources.

    ``open`` and optional ``prepare`` run in a background worker.  The returned
    media path is opened by mpv only after this work has completed successfully.
    """

    @classmethod
    @abstractmethod
    def can_open(cls, path: Path) -> float:
        """Return 0..1 confidence that this loader can open the file."""
        pass

    @abstractmethod
    def open(self, path: Path, config: dict[str, Any]) -> None:
        """Probe source metadata; this method may perform blocking I/O."""
        pass

    @abstractmethod
    def needs_conversion(self) -> bool:
        """Return True if this source needs proxy conversion (e.g., image seq)."""
        pass

    @abstractmethod
    def prepare(self, progress_cb: Callable[[float], None]) -> Path:
        """Produce an mpv-playable cached proxy and report progress in ``[0, 1]``."""
        pass

    @abstractmethod
    def media_path(self) -> Path:
        """Return what mpv actually plays (proxy-aware)."""
        pass

    @abstractmethod
    def start_time(self) -> float | None:
        """Return an optional UTC-epoch metadata guess; user offset always wins."""
        pass

    @abstractmethod
    def time_bounds(self) -> tuple[float, float]:
        """Return source coverage in master-time seconds.

        Sources with a metadata start return ``(start_time, start_time + duration)``;
        sources without one return media-relative ``(0.0, duration)``.
        """
        pass

    @abstractmethod
    def frame_times(self) -> np.ndarray | None:
        """Per-frame timestamps if the container has them."""
        pass

    @abstractmethod
    def fps(self) -> float:
        """Nominal frames per second."""
        pass

    @abstractmethod
    def label(self) -> str:
        """Camera label for the UI."""
        pass
