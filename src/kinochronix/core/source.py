"""Source plugin abstract base classes."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

ChannelSlice = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]


@dataclass
class ChannelInfo:
    """Metadata for a single data channel."""

    name: str
    unit: str
    dtype: str
    rate_hz: float | None  # None indicates irregular sampling


class TimeSeriesSource(ABC):
    """Plugin contract for time series data sources."""

    @classmethod
    @abstractmethod
    def can_open(cls, path: Path) -> float:
        """Return 0..1 confidence that this loader can open the file."""
        pass

    @abstractmethod
    def open(self, path: Path, config: dict[str, Any]) -> None:
        """Open the source with the given configuration."""
        pass

    @abstractmethod
    def channels(self) -> list[ChannelInfo]:
        """Return metadata for all available channels."""
        pass

    @abstractmethod
    def time_bounds(self) -> tuple[float, float]:
        """Return the absolute UTC bounds (start, end) in seconds."""
        pass

    @abstractmethod
    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """
        Yield (t, v) chunks in time order.
        Must sort non-monotonic input or raise NonMonotonicTimeError.
        """
        pass

    @abstractmethod
    def read(self, ch: str, t0: float, t1: float, max_points: int) -> ChannelSlice:
        """Serve from pyramid/cache returning (t, vmin, vmax, gap_mask)."""
        pass

    @abstractmethod
    def config_widget(self) -> Any | None:
        """Optional import-config UI hook. Returns QWidget or None."""
        pass


class VideoSource(ABC):
    """Plugin contract for video sources."""

    @classmethod
    @abstractmethod
    def can_open(cls, path: Path) -> float:
        """Return 0..1 confidence that this loader can open the file."""
        pass

    @abstractmethod
    def open(self, path: Path, config: dict[str, Any]) -> None:
        """Open the source with the given configuration."""
        pass

    @abstractmethod
    def needs_conversion(self) -> bool:
        """Return True if this source needs proxy conversion (e.g., image seq)."""
        pass

    @abstractmethod
    def prepare(self, progress_cb: Callable[[float], None]) -> Path:
        """Produce an mpv-playable file (proxy), return the cached sidecar path."""
        pass

    @abstractmethod
    def media_path(self) -> Path:
        """Return what mpv actually plays (proxy-aware)."""
        pass

    @abstractmethod
    def start_time(self) -> float | None:
        """Metadata guess ONLY; defaults to offset 0 in UI."""
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
