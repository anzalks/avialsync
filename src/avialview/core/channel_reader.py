"""Master-clock presentation of a cached pyramid channel.

A :class:`~avialview.core.pyramid.PyramidReader` speaks its source's own time
base — whatever the acquisition system wrote.  Video sources have always been
projected onto the master clock through a :class:`~avialview.core.timeline.TimeMap`;
P3.5 gives time-series sources the same treatment so a sensor recorded on an
independent clock can be aligned without ever rewriting a cached sample.

:class:`MappedChannelReader` is drop-in compatible with ``PyramidReader``: every
method takes and returns **master** time.  Consumers (plot rows, readout, delta
measurement, export, statistics) therefore need no mapping logic of their own.

Only bounded results are converted.  ``mapped_columns`` deliberately stays in
source time — converting a whole recording would allocate a second copy of it —
so tick-rate consumers convert their scalar query instead via :attr:`time_map`.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from avialview.core.pyramid import RAW_CHUNK_SAMPLES, PyramidReader
from avialview.core.timeline import TimeMap


@dataclass(frozen=True, slots=True, order=True)
class ChannelKey:
    """Stable identity of one channel: its source plus its name.

    A channel name alone is not unique.  Two recordings of the same rig both
    contain ``force_z``; keying plots, readouts, units, visibility, or exports by
    the bare name lets one file silently overwrite or control the other's row.
    Every such map is keyed by this pair instead (P3.5 P1 identity).
    """

    source_id: str
    channel_id: str

    def label(self, ambiguous: bool = False) -> str:
        """Return the display name, qualified by source only when it must be."""
        if not ambiguous or not self.source_id:
            return self.channel_id
        return f"{self.channel_id} · {Path(self.source_id).name}"


def disambiguate(keys: list[ChannelKey]) -> dict[ChannelKey, str]:
    """Return display labels, qualifying only names owned by more than one source."""
    owners: dict[str, set[str]] = {}
    for key in keys:
        owners.setdefault(key.channel_id, set()).add(key.source_id)
    return {key: key.label(len(owners[key.channel_id]) > 1) for key in keys}


class MappedChannelReader:
    """A pyramid channel presented on the master clock through its ``TimeMap``."""

    def __init__(
        self,
        reader: PyramidReader,
        time_map: TimeMap | None = None,
        source_id: str = "",
    ) -> None:
        self._reader = reader
        self._time_map = time_map if time_map is not None else TimeMap()
        self._source_id = source_id

    # ── Identity (delegated so existing grouping/lookup keeps working) ─

    @property
    def cache_dir(self) -> Path:
        return self._reader.cache_dir

    @property
    def channel_id(self) -> str:
        return self._reader.channel_id

    @property
    def source_id(self) -> str:
        """The owning source's stable identifier (its path)."""
        return self._source_id

    @property
    def key(self) -> ChannelKey:
        """The ``(source_id, channel_id)`` identity of this channel."""
        return ChannelKey(self._source_id, self._reader.channel_id)

    @property
    def source_reader(self) -> PyramidReader:
        """The underlying source-time reader."""
        return self._reader

    @property
    def time_map(self) -> TimeMap:
        """The source-to-master mapping applied by every method here."""
        return self._time_map

    def set_mapping(self, offset: float, drift_ppm: float) -> None:
        """Replace the offset/drift mapping in place.

        Existing plot rows and readout rows keep their reader object, so a live
        offset edit is a mapping change rather than a channel reload.
        """
        self._time_map.offset = float(offset)
        self._time_map.drift_ppm = float(drift_ppm)

    # ── Bounded read API, all in master time ──────────────────────────

    def coverage(self) -> tuple[float, float] | None:
        """Return this channel's master-time extent, or None when empty."""
        bounds = self._reader.coverage()
        if bounds is None:
            return None
        return self._time_map.to_master(bounds[0]), self._time_map.to_master(bounds[1])

    def sample_count(self) -> int:
        return self._reader.sample_count()

    def sample_at(self, t_master: float) -> tuple[int, float] | None:
        return self._reader.sample_at(self._time_map.to_source(t_master))

    def value_at(self, t_master: float) -> float:
        return self._reader.value_at(self._time_map.to_source(t_master))

    def raw_slice(
        self, t0_master: float, t1_master: float
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return ``(t_master, v, gap)`` for a bounded master-time range."""
        t, v, gap = self._reader.raw_slice(
            self._time_map.to_source(t0_master), self._time_map.to_source(t1_master)
        )
        return self._time_map.to_master_array(t), v, gap

    def iter_raw_chunks(
        self,
        chunk_size: int = RAW_CHUNK_SAMPLES,
        t0: float | None = None,
        t1: float | None = None,
    ) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield bounded ``(t_master, v)`` chunks."""
        source_t0 = None if t0 is None else self._time_map.to_source(t0)
        source_t1 = None if t1 is None else self._time_map.to_source(t1)
        for times, values in self._reader.iter_raw_chunks(chunk_size, source_t0, source_t1):
            yield self._time_map.to_master_array(times), values

    def query(
        self, t0: float, t1: float, max_points: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Decimated master-time query; the result is bounded by *max_points*."""
        t, vmin, vmax, gap = self._reader.query(
            self._time_map.to_source(t0), self._time_map.to_source(t1), max_points
        )
        return self._time_map.to_master_array(t), vmin, vmax, gap

    def mapped_columns(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return level-1 mmap views in **source** time.

        Kept unmapped on purpose: converting the whole time column would
        materialise the recording.  Convert the scalar query with
        ``reader.time_map.to_source(t_master)`` instead.
        """
        return self._reader.mapped_columns()
