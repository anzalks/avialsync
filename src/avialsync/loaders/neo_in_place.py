"""Describe a neo signal stream's samples where they already are on disk.

neo reads Open Ephys (and other raw binary formats) by mapping the file, so it
can say where every channel's samples sit: the file, its dtype and byte offset,
the row layout, and the column. :func:`in_place_channels` turns that into
:class:`~avialsync.core.channel_store.InPlaceChannel` offers, so the importer
leaves the samples in the recording instead of copying them into the cache.

**The clock is checked against the data, not the header.** neo dates a stream
as ``t_start + i / rate`` from its header. Open Ephys also writes each sample's
own number (``sample_numbers.npy``, or ``timestamps.npy`` before GUI v0.6).
Every one is checked: consecutive numbers make the header's grid true; a drop
makes the times follow the numbers instead, and the gap is then visible where
it happened. A stream without per-sample numbers is not offered: nothing in it
could prove the grid.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.channel_store import ExternalArray, InPlaceChannel
from avialsync.core.columns import RegularTimes, ScaledColumn

logger = logging.getLogger(__name__)

#: Sample numbers checked per pass, so a recording of any length stays bounded.
_CHECK_CHUNK = 4_000_000


def in_place_channels(
    io: Any,
    signals: dict[str, tuple[Any, int]],
    clock: tuple[int, float, float, int],
) -> dict[str, InPlaceChannel] | None:
    """Offer every channel of *signals* in place, or ``None`` when any cannot be.

    *signals* maps a channel name to its neo ``AnalogSignalProxy`` and column;
    *clock* is the loader's shared ``(segment, t_start, rate, length)``.
    """
    has_api = getattr(io, "has_buffer_description_api", None)
    if not callable(has_api) or not has_api():
        return None
    _seg, t_start, rate, length = clock
    offers: dict[str, InPlaceChannel] = {}
    clocks: dict[str, Any] = {}
    for name, (signal, column) in signals.items():
        located = _locate(io, signal, column)
        if located is None:
            return None
        values, gain, offset, dtype = located
        if values.shape[0] != length or not gain > 0:
            return None
        if values.path not in clocks:
            clocks[values.path] = _verified_clock(Path(values.path).parent, t_start, rate, length)
        times = clocks[values.path]
        if times is None:
            return None
        offers[name] = InPlaceChannel(
            values=values, times=times, scales=(gain,), offset=offset, dtype=dtype
        )
    return offers


def _locate(io: Any, signal: Any, column: int) -> tuple[ExternalArray, float, float, str] | None:
    """Where *column* of a lazy neo signal sits in its raw buffer, and how it is scaled."""
    try:
        block, segment = int(signal._block_index), int(signal._seg_index)
        stream_index = int(signal._stream_index)
        inner = signal._inner_stream_channels
        global_indexes = signal._global_channel_indexes
    except AttributeError:
        return None  # not a lazy proxy; there is no file layout to describe
    stream = io.header["signal_streams"][stream_index]
    description = io.get_analogsignal_buffer_description(block, segment, stream["buffer_id"])
    if (
        description.get("type") != "raw"
        or description.get("order", "C") != "C"
        or description.get("time_axis", 0) != 0
        or len(description["shape"]) != 2
    ):
        return None
    in_stream = (
        int(np.arange(_stream_width(io, stream["id"]))[inner][column])
        if inner is not None
        else column
    )
    buffer_columns = np.arange(int(description["shape"][1]))
    selection = io._stream_buffer_slice.get(stream["id"])
    in_buffer = int(buffer_columns[selection][in_stream] if selection is not None else in_stream)
    channel = io.header["signal_channels"][int(np.asarray(global_indexes)[column])]
    if np.dtype(channel["dtype"]) != np.dtype(description["dtype"]):
        return None
    # The float type neo rescales into, which is what the loader stored.
    output = "float64" if np.dtype(description["dtype"]) == np.float64 else "float32"
    values = ExternalArray.describe(
        Path(description["file_path"]),
        description["dtype"],
        int(description.get("file_offset", 0)),
        tuple(int(n) for n in description["shape"]),
        column=in_buffer,
    )
    return values, float(channel["gain"]), float(channel["offset"]), output


def _stream_width(io: Any, stream_id: str) -> int:
    channels = io.header["signal_channels"]
    return int(np.count_nonzero(channels["stream_id"] == stream_id))


def _verified_clock(folder: Path, t_start: float, rate: float, length: int) -> Any:
    """The stream's times as its per-sample numbers say, or ``None`` if it has none.

    Consecutive numbers: the header's grid, bit-for-bit what the loader computes.
    A drop: ``t_start`` plus each sample's own number over the rate, so the
    missing stretch is a gap rather than samples moved earlier.
    """
    numbers = _sample_numbers(folder)
    if numbers is None or len(numbers) != length or length == 0:
        return None
    first = int(numbers[0])
    for start in range(0, length, _CHECK_CHUNK):
        stop = min(start + _CHECK_CHUNK, length)
        expected = first + np.arange(start, stop, dtype=np.int64)
        if not np.array_equal(np.asarray(numbers[start:stop], dtype=np.int64), expected):
            logger.warning(
                "%s: sample numbers are not consecutive; dating samples by their numbers.",
                folder,
            )
            return ScaledColumn(numbers, (1.0 / rate,), t_start - first / rate, np.float64)
    return RegularTimes(t_start, rate, length)


def _sample_numbers(folder: Path) -> np.ndarray | None:
    """``sample_numbers.npy`` (GUI v0.6+), or the integer ``timestamps.npy`` before it."""
    for name in ("sample_numbers.npy", "timestamps.npy"):
        path = folder / name
        if not path.is_file():
            continue
        try:
            numbers = np.load(path, mmap_mode="r", allow_pickle=False)
        except (OSError, ValueError):
            return None
        if numbers.ndim == 1 and np.issubdtype(numbers.dtype, np.integer):
            loaded: np.ndarray = numbers
            return loaded
    return None
