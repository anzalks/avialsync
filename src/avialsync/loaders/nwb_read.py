"""Reading samples, frames, intervals and spikes out of an open NWB file (D-188).

Everything here takes an open ``h5py.File`` and a description from
:func:`avialsync.loaders.nwb_format.scan`, and reads only the slice asked for,
so a loader can stream a series in blocks without holding the file's arrays.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import h5py
import numpy as np

from avialsync.loaders.nwb_format import IntervalTable, SeriesInfo, UnitsTable
from avialsync.loaders.nwb_storage import is_dataset
from avialsync.loaders.nwb_text import text


def read_times(handle: h5py.File, info: SeriesInfo, start: int, stop: int) -> np.ndarray:
    """Return the times of samples ``[start, stop)`` of *info*, in seconds."""
    if info.has_timestamps:
        return np.asarray(handle[info.path]["timestamps"][start:stop], dtype=np.float64)
    assert info.rate is not None
    return info.start + np.arange(start, stop, dtype=np.float64) / info.rate


def read_values(handle: h5py.File, info: SeriesInfo, start: int, stop: int) -> np.ndarray:
    """Return samples ``[start, stop)`` of *info* as ``(n, columns)`` float64, in its unit.

    The schema stores raw numbers and says how to scale them: ``data *
    channel_conversion[column] * conversion + offset``. ``offset`` arrived in
    NWB 2.4 and ``channel_conversion`` is optional, so both default to doing
    nothing.
    """
    group = handle[info.path]
    data = group["data"]
    block = np.asarray(data[start:stop], dtype=np.float64)
    if block.ndim == 1:
        block = block.reshape(-1, 1)
    per_column = group.get("channel_conversion")
    if is_dataset(per_column) and per_column.shape == (block.shape[1],):
        block *= np.asarray(per_column[()], dtype=np.float64)[np.newaxis, :]
    conversion = float(data.attrs.get("conversion", 1.0))
    offset = float(data.attrs.get("offset", 0.0))
    if conversion != 1.0:
        block *= conversion
    if offset != 0.0:
        block += offset
    return block


def read_text(handle: h5py.File, info: SeriesInfo) -> tuple[np.ndarray, list[str]]:
    """Return an annotation series' times and texts."""
    times = read_times(handle, info, 0, info.length)
    raw = handle[info.path]["data"][: info.length]
    return times, [text(value) for value in raw]


def read_frames(handle: h5py.File, info: SeriesInfo, start: int, stop: int) -> np.ndarray:
    """Return frames ``[start, stop)`` of an imaging series in their stored type."""
    return np.asarray(handle[info.path]["data"][start:stop])


def read_intervals(handle: h5py.File, table: IntervalTable) -> tuple[np.ndarray, np.ndarray]:
    """Return a ``TimeIntervals`` table's start and stop times."""
    group = handle[table.path]
    starts = np.asarray(group["start_time"][()], dtype=np.float64)
    stops = np.asarray(group["stop_time"][()], dtype=np.float64)
    count = min(len(starts), len(stops))
    return starts[:count], stops[:count]


def interval_rows(handle: h5py.File, table: IntervalTable) -> Iterator[tuple[float, str]]:
    """Yield ``(start_time, description)`` for each row, from its scalar columns.

    Ragged columns (those with a ``_index`` partner) and references to other
    objects are left out: a list or a pointer does not read as one cell of text.
    """
    group = handle[table.path]
    starts, stops = read_intervals(handle, table)
    ids = group.get("id")
    row_ids = np.asarray(ids[()]) if is_dataset(ids) else np.arange(len(starts))
    columns: list[tuple[str, np.ndarray]] = []
    for key in _column_order(group):
        if key in ("start_time", "stop_time", "id") or key.endswith("_index"):
            continue
        dataset = group.get(key)
        if not is_dataset(dataset) or f"{key}_index" in group:
            continue
        if (
            dataset.ndim != 1
            or dataset.shape[0] < len(starts)
            or dataset.dtype.kind not in "biufOSU"
        ):
            continue
        columns.append((key, dataset[: len(starts)]))
    for row, start in enumerate(starts):
        parts = [f"{table.name} {_cell(row_ids[row]) if row < len(row_ids) else row}"]
        parts.append(f"{_cell(start)}–{_cell(stops[row])} s")
        parts.extend(f"{key}={_cell(values[row])}" for key, values in columns)
        yield float(start), " · ".join(parts)


def _column_order(group: h5py.Group) -> list[str]:
    declared = group.attrs.get("colnames")
    if declared is not None:
        return [text(value) for value in np.atleast_1d(declared)]
    return sorted(group.keys())


def read_spike_times(handle: h5py.File, table: UnitsTable, row: int) -> np.ndarray:
    """Return the spike times of the unit in *row* of *table*.

    ``spike_times`` is one flat array for every unit, and ``spike_times_index``
    holds where each unit's run ends -- the schema's ragged-column layout.
    """
    group = handle[table.path]
    index = group["spike_times_index"]
    begin = int(index[row - 1]) if row > 0 else 0
    end = int(index[row])
    return np.asarray(group["spike_times"][begin:end], dtype=np.float64)


def _cell(value: Any) -> str:
    """Write one table cell the way a person reads it."""
    if isinstance(value, bytes | np.bytes_):
        return text(bytes(value))
    if isinstance(value, bool | np.bool_):
        return "yes" if value else "no"
    if isinstance(value, np.integer | int):
        return str(int(value))
    if isinstance(value, np.floating | float):
        number = float(value)
        if not np.isfinite(number):
            return "–"
        return (
            f"{number:.3f}".rstrip("0").rstrip(".") if number != int(number) else str(int(number))
        )
    return text(value)
