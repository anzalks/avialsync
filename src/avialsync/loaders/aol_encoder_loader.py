"""AOL Encoder Log Loader.

Parses MATLAB-generated encoder_log.txt files with space-separated columns:
    HH:MM:SS:mmm  counter  position  velocity

Only the velocity channel is imported.

Master-time axis (do not "fix" this without reading DECISIONS.md):
    Within an auto-detected AOL session, encoder timestamps are emitted as
    **seconds since midnight UTC**, which is deliberately the same axis AOL
    videos and EKS tracking land on.  The AOL manifest reads each camera's
    absolute start epoch, and ``drop_worker._collect_aol_candidates`` then
    *subtracts* the session's anchor-date epoch from it -- putting video and
    EKS on seconds-since-midnight too.  Verified on
    2026-05-08/experiment_1/09-35-24: video [34526.312..34586.502],
    EKS [34526.312..34586.499], encoder [34526.082..34586.964].

    ``drop_worker`` marks every candidate it produces with
    ``config["auto_resolved"] = True`` -- that flag, not the presence of
    ``anchor_date`` (which the auto path also sets whenever a session has one),
    is what identifies an AOL-session import (D-052).  A manual import (a bare
    ``encoder_log.txt`` opened outside a detected session, so ``auto_resolved``
    is absent) has no video/EKS epoch to share, and a manually-opened video or
    CSV instead starts near its own relative zero -- so the encoder is shifted
    to start at its own first sample instead, landing on that same near-zero
    axis. Never add the session's anchor-date epoch here: on this file's own
    reference session that would shift the encoder a whole date (~20.6 days)
    away from the video it must align with.

    Across midnight the axis is *unwrapped* (86400, 86401, ...) rather than
    wrapped back to 0, because video/EKS master time is epoch-derived and keeps
    increasing.  See ``_unwrap_midnight``.
"""

import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.errors import MissingColumnError, NonMonotonicTimeError, SourceOpenError
from avialsync.core.source import ChannelInfo, TimeSeriesSource

logger = logging.getLogger(__name__)

# Matches HH:MM:SS:mmm (MATLAB writes milliseconds after a colon)
_TIME_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2}):(\d{3})$")

_CHUNK_SIZE = 50_000
_VELOCITY_CHANNEL = "encoder_velocity"
# A backward jump larger than half a day is a date rollover, not bad data.
_ROLLOVER_THRESHOLD_S = 43_200.0
_SECONDS_PER_DAY = 86_400.0


