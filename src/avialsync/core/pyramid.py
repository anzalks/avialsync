"""Pyramid module for decimation and plotting."""

import math
import os
import struct
import threading
import warnings
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from hashlib import blake2b
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.channel_store import level_stem, read_level, safe_save, write_times
from avialsync.core.columns import RegularTimes, ScaledColumn, fit_regular, no_gaps

LEVELS = [1, 16, 256, 4096]

#: Samples reduced per pass when building the first decimated level, so a level-1
#: column read in place -- a strided mmap of an interleaved file -- is never
#: copied whole into memory.
_LEVEL_CHUNK = 16 * 65_536

_INT16 = np.iinfo(np.int16)

#: Default bound for :meth:`PyramidReader.iter_raw_chunks`.  Workers that scan a
#: whole recording must stay inside a fixed working set regardless of length.
RAW_CHUNK_SAMPLES = 1_000_000

# Subsample stride for median-dt estimation.  Using every N-th point is
# statistically equivalent to using the full diff for uniform/near-uniform
# sensor data, and orders of magnitude faster at 180 M samples.
# (This is the only algorithm-visible change; results are
# identical for regular sensor data; irregular multi-second gaps are still
# detected correctly because the subsample captures global dt statistics.)
_MEDIAN_SAMPLE_STRIDE = 10_000
_GAP_CHUNK_SIZE = 1_000_000
_SAVE_WORKERS = 3


