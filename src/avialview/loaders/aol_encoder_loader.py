"""AOL Encoder Log Loader.

Parses MATLAB-generated encoder_log.txt files with space-separated columns:
    HH:MM:SS:mmm  counter  position  velocity

Only the velocity channel is imported. The wall-clock timestamp (column 0)
is used as the primary time axis with an anchor date for absolute time.
"""

import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from avialview.core.errors import NonMonotonicTimeError
from avialview.core.source import ChannelInfo, TimeSeriesSource

logger = logging.getLogger(__name__)

# Matches HH:MM:SS:mmm (MATLAB writes milliseconds after a colon)
_TIME_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2}):(\d{3})$")

_CHUNK_SIZE = 50_000


class AOLEncoderLoader(TimeSeriesSource):
    """Loads CSV files in chunks using polars.

    Format: space-separated, no header, 4 columns:
        wall-clock (HH:MM:SS:mmm)  counter  position  velocity
    """

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Return high confidence for files matching the encoder log pattern."""
        if path.is_dir():
            return 0.0

        # Fast name check first
        if path.name.lower() == "encoder_log.txt":
            return 0.95

        # Peek at first line for the pattern
        if path.suffix.lower() in (".txt", ".log"):
            try:
                with open(path, encoding="utf-8") as f:
                    line = f.readline().strip()
                parts = line.split()
                if len(parts) == 4 and _TIME_RE.match(parts[0]):
                    return 0.90
            except (OSError, UnicodeError):
                pass

        return 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        """Validate the file and store config."""
        self._path = path
        self._config = config

        # Validate first line
        with open(path, encoding="utf-8") as f:
            line = f.readline().strip()

        parts = line.split()
        if len(parts) < 4:
            raise ValueError(
                f"Expected 4 space-separated columns in encoder log, got {len(parts)}: {path}"
            )
        if not _TIME_RE.match(parts[0]):
            raise ValueError(f"First column does not match HH:MM:SS:mmm pattern: '{parts[0]}'")

    def channels(self) -> list[ChannelInfo]:
        """Return a single velocity channel."""
        return [
            ChannelInfo(name="encoder_velocity", unit="deg/s", dtype="Float64", rate_hz=None),
        ]

    @staticmethod
    def _parse_wall_clock(time_str: str) -> float:
        """Convert HH:MM:SS:mmm to seconds since midnight."""
        m = _TIME_RE.match(time_str)
        if m is None:
            return float("nan")
        h, mi, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return h * 3600.0 + mi * 60.0 + s + ms / 1000.0

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield (time, value) chunks for the requested channel."""
        if ch != "encoder_velocity":
            raise KeyError(f"Unknown encoder channel: {ch}")

        if self._path is None:
            raise RuntimeError("Source not opened")

        times: list[float] = []
        values: list[float] = []
        row_offset = 0

        with open(self._path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue

                parts = line.split()
                if len(parts) < 4:
                    logger.warning("Skipping malformed encoder line %d: %s", line_no, line[:60])
                    continue

                t_sec = self._parse_wall_clock(parts[0])
                if np.isnan(t_sec):
                    logger.warning("Unparseable timestamp at line %d: %s", line_no, parts[0])
                    continue

                try:
                    velocity = float(parts[3])
                except ValueError:
                    logger.warning("Unparseable velocity at line %d: %s", line_no, parts[3])
                    continue

                times.append(t_sec)
                values.append(velocity)

                if len(times) >= _CHUNK_SIZE:
                    t_arr = np.array(times, dtype=np.float64)
                    v_arr = np.array(values, dtype=np.float64)
                    self._validate_monotonic(t_arr, row_offset)
                    t_arr, v_arr = self._deduplicate(t_arr, v_arr)
                    if len(t_arr) > 0:
                        yield t_arr, v_arr
                    row_offset += len(times)
                    times.clear()
                    values.clear()

        # Flush remaining
        if times:
            t_arr = np.array(times, dtype=np.float64)
            v_arr = np.array(values, dtype=np.float64)
            self._validate_monotonic(t_arr, row_offset)
            t_arr, v_arr = self._deduplicate(t_arr, v_arr)
            if len(t_arr) > 0:
                yield t_arr, v_arr

    @staticmethod
    def _validate_monotonic(t: np.ndarray, row_offset: int) -> None:
        """Raise on backward time jumps (allowing duplicates for dedup)."""
        if len(t) > 1:
            dt = np.diff(t)
            if np.any(dt < 0):
                idx = int(np.flatnonzero(dt < 0)[0])
                raise NonMonotonicTimeError(
                    f"Non-monotonic time in encoder log at row {row_offset + idx + 1}",
                    row=row_offset + idx + 1,
                )

    @staticmethod
    def _deduplicate(t: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Remove duplicate timestamps, keeping the last value."""
        if len(t) <= 1:
            return t, v
        dt = np.diff(t)
        mask = np.ones(len(t), dtype=bool)
        mask[:-1] = dt > 0
        return t[mask], v[mask]
