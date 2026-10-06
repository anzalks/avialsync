"""Every time series in an NWB file, as one source (D-188).

One source per file rather than one per series, because the application names a
source by its path and an NWB file is one path holding dozens of series. Each
series keeps its own clock all the same: they are imported as **channel groups**,
one per series, so a 231-ROI fluorescence matrix is read in one pass over its
rows and stores one timestamp array, while a behaviour trace beside it keeps its
own, faster, clock.

What becomes a channel, and how:

* a 1-D or 2-D ``TimeSeries`` -- electrophysiology, calcium traces, position,
  pupil, wheel, anything an extension defines on the same shape -- one channel
  per column, in the unit the file declares, scaled by its ``conversion``;
* an ``IntervalSeries`` or a ``TimeIntervals`` table (trials, epochs) -- one
  channel that is 1 inside an interval and 0 outside it, on a regular grid so it
  is drawn as a box rather than a ramp (see :func:`interval_grid`);
* a ``Units`` table -- one pulse train per unit, high for a moment at each spike,
  keeping every spike time exact, the same shape as a TTL line from neo.

Trial rows and ``AnnotationSeries`` text become messages, so what the
experimenter recorded about each trial is readable at the instant it describes.
"""

from __future__ import annotations

import functools
import logging
import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.errors import SourceOpenError
from avialsync.core.messages import MAX_MESSAGES, Message, clean
from avialsync.core.source import ChannelInfo, TimeSeriesSource, display_unit
from avialsync.loaders import nwb_format, nwb_read
from avialsync.loaders.nwb_format import SeriesInfo, UnitsTable

logger = logging.getLogger(__name__)

#: Values held in memory at once while reading one series, across its columns.
#: The same bound neo's bulk reader uses: ~64 MB of float64.
_BULK_TARGET_VALUES = 8_000_000

#: The finest grid an interval channel is drawn on, and the most samples it may
#: take. One millisecond resolves any behavioural interval; the sample cap keeps a
#: ten-hour session's trial channel at a few megabytes, coarsening the grid
#: rather than growing without bound.
_GRID_MAX_RATE = 1000.0
_GRID_MAX_SAMPLES = 4_000_000

#: The longest a spike's pulse is drawn. Narrower when two spikes are closer.
_SPIKE_PULSE_S = 1e-3


@dataclass
class _Group:
    """One channel group: the channels that are read together and share a clock."""

    names: list[str]
    read: Callable[[Any], Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]]
    infos: list[ChannelInfo] = field(default_factory=list)


