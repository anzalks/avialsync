"""A minimal external AvialSync Plugin API v1 implementation."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.source import ChannelInfo, TimeSeriesSource


class ToyBinarySource(TimeSeriesSource):
    """Read ``.toybin`` records encoded as little-endian ``(time, value)`` pairs."""

    _dtype = np.dtype([("time", "<f8"), ("value", "<f8")])

    def __init__(self) -> None:
        self._path: Path | None = None

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Recognise the example file extension without opening the input."""
        return 1.0 if path.suffix.lower() == ".toybin" else 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        """Store the path after validating whole-record alignment."""
        if path.stat().st_size % self._dtype.itemsize:
            raise ValueError("Toy binary data must contain complete time/value records.")
        self._path = path

    def channels(self) -> list[ChannelInfo]:
        """Expose the single dimensionless signal channel."""
        return [ChannelInfo(name="value", unit="", dtype="float64", rate_hz=None)]

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield fixed-size, chronologically ordered chunks."""
        if ch != "value":
            raise KeyError(ch)
        if self._path is None:
            raise RuntimeError("Source not opened")
        records = np.memmap(self._path, dtype=self._dtype, mode="r")
        for start in range(0, len(records), 100_000):
            chunk = records[start : start + 100_000]
            times = np.asarray(chunk["time"], dtype=np.float64)
            values = np.asarray(chunk["value"], dtype=np.float64)
            if len(times) > 1 and np.any(np.diff(times) <= 0):
                raise ValueError("Toy binary timestamps must be strictly increasing.")
            yield times, values
