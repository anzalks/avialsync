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

import numpy as np

LEVELS = [1, 16, 256, 4096]

#: Default bound for :meth:`PyramidReader.iter_raw_chunks`.  Workers that scan a
#: whole recording must stay inside a fixed working set regardless of length.
RAW_CHUNK_SAMPLES = 1_000_000

# Subsample stride for median-dt estimation.  Using every N-th point is
# statistically equivalent to using the full diff for uniform/near-uniform
# sensor data, and orders of magnitude faster at 180 M samples.
# (D-023 note: this is the only algorithm-visible change; results are
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


def _safe_save(path: Path, arr: np.ndarray) -> None:
    """Save quickly, retrying macOS interrupted writes through a memmap."""
    try:
        np.save(path, arr)
        return
    except InterruptedError:
        # A signal can interrupt NumPy's C-level fwrite on macOS. Recreate the
        # partial file through mmap; all other storage failures remain visible.
        pass

    mapped = np.lib.format.open_memmap(path, mode="w+", dtype=arr.dtype, shape=arr.shape)
    mapped[:] = arr
    mapped.flush()


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
    remainder = n % factor
    n_trunc = n - remainder

    t_dec = t[:n_trunc:factor]
    min_dec, max_dec = _nan_envelope(
        v_min[:n_trunc].reshape(-1, factor),
        v_max[:n_trunc].reshape(-1, factor),
        axis=1,
    )

    if remainder:
        t_dec = np.concatenate((t_dec, t[n_trunc : n_trunc + 1]))
        rem_min, rem_max = _nan_envelope(v_min[n_trunc:], v_max[n_trunc:])
        min_dec = np.concatenate((min_dec, [rem_min]))
        max_dec = np.concatenate((max_dec, [rem_max]))

    return t_dec, min_dec, max_dec


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
        # installed — mypy passed locally and failed in CI on the same code.
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
        if self._compact and self._count:
            staged = np.load(self.path, mmap_mode="r", allow_pickle=False)
            mapped = np.lib.format.open_memmap(
                target, mode="w+", dtype=np.float32, shape=(self._count,)
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


def count_nan(values: np.ndarray, chunk_size: int = RAW_CHUNK_SAMPLES) -> int:
    """Count NaNs in a possibly mmap-backed array without a full-size temporary."""
    total = 0
    for start in range(0, len(values), chunk_size):
        total += int(np.count_nonzero(np.isnan(values[start : start + chunk_size])))
    return total


class PyramidBuilder:
    """Builds and serializes a multi-level pyramid to disk."""

    def __init__(self, cache_dir: Path, channel_id: str):
        self.cache_dir = cache_dir
        self.channel_id = channel_id

    def build_and_save(self, t: np.ndarray, v: np.ndarray) -> None:
        """Build every level from in-memory arrays and write the full sidecar."""
        self.save_levels(t, v, build_gap_mask(t), include_base=True)

    def save_levels(
        self,
        t: np.ndarray,
        v: np.ndarray,
        gap_mask: np.ndarray,
        *,
        include_base: bool = True,
    ) -> None:
        """Write decimated levels for *t*/*v*, which may be mmap-backed.

        ``include_base=False`` skips the level-1 ``_t``/``_v``/``_gap`` arrays for
        callers that already staged them into the cache directory, so streamed
        imports write each raw sample exactly once.
        """
        arrays_to_save: list[tuple[Path, np.ndarray]] = []
        if include_base:
            # Save exact level 1 (full resolution, float64 time; float64 values)
            arrays_to_save = [
                (self.cache_dir / f"{self.channel_id}_t.npy", t),
                (self.cache_dir / f"{self.channel_id}_v.npy", v),
                (self.cache_dir / f"{self.channel_id}_gap.npy", gap_mask),
            ]

        # Build and save decimated levels.
        # vmin/vmax stored as float32 conditionally (D-023): if source is float64
        # (e.g. processed outputs with large magnitude offsets), we keep float64 to
        # avoid lossy downcasts. For raw sensor data (≤16-bit or float32), float32
        # is lossless and halves IO for the largest levels.
        save_dtype = v.dtype if v.dtype == np.float64 else np.float32

        previous_t = t
        previous_min = v
        previous_max = v
        previous_gap = gap_mask
        for level in LEVELS[1:]:
            t_lvl, vmin_lvl, vmax_lvl = _aggregate_pyramid_level(
                previous_t, previous_min, previous_max, factor=16
            )
            gap_lvl = _aggregate_gap_mask(previous_gap, factor=16)
            arrays_to_save.extend(
                (
                    (self.cache_dir / f"{self.channel_id}_pyr_{level}_t.npy", t_lvl),
                    (
                        self.cache_dir / f"{self.channel_id}_pyr_{level}_vmin.npy",
                        vmin_lvl.astype(save_dtype, copy=False),
                    ),
                    (
                        self.cache_dir / f"{self.channel_id}_pyr_{level}_vmax.npy",
                        vmax_lvl.astype(save_dtype, copy=False),
                    ),
                    (self.cache_dir / f"{self.channel_id}_pyr_{level}_gap.npy", gap_lvl),
                )
            )
            previous_t = t_lvl
            previous_min = vmin_lvl
            previous_max = vmax_lvl
            previous_gap = gap_lvl

        _save_arrays(arrays_to_save)


class PyramidReader:
    """Reads pyramid queries dynamically from mmapped arrays."""

    def __init__(self, cache_dir: Path, channel_id: str):
        self.cache_dir = cache_dir
        self.channel_id = channel_id
        self._arrays: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
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

    def _load_level(self, level: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        key = f"{self.channel_id}_{level}"
        with self._lock:
            cached = self._arrays.get(key)
            cache_dir = self.cache_dir
        if cached is not None:
            return cached
        # Opened outside the lock: a cold mmap open must not hold up a reader
        # on another thread that only wants a level already loaded.
        if level == 1:
            t = np.load(cache_dir / f"{self.channel_id}_t.npy", mmap_mode="r")
            v = np.load(cache_dir / f"{self.channel_id}_v.npy", mmap_mode="r")
            gap = np.load(cache_dir / f"{self.channel_id}_gap.npy", mmap_mode="r")
            loaded = (t, v, v, gap)
        else:
            stem = f"{self.channel_id}_pyr_{level}"
            loaded = (
                np.load(cache_dir / f"{stem}_t.npy", mmap_mode="r"),
                np.load(cache_dir / f"{stem}_vmin.npy", mmap_mode="r"),
                np.load(cache_dir / f"{stem}_vmax.npy", mmap_mode="r"),
                np.load(cache_dir / f"{stem}_gap.npy", mmap_mode="r"),
            )
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
        index = int(np.searchsorted(t, t_target, side="right")) - 1
        index = max(0, min(index, len(v) - 1))
        return index, float(v[index])

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

    def mapped_columns(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return the level-1 ``(t, v, gap)`` mmap views without copying.

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
        if chosen_level == 1:
            t, vmin, vmax, gap = (column[int(i0) : int(i1)] for column in (t, vmin, vmax, gap))
        else:
            # Stored buckets are aligned by sample index. Selecting by their
            # first timestamp misses a bucket overlapping the left edge and
            # includes out-of-window values at the right edge. Reduce only the
            # two partial buckets from raw samples; the interior stays mmapped.
            raw_t, raw_v, _, raw_gap = self._load_level(1)
            first = int(i0)
            last = int(i1)
            left_stop = min(last, -(-first // chosen_level) * chosen_level)
            full_stop = (last // chosen_level) * chosen_level
            right_start = max(left_stop, full_stop)
            parts: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
            if first < left_stop:
                parts.append(self._edge_envelope(raw_t, raw_v, raw_gap, first, left_stop))
            if left_stop < full_stop:
                start_bucket = left_stop // chosen_level
                stop_bucket = full_stop // chosen_level
                parts.append(
                    (
                        t[start_bucket:stop_bucket],
                        vmin[start_bucket:stop_bucket],
                        vmax[start_bucket:stop_bucket],
                        gap[start_bucket:stop_bucket],
                    )
                )
            if right_start < last:
                parts.append(self._edge_envelope(raw_t, raw_v, raw_gap, right_start, last))
            if not parts:
                return np.array([]), np.array([]), np.array([]), np.array([], dtype=bool)
            t, vmin, vmax, gap = (np.concatenate(columns) for columns in zip(*parts, strict=True))

        if len(t) <= budget:
            return t, vmin, vmax, gap

        # -(-a // b) is ceiling division: land at or under the budget, never over.
        factor = int(-(-len(t) // budget))
        t_dec, min_dec, max_dec = _aggregate_pyramid_level(t, vmin, vmax, factor)
        return t_dec, min_dec, max_dec, _aggregate_gap_mask(gap, factor)

    @staticmethod
    def _edge_envelope(
        times: np.ndarray, values: np.ndarray, gaps: np.ndarray, start: int, stop: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Reduce one partial stored bucket using only visible raw samples."""
        minimum, maximum = _nan_envelope(values[start:stop], values[start:stop])
        return (
            times[start : start + 1],
            np.array([minimum]),
            np.array([maximum]),
            np.array([bool(np.any(gaps[start:stop]))]),
        )

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
