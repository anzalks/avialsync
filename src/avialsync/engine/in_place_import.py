"""Import a binary source without copying its samples into the cache.

An Open Ephys ``continuous.dat`` or an uncompressed, contiguous NWB dataset is
already an array NumPy can map. Copying it into the cache as floats tripled it
on disk (int16 became float32 or float64, and every channel carried a gap mask
and a timestamp per sample). Here level 1 stays in the source file, described
by each channel's ``_layout.json`` (:mod:`avialsync.core.channel_store`), and
only the decimated levels are written -- about a quarter of a byte per sample.

Every channel of a file is reduced in **one pass** over its rows: reading an
interleaved file column by column would read the whole file once per channel.
The first level is written to disk as it is built, so memory stays at one block
of rows whatever the recording's length.
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.channel_store import (
    ExternalArray,
    InPlaceChannel,
    Layout,
    write_layout,
    write_times,
)
from avialsync.core.columns import RegularTimes, fit_regular
from avialsync.core.errors import LoaderContractError
from avialsync.core.pyramid import PyramidBuilder, build_gap_mask

logger = logging.getLogger(__name__)

#: Upper bound on one block of rows read from the source, all columns included.
_BLOCK_BYTES = 64 * 1024 * 1024

#: Samples per level-1 bucket; the first stored level.
_FACTOR = 16

#: Above this, the first level is built on disk rather than in memory. A
#: 600-ROI series needs a few megabytes; a long multi-channel headstage, gigabytes.
_IN_MEMORY_BYTES = 256 * 1024 * 1024

Result = tuple[int, int, int, list[float], float, float]


def build_in_place(
    channels: dict[str, InPlaceChannel],
    temp_dir: Path,
    *,
    progress: Callable[[float], None],
    cancelled: Callable[[], bool],
    gap_locations: Callable[[Any, np.ndarray], list[float]],
    share_file: Callable[[Path, Path], None],
) -> Result | None:
    """Describe *channels* in place and write their decimated levels into *temp_dir*.

    Returns the importer's ``(rows, nan_count, gap_count, gap_locations, t0, t1)``,
    or ``None`` when cancelled.
    """
    names = list(channels)
    times, gap_mask, external_times = _time_axis(
        channels[names[0]].times, temp_dir, names, share_file
    )
    if cancelled():
        return None
    length = len(times)
    for name in names:
        # From the description: mapping the file per channel was most of an import.
        if channels[name].values.shape[0] != length:
            raise LoaderContractError(f"{name}: samples and timestamps differ in length")

    envelopes, nan_counts = _reduce_first_level(channels, temp_dir, progress, cancelled)
    if envelopes is None:
        return None

    has_gaps = gap_mask is not None and bool(np.any(gap_mask))
    for name in names:
        spec = channels[name]
        write_layout(
            temp_dir,
            name,
            Layout(
                scales=spec.scales,
                offset=spec.offset,
                dtype=spec.dtype,
                values=spec.values,
                times=external_times,
            ),
        )
        if external_times is None and not (temp_dir / f"{name}_t.npy").exists():
            write_times(temp_dir, name, times)
        if has_gaps:
            assert gap_mask is not None
            np.save(temp_dir / f"{name}_gap.npy", gap_mask)
        # Only the dtype is read when the first level is given; nothing is mapped.
        dtype_only = np.empty(0, dtype=np.dtype(spec.values.dtype))
        PyramidBuilder(temp_dir, name).save_levels(
            times,
            dtype_only,
            gap_mask if has_gaps else None,
            include_base=False,
            first_level=envelopes[name],
        )
    # The staged first level was copied into each channel's level files; it
    # must not be committed with the entry. Mappings go first (Windows).
    del envelopes
    for staged in temp_dir.glob("_first_*.npy"):
        staged.unlink(missing_ok=True)
    gaps = int(np.count_nonzero(gap_mask)) if has_gaps and gap_mask is not None else 0
    locations = gap_locations(times, gap_mask) if has_gaps and gap_mask is not None else []
    return length, sum(nan_counts.values()), gaps, locations, float(times[0]), float(times[-1])


def _time_axis(
    offered: Any, temp_dir: Path, names: list[str], share_file: Callable[[Path, Path], None]
) -> tuple[Any, np.ndarray | None, ExternalArray | None]:
    """The shared clock: a grid when the stored times prove it, else the times themselves.

    Returns ``(times, gap_mask, external)``: *external* is set when the times
    are read in place from the source, as a non-regular NWB ``timestamps``.
    """
    if isinstance(offered, RegularTimes):
        return offered, None, None
    column = offered.open() if isinstance(offered, ExternalArray) else offered
    grid = fit_regular(column)
    if grid is not None:
        return grid, None, None
    if isinstance(offered, ExternalArray):
        return column, build_gap_mask(column), offered
    # Computed from per-sample evidence (Open Ephys sample numbers with a drop):
    # not on disk as times, so written once and shared by every channel.
    first = temp_dir / f"{names[0]}_t.npy"
    stored = np.lib.format.open_memmap(first, mode="w+", dtype=np.float64, shape=(len(column),))
    step = 1_000_000
    for start in range(0, len(column), step):
        stored[start : start + step] = column[start : start + step]
    stored.flush()
    del stored
    for name in names[1:]:
        share_file(first, temp_dir / f"{name}_t.npy")
    times = np.load(first, mmap_mode="r", allow_pickle=False)
    return times, build_gap_mask(times), None


def _reduce_first_level(
    channels: dict[str, InPlaceChannel],
    temp_dir: Path,
    progress: Callable[[float], None],
    cancelled: Callable[[], bool],
) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]] | None, dict[str, int]]:
    """Every channel's level-16 envelope, one pass over each source file's rows."""
    by_file: dict[tuple[str, str, int, tuple[int, ...]], list[str]] = {}
    for name, spec in channels.items():
        values = spec.values
        key = (values.path, values.dtype, values.offset, values.shape)
        by_file.setdefault(key, []).append(name)

    envelopes: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    nan_counts = dict.fromkeys(channels, 0)
    done = 0
    for (path, dtype, offset, shape), names in by_file.items():
        source = np.memmap(path, dtype=np.dtype(dtype), mode="r", offset=offset, shape=shape)
        length = shape[0]
        buckets = -(-length // _FACTOR)
        columns = [channels[name].values.column for name in names]
        on_disk = 2 * buckets * source.dtype.itemsize * len(names) > _IN_MEMORY_BYTES
        out = {
            name: _first_level_columns(temp_dir, index, buckets, source.dtype, on_disk)
            for index, name in enumerate(names, start=done)
        }
        row_bytes = source.dtype.itemsize * (shape[1] if len(shape) > 1 else 1)
        rows = max(_FACTOR, (_BLOCK_BYTES // row_bytes) // _FACTOR * _FACTOR)
        floating = np.issubdtype(source.dtype, np.floating)
        for start in range(0, length, rows):
            if cancelled():
                return None, nan_counts
            stop = min(start + rows, length)
            block = np.asarray(source[start:stop])
            for name, column in zip(names, columns, strict=True):
                samples = block if column is None else block[:, column]
                low, high = _envelope(samples)
                first = start // _FACTOR
                out[name][0][first : first + len(low)] = low
                out[name][1][first : first + len(high)] = high
                if floating:
                    nan_counts[name] += int(np.count_nonzero(np.isnan(samples)))
            progress(0.8 * (done + len(names) * stop / length) / len(channels))
        for name in names:
            for built in out[name]:
                if isinstance(built, np.memmap):
                    built.flush()
            envelopes[name] = (out[name][0], out[name][1])
        done += len(names)
        del source
    return envelopes, nan_counts


def _first_level_columns(
    temp_dir: Path, index: int, buckets: int, dtype: np.dtype[Any], on_disk: bool
) -> tuple[np.ndarray, np.ndarray]:
    """Empty min and max columns for one channel's first level, in memory or on disk."""
    if not on_disk:
        return np.empty(buckets, dtype=dtype), np.empty(buckets, dtype=dtype)
    low: np.ndarray = np.lib.format.open_memmap(
        temp_dir / f"_first_{index}_min.npy", mode="w+", dtype=dtype, shape=(buckets,)
    )
    high: np.ndarray = np.lib.format.open_memmap(
        temp_dir / f"_first_{index}_max.npy", mode="w+", dtype=dtype, shape=(buckets,)
    )
    return low, high


def _envelope(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Min and max per 16 samples, the last bucket partial."""
    whole = len(values) - len(values) % _FACTOR
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        parts_low = [np.nanmin(values[:whole].reshape(-1, _FACTOR), axis=1)] if whole else []
        parts_high = [np.nanmax(values[:whole].reshape(-1, _FACTOR), axis=1)] if whole else []
        if whole < len(values):
            parts_low.append(np.array([np.nanmin(values[whole:])], dtype=values.dtype))
            parts_high.append(np.array([np.nanmax(values[whole:])], dtype=values.dtype))
    return np.concatenate(parts_low), np.concatenate(parts_high)