class NWBLoader(TimeSeriesSource):
    """Loads every time series, interval and spike train in an NWB 2.x file."""

    @classmethod
    def display_name(cls) -> str:
        return "NWB Time Series"

    def __init__(self) -> None:
        self._path: Path | None = None
        self._contents: nwb_format.FileContents | None = None
        self._groups: list[_Group] = []
        self._by_channel: dict[str, _Group] = {}

    @classmethod
    def can_open(cls, path: Path) -> float:
        return 0.9 if nwb_format.is_nwb_path(path) else 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        self._path = path
        self._contents = nwb_format.scan(path)
        self._groups = []
        with nwb_format.open_file(path) as handle:
            for info in self._contents.of_kind("signal"):
                self._groups.append(self._signal_group(info))
            for info in self._contents.of_kind("interval"):
                starts, stops = _interval_series_edges(handle, info)
                self._add_interval_group(info.name, starts, stops)
            for table in self._contents.interval_tables:
                starts, stops = nwb_read.read_intervals(handle, table)
                self._add_interval_group(table.name, starts, stops)
        for units in self._contents.units_tables:
            self._groups.extend(self._spike_groups(units))
        self._by_channel = {name: group for group in self._groups for name in group.names}
        if not self._groups:
            raise SourceOpenError(f"{path.name} holds no time series, intervals or spike trains.")
        logger.info(
            "NWB %s: %d channels in %d groups from %s",
            self._contents.version,
            len(self._by_channel),
            len(self._groups),
            path.name,
        )

    # ── Channel groups ─────────────────────────────────────────────────────

    def _signal_group(self, info: SeriesInfo) -> _Group:
        unit = display_unit(info.unit)
        names = info.channel_names()
        return _Group(
            names=names,
            read=lambda handle: _signal_chunks(handle, info, names),
            infos=[ChannelInfo(name, unit, "float64", info.rate) for name in names],
        )

    def _add_interval_group(self, name: str, starts: np.ndarray, stops: np.ndarray) -> None:
        grid = interval_grid(starts, stops)
        if grid is None:
            return
        times, values, rate = grid
        self._groups.append(
            _Group(
                names=[name],
                read=lambda _handle: iter([{name: (times, values)}]),
                infos=[ChannelInfo(name, "", "float64", rate)],
            )
        )

    def _spike_groups(self, units: UnitsTable) -> list[_Group]:
        groups: list[_Group] = []
        for row, name in zip(units.rows, units.channel_names(), strict=True):
            groups.append(
                _Group(
                    names=[name],
                    read=functools.partial(_spike_chunks, units=units, row=row, name=name),
                    infos=[ChannelInfo(name, "", "float64", None)],
                )
            )
        return groups

    def channels(self) -> list[ChannelInfo]:
        return [info for group in self._groups for info in group.infos]

    def iter_channel_groups(
        self,
    ) -> Iterator[tuple[list[str], Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]]]:
        """Yield each group's channel names with an iterator over its shared-clock chunks.

        The importer reads a group the way it reads neo's single-clock stream:
        every channel of a chunk shares one timestamp array, which it stores
        once. The file is opened per group and closed when the group is done.
        """
        for group in self._groups:
            yield group.names, self._read_group(group)

    def _read_group(self, group: _Group) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
        if self._path is None:  # pragma: no cover - guarded by open()
            raise SourceOpenError("NWB source has not been opened.")
        with nwb_format.open_file(self._path) as handle:
            yield from group.read(handle)

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        group = self._by_channel.get(ch)
        if group is None:
            raise SourceOpenError(f"NWB source has no channel {ch}.")
        for chunk in self._read_group(group):
            yield chunk[ch]

    # ── Messages ───────────────────────────────────────────────────────────

    def messages(self) -> list[Message]:
        """Return trial rows and annotation text, each at the instant it describes."""
        if self._path is None or self._contents is None:
            return []
        found: list[Message] = []
        with nwb_format.open_file(self._path) as handle:
            for info in self._contents.of_kind("annotation"):
                times, texts = nwb_read.read_text(handle, info)
                for time, text in zip(times, texts, strict=False):
                    if len(found) >= MAX_MESSAGES:
                        return found
                    if clean(text):
                        found.append(Message(text=clean(text), time=float(time), channel=info.name))
            for table in self._contents.interval_tables:
                for start, text in nwb_read.interval_rows(handle, table):
                    if len(found) >= MAX_MESSAGES:
                        return found
                    found.append(Message(text=clean(text), time=start, channel=table.name))
        return found


# ── Reading ────────────────────────────────────────────────────────────────