def _nan_envelope(
    values_min: np.ndarray, values_max: np.ndarray, axis: int | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Return NaN-aware bounds without warning for intentionally empty blocks."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmin(values_min, axis=axis), np.nanmax(values_max, axis=axis)


_safe_save = safe_save


def _save_arrays(arrays: list[tuple[Path, np.ndarray]]) -> None:
    """Persist independent sidecar arrays with bounded storage concurrency."""
    with ThreadPoolExecutor(max_workers=_SAVE_WORKERS) as pool:
        futures = [pool.submit(_safe_save, path, values) for path, values in arrays]
        for future in futures:
            future.result()


def build_pyramid_level(
    t: np.ndarray, v: np.ndarray, level: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build a decimation level for arrays t and v.

    Returns (t_decimated, v_min, v_max).
    If level=1, returns (t, v, v).
    NaN values are ignored via nanmin/nanmax.
    """
    if level == 1:
        return t, v, v

    n = len(t)
    remainder = n % level

    # Trim remainder for fast reshaping
    n_trunc = n - remainder
    t_trunc = t[:n_trunc]
    v_trunc = v[:n_trunc]

    # Reshape and vectorized min/max
    t_view = t_trunc.reshape(-1, level)
    v_view = v_trunc.reshape(-1, level)

    t_dec = t_view[:, 0]  # take the first timestamp of the block

    v_min, v_max = _nan_envelope(v_view, v_view, axis=1)

    # Handle remainder if exists
    if remainder > 0:
        t_rem = np.array([t[n_trunc]])
        rem_min, rem_max = _nan_envelope(v[n_trunc:], v[n_trunc:])
        v_rem_min = np.array([rem_min])
        v_rem_max = np.array([rem_max])

        t_dec = np.concatenate([t_dec, t_rem])
        v_min = np.concatenate([v_min, v_rem_min])
        v_max = np.concatenate([v_max, v_rem_max])

    return t_dec, v_min, v_max


def build_gap_mask(t: np.ndarray) -> np.ndarray:
    """Return a boolean mask where True indicates a gap larger than 10x median dt.

    Median is estimated from a subsampled diff to keep runtime O(n/S) instead
    of O(n) for large arrays — statistically equivalent for regular sensor data.
    """
    if len(t) < 2:
        return np.zeros(len(t), dtype=bool)

    # Sample adjacent pairs directly.  Constructing ``np.diff(t)`` would allocate
    # another 1.4 GB array for a 180 M-sample recording before we even build the
    # mask.  Adjacent pairs retain the original median-dt semantics.
    stride = max(1, (len(t) - 1) // _MEDIAN_SAMPLE_STRIDE)
    sample_starts = np.arange(0, len(t) - 1, stride)
    median_dt = float(np.median(t[sample_starts + 1] - t[sample_starts]))

    if math.isnan(median_dt) or median_dt <= 0:
        return np.zeros(len(t), dtype=bool)

    gap_threshold = median_dt * 10.0
    mask = np.zeros(len(t), dtype=bool)
    scratch = np.empty(min(_GAP_CHUNK_SIZE, len(t) - 1), dtype=np.float64)
    for start in range(0, len(t) - 1, _GAP_CHUNK_SIZE):
        stop = min(start + _GAP_CHUNK_SIZE, len(t) - 1)
        chunk_size = stop - start
        np.subtract(t[start + 1 : stop + 1], t[start:stop], out=scratch[:chunk_size])
        np.greater(scratch[:chunk_size], gap_threshold, out=mask[start:stop])

    return mask


def _aggregate_pyramid_level(
    t: np.ndarray, v_min: np.ndarray, v_max: np.ndarray, factor: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Aggregate one pyramid level from the preceding level's min/max envelopes."""
    n = len(t)
    n_trunc = n - n % factor
    t_dec = t[:n_trunc:factor]
    if n_trunc < n:
        t_dec = np.concatenate((t_dec, t[n_trunc : n_trunc + 1]))
    min_dec, max_dec = _aggregate_envelope(v_min, v_max, factor)
    return t_dec, min_dec, max_dec


def _aggregate_envelope(
    v_min: np.ndarray, v_max: np.ndarray, factor: int
) -> tuple[np.ndarray, np.ndarray]:
    """Each run of *factor* buckets' lowest minimum and highest maximum."""
    n = len(v_min)
    remainder = n % factor
    n_trunc = n - remainder
    same = v_min is v_max
    min_dec, max_dec = _nan_envelope(
        v_min[:n_trunc].reshape(-1, factor),
        (v_min if same else v_max)[:n_trunc].reshape(-1, factor),
        axis=1,
    )
    if remainder:
        rem_min, rem_max = _nan_envelope(v_min[n_trunc:], v_max[n_trunc:])
        min_dec = np.concatenate((min_dec, [rem_min]))
        max_dec = np.concatenate((max_dec, [rem_max]))
    return min_dec, max_dec


def _order_space(column: Any) -> tuple[Any, Any, tuple[Any, ...] | None]:
    """``(stored, convert, key)``: *column* as stored values and their conversion.

    Only a conversion that never reverses two values' order is offered (every
    multiplier positive), so the envelope of the stored values, converted, is
    the envelope of the converted values. Columns that share a *key* convert
    alike. A column without one is used as it reads.
    """
    if isinstance(column, ScaledColumn) and all(scale > 0 for scale in column.scales):
        return column.raw, column.convert, column.conversion
    if isinstance(column, np.ndarray) and not np.issubdtype(column.dtype, np.integer):
        return column, None, ("as stored", column.dtype.str)
    return column, None, None


def _aggregate_gap_mask(gap_mask: np.ndarray, factor: int) -> np.ndarray:
    """Carry raw discontinuity evidence into one coarser pyramid level.

    A gap marks the sample immediately before a discontinuity.  Recomputing a
    threshold from decimated timestamps can make a real short gap disappear;
    marking every parent bucket that contains a gap is conservative and never
    permits a display line to bridge evidence that was present at level 1.
    """
    length = len(gap_mask)
    remainder = length % factor
    truncated = length - remainder
    if truncated:
        coarse = np.any(gap_mask[:truncated].reshape(-1, factor), axis=1)
    else:
        coarse = np.empty(0, dtype=bool)
    if remainder:
        # The tail is built as a typed array rather than a bare list: the
        # `np.concatenate` overload that takes a sequence of mixed types
        # resolves to Any on some NumPy versions and to a typed ndarray on
        # others, so this line's type depended on which NumPy happened to be
        # installed.
        tail = np.array([bool(np.any(gap_mask[truncated:]))], dtype=bool)
        coarse = np.concatenate((coarse, tail))
    return np.asarray(coarse, dtype=bool)


class ChannelStage:
    """Append-only, bounded-memory staging buffer for one numeric channel.

    An import worker appends bounded parser chunks as they arrive and then
    materialises the result once.  Peak memory stays at one chunk instead of one
    complete channel, which is what makes a 1 GB / 180 M-sample import survive on
    a 16 GB machine. A fixed-width ``.npy`` header is reserved before the first sample and its
    count is finalized in place. Lossless float64 channels are then renamed
    into the cache without writing every sample a second time.
    """

    def __init__(
        self,
        staging_dir: Path,
        name: str,
        *,
        allow_float32: bool = False,
        hash_content: bool = False,
    ) -> None:
        self.path = staging_dir / f"{name}.stage"
        self._handle = self.path.open("wb")
        self._handle.write(self._header(0))
        self._count = 0
        self._compact = allow_float32
        #: Whole numbers in 16-bit range, no NaN: ADC counts and digital lines,
        #: stored in a quarter of float64's space with nothing lost.
        self._int16 = allow_float32
        self._digest = blake2b(digest_size=16) if hash_content else None

    @staticmethod
    def _header(count: int) -> bytes:
        """Write a NumPy v2 header whose length never depends on the count."""
        body = f"{{'descr': '<f8', 'fortran_order': False, 'shape': ({count:>20d},), }}"
        padding = (-(12 + len(body) + 1)) % 64
        payload = (body + " " * padding + "\n").encode("ascii")
        return b"\x93NUMPY\x02\x00" + struct.pack("<I", len(payload)) + payload

    @property
    def count(self) -> int:
        """Number of samples appended so far."""
        return self._count

    @property
    def content_digest(self) -> str | None:
        """Return a chunk-boundary-independent digest when requested at staging."""
        return None if self._digest is None else self._digest.hexdigest()

    def append(self, values: np.ndarray) -> None:
        """Append one bounded chunk of samples."""
        if self._handle.closed:
            raise ValueError("ChannelStage is closed")
        block = np.ascontiguousarray(values, dtype="<f8")
        if self._compact and not np.array_equal(
            block, block.astype(np.float32).astype(np.float64), equal_nan=True
        ):
            self._compact = False
        if self._int16 and block.size and not _fits_int16(block):
            self._int16 = False
        if self._digest is not None:
            self._digest.update(memoryview(block).cast("B"))
        block.tofile(self._handle)
        self._count += int(block.size)

    def close(self) -> None:
        """Close the staging handle; safe to call more than once."""
        if not self._handle.closed:
            self._handle.close()

    def discard(self) -> None:
        """Close and delete the staging file without materialising it."""
        self.close()
        self.path.unlink(missing_ok=True)

    def materialize(self, target: Path, chunk_size: int = RAW_CHUNK_SAMPLES) -> np.ndarray:
        """Finalize the header, then rename or losslessly compact into *target*."""
        self.close()
        with self.path.open("r+b") as handle:
            handle.write(self._header(self._count))
        if (self._compact or self._int16) and self._count:
            staged = np.load(self.path, mmap_mode="r", allow_pickle=False)
            mapped = np.lib.format.open_memmap(
                target,
                mode="w+",
                dtype=np.int16 if self._int16 else np.float32,
                shape=(self._count,),
            )
            for start in range(0, self._count, chunk_size):
                stop = min(start + chunk_size, self._count)
                mapped[start:stop] = staged[start:stop]
            mapped.flush()
            del mapped, staged
            self.path.unlink(missing_ok=True)
        else:
            os.replace(self.path, target)
        if self._count <= chunk_size:
            loaded: np.ndarray = np.load(target, allow_pickle=False)
            return loaded
        mapped_result: np.ndarray = np.load(target, mmap_mode="r", allow_pickle=False)
        return mapped_result


def _fits_int16(block: np.ndarray) -> bool:
    """Whether every sample of *block* is a whole number a 16-bit integer holds exactly."""
    if not np.all(np.isfinite(block)):
        return False
    if float(block.min()) < _INT16.min or float(block.max()) > _INT16.max:
        return False
    return bool(np.array_equal(block, np.trunc(block)))


def count_nan(values: Any, chunk_size: int = RAW_CHUNK_SAMPLES) -> int:
    """Count NaNs in a possibly mmap-backed array without a full-size temporary."""
    if np.issubdtype(np.dtype(values.dtype), np.integer):
        return 0
    total = 0
    for start in range(0, len(values), chunk_size):
        total += int(np.count_nonzero(np.isnan(values[start : start + chunk_size])))
    return total


class PyramidBuilder:
    """Builds and serializes a multi-level pyramid to disk (layout: ``channel_store``)."""

    def __init__(self, cache_dir: Path, channel_id: str):
        self.cache_dir = cache_dir
        self.channel_id = channel_id

    def build_and_save(self, t: np.ndarray, v: np.ndarray) -> None:
        """Build every level from in-memory arrays and write the full sidecar."""
        grid = fit_regular(t)
        times: Any = grid if grid is not None else t
        gap_mask = no_gap_mask(len(t)) if grid is not None else build_gap_mask(t)
        self.save_levels(times, v, gap_mask, include_base=True)

    def save_levels(
        self,
        t: Any,
        v: Any,
        gap_mask: np.ndarray | None,
        *,
        include_base: bool = True,
        first_level: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> None:
        """Write decimated levels for *t*/*v*, which may be mmap-backed or computed.

        ``include_base=False`` skips the level-1 columns for callers that already
        put them in the cache directory (or describe them in place), so streamed
        imports write each raw sample at most once.

        *t* may be a :class:`RegularTimes`, whose levels are grids too. A gap
        column is written only where it holds a gap; ``gap_mask`` may be
        ``None`` for a channel known to have none. *first_level* is the
        level-16 envelope when the caller already reduced it (an in-place import
        reduces every channel in one pass over the source); it must be in
        ``v``'s dtype.
        """
        has_gaps = gap_mask is not None and bool(np.any(gap_mask))
        arrays_to_save: list[tuple[Path, np.ndarray]] = []
        if include_base:
            write_times(self.cache_dir, self.channel_id, t)
            arrays_to_save.append((self.cache_dir / f"{self.channel_id}_v.npy", np.asarray(v)))
            if has_gaps:
                assert gap_mask is not None
                arrays_to_save.append((self.cache_dir / f"{self.channel_id}_gap.npy", gap_mask))

        # vmin/vmax keep the values' own precision: float64 stays float64 (large
        # offsets in processed outputs), integers stay integers (16-bit counts,
        # or raw samples read in place and scaled on read), and anything else is
        # float32, which is lossless for raw sensor data and halves the IO.
        dtype = np.dtype(v.dtype)
        save_dtype = (
            dtype if dtype == np.float64 or np.issubdtype(dtype, np.integer) else np.float32
        )

        previous_min, previous_max = (
            first_level if first_level is not None else _first_level(v, factor=16)
        )
        previous_t: Any = t
        previous_gap = gap_mask if has_gaps else None
        for position, level in enumerate(LEVELS[1:]):
            if position:
                _t, previous_min, previous_max = _aggregate_pyramid_level(
                    np.empty(len(previous_min)), previous_min, previous_max, factor=16
                )
            stem = level_stem(self.channel_id, level)
            if isinstance(t, RegularTimes):
                level_t: Any = t.level(level)
            else:
                level_t = _level_times(previous_t, 16)
                previous_t = level_t
            write_times(self.cache_dir, stem, level_t)
            arrays_to_save.extend(
                (
                    (
                        self.cache_dir / f"{stem}_vmin.npy",
                        previous_min.astype(save_dtype, copy=False),
                    ),
                    (
                        self.cache_dir / f"{stem}_vmax.npy",
                        previous_max.astype(save_dtype, copy=False),
                    ),
                )
            )
            if previous_gap is not None:
                previous_gap = _aggregate_gap_mask(previous_gap, factor=16)
                arrays_to_save.append((self.cache_dir / f"{stem}_gap.npy", previous_gap))

        _save_arrays(arrays_to_save)


def no_gap_mask(length: int) -> np.ndarray:
    """An all-false mask without memory, for a channel known to have no gap."""
    return no_gaps(length)


def _level_times(times: np.ndarray, factor: int) -> np.ndarray:
    """Every *factor*-th time plus the last partial block's first, as a level stores."""
    length = len(times)
    truncated = length - length % factor
    picked = np.asarray(times[:truncated:factor], dtype=np.float64)
    if length % factor:
        picked = np.concatenate((picked, np.asarray(times[truncated : truncated + 1])))
    return picked


def _first_level(values: Any, factor: int) -> tuple[np.ndarray, np.ndarray]:
    """The min/max envelope of *values* per *factor* samples, a bounded chunk at a time.

    The chunk is a multiple of *factor*, so each bucket is reduced from exactly
    the samples a whole-array reduction would see; a strided in-place column is
    copied one chunk at a time instead of whole.
    """
    length = len(values)
    buckets = -(-length // factor)
    dtype = np.dtype(values.dtype)
    minimum = np.empty(buckets, dtype=dtype)
    maximum = np.empty(buckets, dtype=dtype)
    chunk = _LEVEL_CHUNK - _LEVEL_CHUNK % factor
    for start in range(0, length, chunk):
        stop = min(start + chunk, length)
        block = np.ascontiguousarray(values[start:stop])
        whole = len(block) - len(block) % factor
        first = start // factor
        if whole:
            low, high = _nan_envelope(
                block[:whole].reshape(-1, factor), block[:whole].reshape(-1, factor), axis=1
            )
            minimum[first : first + len(low)] = low
            maximum[first : first + len(high)] = high
        if whole < len(block):
            low_tail, high_tail = _nan_envelope(block[whole:], block[whole:])
            minimum[-1] = low_tail
            maximum[-1] = high_tail
    return minimum, maximum


class PyramidReader:
    """Reads pyramid queries dynamically from mmapped arrays."""

    def __init__(self, cache_dir: Path, channel_id: str):
        self.cache_dir = cache_dir
        self.channel_id = channel_id
        self._arrays: dict[str, tuple[Any, Any, Any, np.ndarray]] = {}
        # A plot row's reader is also read by the page worker. The lock keeps a
        # level loaded from a directory `reopen` has just replaced out of the
        # cache, where it would serve the old generation from then on.
        self._lock = threading.Lock()

    def reopen(self, cache_dir: Path) -> None:
        """Read this channel from *cache_dir* from now on.

        What lets an edited generation (:mod:`avialsync.core.edit_cache`) reach
        a plot row, an overlay, or the readout without rebuilding any of them:
        the consumer keeps its row, its colour, its Y scale and its visibility,
        and only the arrays underneath change.

        Dropping the mmap views is the point as much as the path is. Holding
        them would keep the previous generation's files open, which on Windows
        is the difference between a directory that can be replaced and one that
        cannot.
        """
        with self._lock:
            if cache_dir == self.cache_dir:
                return
            self.cache_dir = cache_dir
            self._arrays.clear()

    def _load_level(self, level: int) -> tuple[Any, Any, Any, np.ndarray]:
        key = f"{self.channel_id}_{level}"
        with self._lock:
            cached = self._arrays.get(key)
            cache_dir = self.cache_dir
        if cached is not None:
            return cached
        # Opened outside the lock: a cold mmap open must not hold up a reader
        # on another thread that only wants a level already loaded.
        loaded = read_level(cache_dir, self.channel_id, level)
        with self._lock:
            if self.cache_dir == cache_dir:
                return self._arrays.setdefault(key, loaded)
        # Replaced while loading. This read is already obsolete -- the caller's
        # page or sample is superseded by the change that replaced it -- but it
        # is never cached, so nothing reads the old generation again.
        return loaded

    # ── Public bounded read API (Trap 13) ─────────────────────────────
    #
    # Every consumer outside this class reads through these methods.  They
    # return mmap views or fixed-size chunks so a caller can never materialise
    # a whole recording by accident, and they keep sampling policy in one place.

    def coverage(self) -> tuple[float, float] | None:
        """Return this channel's ``(t_first, t_last)`` extent, or None when empty."""
        t, _, _, _ = self._load_level(1)
        if len(t) == 0:
            return None
        return float(t[0]), float(t[-1])

    def sample_count(self) -> int:
        """Return the number of stored full-resolution samples."""
        t, _, _, _ = self._load_level(1)
        return int(len(t))

    def sample_at(self, t_target: float) -> tuple[int, float] | None:
        """Return the ``(index, value)`` of the last sample at or before *t_target*.

        Returns None for an empty channel.  The index is clamped into range so a
        cursor before the first sample reports sample 0 rather than nothing.
        """
        t, v, _, _ = self._load_level(1)
        if len(t) == 0:
            return None
        # The method, not np.searchsorted: the same answer without NumPy's dispatch,
        # on a stored array or a grid alike.
        index = int(t.searchsorted(t_target, side="right")) - 1
        index = max(0, min(index, len(v) - 1))
        return index, float(v[index])

    def neighbour_time(self, t_source: float, direction: int) -> float | None:
        """The time of the sample after (``direction > 0``) or before *t_source*.

        A nanosecond either side of *t_source* is treated as *t_source* itself,
        so a time that went through a master/source round trip still steps off
        the sample it stands on instead of finding it again.
        """
        t, _, _, _ = self._load_level(1)
        if len(t) == 0:
            return None
        if direction > 0:
            index = int(np.searchsorted(t, t_source + 1e-9, side="right"))
        else:
            index = int(np.searchsorted(t, t_source - 1e-9, side="left")) - 1
        return float(t[index]) if 0 <= index < len(t) else None

    def raw_slice(self, t0: float, t1: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return ``(t, v, gap)`` mmap views bounded to ``[t0, t1]``.

        Slicing an mmap yields a view, so the working set is the requested range
        rather than the recording.  Callers that need an unbounded scan must use
        :meth:`iter_raw_chunks` instead.
        """
        t, v, _, gap = self._load_level(1)
        first = int(np.searchsorted(t, t0, side="left"))
        last = int(np.searchsorted(t, t1, side="right"))
        return t[first:last], v[first:last], gap[first:last]

    def iter_raw_chunks(
        self,
        chunk_size: int = RAW_CHUNK_SAMPLES,
        t0: float | None = None,
        t1: float | None = None,
    ) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield chronological ``(t, v)`` views of at most *chunk_size* samples.

        This is the supported way to scan a whole channel — synchronization
        extraction, export, and statistics stay inside a bounded working set no
        matter how long the recording is.
        """
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        t, v, _, _ = self._load_level(1)
        first = 0 if t0 is None else int(np.searchsorted(t, t0, side="left"))
        last = len(t) if t1 is None else int(np.searchsorted(t, t1, side="right"))
        for start in range(first, last, chunk_size):
            stop = min(start + chunk_size, last)
            yield t[start:stop], v[start:stop]

    def iter_raw_chunks_with_gaps(
        self,
        chunk_size: int = RAW_CHUNK_SAMPLES,
        t0: float | None = None,
        t1: float | None = None,
    ) -> Iterator[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """Yield bounded source-time, value, and gap views for export."""
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        times, values, _, gaps = self._load_level(1)
        first = 0 if t0 is None else int(np.searchsorted(times, t0, side="left"))
        last = len(times) if t1 is None else int(np.searchsorted(times, t1, side="right"))
        for start in range(first, last, chunk_size):
            stop = min(start + chunk_size, last)
            yield times[start:stop], values[start:stop], gaps[start:stop]

    def mapped_columns(self) -> tuple[Any, Any, np.ndarray]:
        """Return the level-1 ``(t, v, gap)`` mmap views without copying.

        A column may be computed rather than mapped (:mod:`avialsync.core.columns`):
        it indexes, slices and ``np.searchsorted``s like an array, and a whole
        column NumPy operation materialises it, as reading a whole mmap did.

        Reserved for consumers that index single samples out of the whole
        recording on a clock tick (pose sampling).  The arrays are mmap-backed
        views: index or slice them, never reduce over them on the UI thread.
        """
        t, v, _, gap = self._load_level(1)
        return t, v, gap

    def query(
        self, t0: float, t1: float, max_points: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return ``(t, vmin, vmax, gap_mask)`` at close to ``max_points`` columns.

        Stored levels step by 16, so picking the first level that merely *fits*
        the budget undershoots it by up to 16x: a 1 M-sample window used to be
        drawn with 244 columns across a 1400-pixel plot, one point every six
        pixels, which reads as a jagged zigzag rather than a signal.

        Instead, take the coarsest stored level that still holds *at least* the
        budget — bounding the read to under ``16 * max_points`` points — and
        aggregate that down to the budget here.  The plot then gets roughly one
        column per pixel at every zoom, and a window whose raw samples already
        fit is returned untouched (exact samples, no envelope at all).
        """
        # Find time indices on base level
        t_base, _, _, _ = self._load_level(1)

        if len(t_base) == 0:
            return np.array([]), np.array([]), np.array([]), np.array([], dtype=bool)

        i0 = np.searchsorted(t_base, t0)
        i1 = np.searchsorted(t_base, t1, side="right")

        points_in_range = int(i1 - i0)
        budget = max(1, int(max_points))

        chosen_level = LEVELS[0]
        for level in LEVELS:
            if (points_in_range // level) < budget:
                break
            chosen_level = level

        t, vmin, vmax, gap = self._load_level(chosen_level)
        first, last = int(i0), int(i1)
        if chosen_level == 1:
            start, stop, left, right = first, last, None, None
            edge_t: Any = None
            edge_v: Any = None
            edge_gap: Any = None
        else:
            # Stored buckets are aligned by sample index. Selecting by their
            # first timestamp misses a bucket overlapping the left edge and
            # includes out-of-window values at the right edge. Reduce only the
            # two partial buckets from raw samples; the interior stays mmapped.
            edge_t, edge_v, _, edge_gap = self._load_level(1)
            left_stop = min(last, -(-first // chosen_level) * chosen_level)
            full_stop = (last // chosen_level) * chosen_level
            right_start = max(left_stop, full_stop)
            start = left_stop // chosen_level
            stop = max(start, full_stop // chosen_level)
            left = (first, left_stop) if first < left_stop else None
            right = (right_start, last) if right_start < last else None
        edges = [edge for edge in (left, right) if edge is not None]
        total = (stop - start) + len(edges)
        if total == 0:
            return np.array([]), np.array([]), np.array([]), np.array([], dtype=bool)
        # -(-a // b) is ceiling division: land at or under the budget, never over.
        factor = 1 if total <= budget else int(-(-total // budget))

        # Reduce the stored values and convert only what is returned, when
        # the conversion keeps their order (D-216): an in-place recording's
        # envelope then costs what a stored float column's did.
        same = vmin is vmax
        columns = [vmin, vmax] + ([edge_v] if edges else [])
        spaces = [_order_space(column) for column in columns]
        convert = spaces[0][1]
        if all(space[2] is not None and space[2] == spaces[0][2] for space in spaces):
            low, high = spaces[0][0], spaces[1][0]
            edge_v = spaces[-1][0]
        else:
            low, high, convert = vmin, vmax, None

        lows = low[start:stop]
        highs = lows if same else high[start:stop]
        gaps = gap[start:stop]
        if edges:
            pieces: list[tuple[Any, Any, Any]] = []
            for a, b in edges:
                block = edge_v[a:b]
                minimum, maximum = _nan_envelope(block, block)
                gapped = bool(np.any(edge_gap[a:b]))
                pieces.append((np.array([minimum]), np.array([maximum]), np.array([gapped])))
            before = [pieces[0]] if left is not None else []
            after = [pieces[-1]] if right is not None else []
            lows, highs, gaps = (
                np.concatenate([p[n] for p in before] + [inner] + [p[n] for p in after])
                for n, inner in enumerate((lows, highs, gaps))
            )
            same = False
        if factor > 1:
            lows, highs = _aggregate_envelope(lows, highs, factor)
            gaps = _aggregate_gap_mask(gaps, factor)
            same = False
        if convert is not None:
            lows = convert(lows)
            highs = lows if same else convert(highs)
        return self._times_at(t, start, stop, edge_t, left, right, factor), lows, highs, gaps

    @staticmethod
    def _times_at(
        t: Any,
        start: int,
        stop: int,
        edge_t: Any,
        left: tuple[int, int] | None,
        right: tuple[int, int] | None,
        factor: int,
    ) -> np.ndarray:
        """Every *factor*-th time of [left edge] + ``t[start:stop]`` + [right edge], unbuilt."""
        offset = 1 if left is not None else 0
        first = -(-offset // factor) * factor - offset  # the first kept interior position
        inner = t[start + first : stop : factor]
        if left is None and (right is None or (offset + stop - start) % factor):
            return np.asarray(inner)
        parts = [np.asarray(inner, dtype=np.float64)]
        if left is not None:
            parts.insert(0, np.array([edge_t[left[0]]], dtype=np.float64))
        if right is not None and (offset + stop - start) % factor == 0:
            parts.append(np.array([edge_t[right[0]]], dtype=np.float64))
        return np.concatenate(parts)

    def value_at(self, t_target: float) -> float:
        """
        Return the exact value at the given time `t_target` using the highest resolution level.
        Returns np.nan if out of bounds or if the nearest point is across a gap.
        """
        t, vmin, _, gap = self._load_level(1)
        if len(t) == 0:
            return float("nan")

        idx = np.searchsorted(t, t_target)

        if idx == len(t):
            return float("nan") if t_target - t[-1] > 0.1 else float(vmin[-1])

        if t[idx] == t_target:
            return float(vmin[idx]) if not gap[idx] else float("nan")

        if idx == 0:
            return float("nan") if t[0] - t_target > 0.1 else float(vmin[0])

        left_idx = idx - 1
        right_idx = idx

        if (t_target - t[left_idx]) <= (t[right_idx] - t_target):
            return float(vmin[left_idx]) if not gap[left_idx] else float("nan")
        else:
            return float(vmin[right_idx]) if not gap[right_idx] else float("nan")