class AOLEncoderLoader(TimeSeriesSource):
    """Loads AOL encoder logs in bounded chunks.

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
            raise SourceOpenError(
                f"Expected 4 space-separated columns in encoder log, got {len(parts)}: {path}. "
                "Check that this is an AOL encoder_log.txt and not another text file."
            )
        if not _TIME_RE.match(parts[0]):
            raise SourceOpenError(
                f"First encoder column does not match HH:MM:SS:mmm: '{parts[0]}' in {path}. "
                "Check that this is an AOL encoder_log.txt written by the MATLAB logger."
            )

    def channels(self) -> list[ChannelInfo]:
        """Return a single velocity channel.

        ``rate_hz`` stays ``None``: the logger writes at roughly 1 kHz but only
        millisecond resolution, so repeated timestamps are collapsed on ingest
        and the effective interval is genuinely irregular.
        """
        return [
            ChannelInfo(name=_VELOCITY_CHANNEL, unit="deg/s", dtype="Float64", rate_hz=None),
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
        """Yield bounded (time, value) chunks for the requested channel.

        Chunk boundaries are carried the same way ``CSVLoader._read_batches``
        carries them, so chronology checks and duplicate collapsing behave
        identically whether two samples land in one chunk or straddle two.
        """
        if ch != _VELOCITY_CHANNEL:
            raise MissingColumnError(ch, [_VELOCITY_CHANNEL])

        if self._path is None:
            raise SourceOpenError(
                "Encoder source used before open(). Call open(path, config) first."
            )

        # `auto_resolved` -- not `anchor_date` -- is the reliable signal that this
        # is an AOL-session auto-import: drop_worker sets it on every candidate it
        # produces, whereas it also sets `anchor_date` whenever the session has
        # one, so `anchor_date` presence cannot distinguish the two paths (D-052).
        is_manual = not bool(self._config.get("auto_resolved", False))
        first_t: float | None = None

        times: list[float] = []
        values: list[float] = []
        row_offset = 0
        # Carried across chunk boundaries.
        unwrap = _MidnightUnwrapper()
        pending: tuple[float, float] | None = None

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

                if is_manual:
                    if first_t is None:
                        first_t = t_sec
                    t_sec -= first_t

                try:
                    velocity = float(parts[3])
                except ValueError:
                    logger.warning("Unparseable velocity at line %d: %s", line_no, parts[3])
                    continue

                times.append(unwrap.advance(t_sec))
                values.append(velocity)

                if len(times) >= _CHUNK_SIZE:
                    chunk, pending = self._finish_chunk(times, values, pending, row_offset)
                    if chunk is not None:
                        yield chunk
                    row_offset += len(times)
                    times.clear()
                    values.clear()

        if times:
            chunk, pending = self._finish_chunk(times, values, pending, row_offset)
            if chunk is not None:
                yield chunk

        # Flush the retained final sample.
        if pending is not None:
            yield (
                np.asarray([pending[0]], dtype=np.float64),
                np.asarray([pending[1]], dtype=np.float64),
            )

    @classmethod
    def _finish_chunk(
        cls,
        times: list[float],
        values: list[float],
        pending: tuple[float, float] | None,
        row_offset: int,
    ) -> tuple[tuple[np.ndarray, np.ndarray] | None, tuple[float, float] | None]:
        """Validate and de-duplicate one chunk, retaining its final sample.

        The retained sample is prepended to the next chunk so a duplicate or a
        backward jump spanning the boundary is treated exactly like one inside a
        chunk. Returns ``(chunk_to_yield, new_pending)``.
        """
        t_arr = np.asarray(times, dtype=np.float64)
        v_arr = np.asarray(values, dtype=np.float64)
        if pending is not None:
            t_arr = np.concatenate(([pending[0]], t_arr))
            v_arr = np.concatenate(([pending[1]], v_arr))

        cls._validate_monotonic(t_arr, row_offset)
        t_arr, v_arr = cls._deduplicate(t_arr, v_arr)

        if len(t_arr) == 0:
            return None, pending
        new_pending = (float(t_arr[-1]), float(v_arr[-1]))
        if len(t_arr) == 1:
            return None, new_pending
        return (t_arr[:-1], v_arr[:-1]), new_pending

    @staticmethod
    def _validate_monotonic(t: np.ndarray, row_offset: int) -> None:
        """Raise on backward time jumps (allowing duplicates for dedup)."""
        if len(t) > 1:
            dt = np.diff(t)
            if np.any(dt < 0):
                idx = int(np.flatnonzero(dt < 0)[0])
                raise NonMonotonicTimeError(
                    f"Non-monotonic time in encoder log at row {row_offset + idx + 1}. "
                    "The encoder log must be written in chronological order.",
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


class _MidnightUnwrapper:
    """Turn wrapping seconds-since-midnight into a continuous axis.

    AOL video and EKS master time is epoch-derived, so it keeps increasing past
    86400 when a recording crosses midnight.  The encoder's wall clock wraps back
    to 0 instead, which would read as a full-day backward jump.  Unwrapping keeps
    both streams on one axis (D-045).
    """

    def __init__(self) -> None:
        self._offset = 0.0
        self._previous_raw: float | None = None

    def advance(self, raw_seconds: float) -> float:
        """Return *raw_seconds* shifted onto the continuous master axis."""
        if (
            self._previous_raw is not None
            and raw_seconds < self._previous_raw - _ROLLOVER_THRESHOLD_S
        ):
            self._offset += _SECONDS_PER_DAY
        self._previous_raw = raw_seconds
        return raw_seconds + self._offset