def _signal_chunks(
    handle: Any, info: SeriesInfo, names: list[str]
) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
    """Yield a series in row blocks, every column sharing one timestamp array."""
    length = info.length
    block = max(1, _BULK_TARGET_VALUES // max(1, len(names)))
    if info.has_timestamps:
        times = nwb_read.read_times(handle, info, 0, length)
        order = _chronological(times)
        if order is not None:
            # Rare, and read whole: a writer that appended out of order cannot be
            # streamed in file order without emitting time going backwards, which
            # the ingest contract forbids (TimeSeriesSource.read_chunks).
            logger.warning("%s timestamps are not increasing; sorting them.", info.path)
            values = nwb_read.read_values(handle, info, 0, length)[order]
            times = times[order]
            for start in range(0, len(times), block):
                stop = min(start + block, len(times))
                yield {
                    name: (times[start:stop], values[start:stop, column])
                    for column, name in enumerate(names)
                }
            return
    for start in range(0, length, block):
        stop = min(start + block, length)
        chunk_times = (
            times[start:stop]
            if info.has_timestamps
            else nwb_read.read_times(handle, info, start, stop)
        )
        values = nwb_read.read_values(handle, info, start, stop)
        yield {name: (chunk_times, values[:, column]) for column, name in enumerate(names)}


def _chronological(times: np.ndarray) -> np.ndarray | None:
    """Return the order that makes *times* strictly increasing, or ``None`` if it is.

    Duplicates keep the last sample written, as the ingest contract requires.
    """
    if len(times) < 2 or bool(np.all(np.diff(times) > 0)):
        return None
    order = np.argsort(times, kind="stable")
    ordered = times[order]
    keep = np.ones(len(order), dtype=bool)
    keep[:-1] = ordered[1:] != ordered[:-1]
    return order[keep]


def _interval_series_edges(handle: Any, info: SeriesInfo) -> tuple[np.ndarray, np.ndarray]:
    """Pair an ``IntervalSeries``' edges: positive data starts an interval, negative stops it."""
    times = nwb_read.read_times(handle, info, 0, info.length)
    data = nwb_read.read_values(handle, info, 0, info.length)[:, 0]
    order = np.argsort(times, kind="stable")
    starts: list[float] = []
    stops: list[float] = []
    open_at: float | None = None
    for time, value in zip(times[order], data[order], strict=True):
        if value > 0 and open_at is None:
            open_at = float(time)
        elif value < 0 and open_at is not None:
            starts.append(open_at)
            stops.append(float(time))
            open_at = None
    if open_at is not None:
        # Started and never stopped: the interval is real, its end is not known.
        starts.append(open_at)
        stops.append(open_at)
    return np.asarray(starts, dtype=np.float64), np.asarray(stops, dtype=np.float64)


def interval_grid(
    starts: np.ndarray, stops: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float] | None:
    """Sample a set of intervals as a 0/1 channel on a regular grid.

    A plot joins samples with straight lines, and the pyramid breaks the stroke
    wherever two samples sit further apart than ten times the median spacing.
    Edge samples alone therefore draw an eight-second trial as an eight-second
    ramp, or not at all; on a regular grid the same trial is a box with
    one-sample edges.

    A grid point reads 1 when *any* interval overlaps its cell, not only when
    the point itself falls inside one, so an interval shorter than a cell still
    shows -- a grid coarsened for a long session thins the edges, never the
    intervals. An interval without a usable stop occupies one cell.
    """
    finite = np.isfinite(starts)
    starts = starts[finite]
    stops = stops[finite]
    if len(starts) == 0:
        return None
    stops = np.where(np.isfinite(stops) & (stops >= starts), stops, starts)
    low, high = float(np.min(starts)), float(np.max(stops))
    span = max(high - low, 0.0)
    rate = _GRID_MAX_RATE if span == 0.0 else min(_GRID_MAX_RATE, _GRID_MAX_SAMPLES / span)
    step = 1.0 / rate
    origin = low - step
    count = int(math.ceil((high - origin) / step)) + 2
    first = np.floor((starts - origin) / step).astype(np.int64)
    last = np.maximum(first + 1, np.ceil((stops - origin) / step).astype(np.int64))
    np.clip(first, 0, count, out=first)
    np.clip(last, 0, count, out=last)
    marks = np.zeros(count + 1, dtype=np.int64)
    np.add.at(marks, first, 1)
    np.add.at(marks, last, -1)
    values = (np.cumsum(marks[:count]) > 0).astype(np.float64)
    times = origin + np.arange(count, dtype=np.float64) * step
    return times, values, rate


def _spike_chunks(
    handle: Any, units: UnitsTable, row: int, name: str
) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
    times, values = spike_pulses(nwb_read.read_spike_times(handle, units, row))
    if len(times):
        yield {name: (times, values)}


def spike_pulses(spikes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return a unit's spikes as a pulse train: high at each spike, low just after.

    Two samples per spike keep every spike time exact, the way a TTL line keeps
    its edges (``NeoLoader._read_event_chunks``). The pulse narrows below a
    millisecond where two spikes are closer than that, so the train stays
    strictly increasing.
    """
    spikes = np.unique(spikes[np.isfinite(spikes)])
    if len(spikes) == 0:
        return np.empty(0), np.empty(0)
    widths = np.full(len(spikes), _SPIKE_PULSE_S)
    if len(spikes) > 1:
        widths[:-1] = np.minimum(widths[:-1], np.diff(spikes) * 0.5)
    times = np.empty(2 * len(spikes), dtype=np.float64)
    times[0::2] = spikes
    times[1::2] = spikes + np.maximum(widths, np.spacing(np.abs(spikes) + 1.0))
    values = np.zeros(2 * len(spikes), dtype=np.float64)
    values[0::2] = 1.0
    return times, values
