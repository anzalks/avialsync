"""Pyramid module for decimation and plotting."""

import math
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

    # Use suppress warnings for all-NaN slices
    with np.errstate(invalid="ignore"):
        v_min = np.nanmin(v_view, axis=1)
        v_max = np.nanmax(v_view, axis=1)

    # Handle remainder if exists
    if remainder > 0:
        t_rem = np.array([t[n_trunc]])
        with np.errstate(invalid="ignore"):
            v_rem_min = np.array([np.nanmin(v[n_trunc:])])
            v_rem_max = np.array([np.nanmax(v[n_trunc:])])

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

    dt = np.diff(t)
    # Estimate median from a subsample — much faster than np.median on 180M items.
    stride = max(1, len(dt) // _MEDIAN_SAMPLE_STRIDE)
    median_dt = float(np.median(dt[::stride]))

    if math.isnan(median_dt) or median_dt <= 0:
        return np.zeros(len(t), dtype=bool)

    gap_threshold = median_dt * 10.0
    mask = np.zeros(len(t), dtype=bool)
    mask[:-1] = dt > gap_threshold

    return mask


class PyramidBuilder:
    """Builds and serializes a multi-level pyramid to disk."""

    def __init__(self, cache_dir: Path, channel_id: str):
        self.cache_dir = cache_dir
        self.channel_id = channel_id

    def build_and_save(self, t: np.ndarray, v: np.ndarray) -> None:
        gap_mask = build_gap_mask(t)

        # Save exact level 1 (full resolution, float64 time; float64 values)
        np.save(self.cache_dir / f"{self.channel_id}_t.npy", t)
        np.save(self.cache_dir / f"{self.channel_id}_v.npy", v)
        np.save(self.cache_dir / f"{self.channel_id}_gap.npy", gap_mask)

        # Build and save decimated levels.
        # vmin/vmax stored as float32 (D-023): sensor precision is ≤16-bit so
        # float32 (7 decimal digits) is lossless in practice, and halves IO for
        # the largest level.  t arrays remain float64 for seek accuracy.
        for level in LEVELS[1:]:
            t_lvl, vmin_lvl, vmax_lvl = build_pyramid_level(t, v, level)
            gap_lvl = build_gap_mask(t_lvl)
            np.save(self.cache_dir / f"{self.channel_id}_pyr_{level}_t.npy", t_lvl)
            np.save(
                self.cache_dir / f"{self.channel_id}_pyr_{level}_vmin.npy",
                vmin_lvl.astype(np.float32, copy=False),
            )
            np.save(
                self.cache_dir / f"{self.channel_id}_pyr_{level}_vmax.npy",
                vmax_lvl.astype(np.float32, copy=False),
            )
            np.save(self.cache_dir / f"{self.channel_id}_pyr_{level}_gap.npy", gap_lvl)


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
