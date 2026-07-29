"""Pyramid module for decimation and plotting."""

import math
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

LEVELS = [1, 16, 256, 4096]

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
        coarse = np.concatenate((coarse, [bool(np.any(gap_mask[truncated:]))]))
    return coarse


class PyramidBuilder:
    """Builds and serializes a multi-level pyramid to disk."""

    def __init__(self, cache_dir: Path, channel_id: str):
        self.cache_dir = cache_dir
        self.channel_id = channel_id

    def build_and_save(self, t: np.ndarray, v: np.ndarray) -> None:
        gap_mask = build_gap_mask(t)

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

    def _load_level(self, level: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        key = f"{self.channel_id}_{level}"
        if key not in self._arrays:
            if level == 1:
                t = np.load(self.cache_dir / f"{self.channel_id}_t.npy", mmap_mode="r")
                v = np.load(self.cache_dir / f"{self.channel_id}_v.npy", mmap_mode="r")
                gap = np.load(self.cache_dir / f"{self.channel_id}_gap.npy", mmap_mode="r")
                self._arrays[key] = (t, v, v, gap)
            else:
                t = np.load(self.cache_dir / f"{self.channel_id}_pyr_{level}_t.npy", mmap_mode="r")
                vmin = np.load(
                    self.cache_dir / f"{self.channel_id}_pyr_{level}_vmin.npy", mmap_mode="r"
                )
                vmax = np.load(
                    self.cache_dir / f"{self.channel_id}_pyr_{level}_vmax.npy", mmap_mode="r"
                )
                gap = np.load(
                    self.cache_dir / f"{self.channel_id}_pyr_{level}_gap.npy", mmap_mode="r"
                )
                self._arrays[key] = (t, vmin, vmax, gap)
        return self._arrays[key]

    def query(
        self, t0: float, t1: float, max_points: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Return (t, vmin, vmax, gap_mask) for the given time range,
        choosing appropriate resolution.
        """
        # Find time indices on base level
        t_base, _, _, _ = self._load_level(1)

        if len(t_base) == 0:
            return np.array([]), np.array([]), np.array([]), np.array([], dtype=bool)

        i0 = np.searchsorted(t_base, t0)
        i1 = np.searchsorted(t_base, t1, side="right")

        points_in_range = i1 - i0

        # Choose level
        chosen_level = LEVELS[0]
        for level in LEVELS:
            if (points_in_range // level) <= max_points:
                chosen_level = level
                break
        else:
            chosen_level = LEVELS[-1]

        # Extract from chosen level
        t, vmin, vmax, gap = self._load_level(chosen_level)

        lvl_i0 = np.searchsorted(t, t0)
        lvl_i1 = np.searchsorted(t, t1, side="right")

        return t[lvl_i0:lvl_i1], vmin[lvl_i0:lvl_i1], vmax[lvl_i0:lvl_i1], gap[lvl_i0:lvl_i1]

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
