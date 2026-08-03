"""Regression tests for hierarchical pyramid construction."""

from __future__ import annotations

import numpy as np

from avialsync.core.pyramid import PyramidBuilder, build_pyramid_level


def test_hierarchical_levels_match_direct_reduction(tmp_path) -> None:
    """Cached hierarchical envelopes preserve direct full-resolution extrema."""
    times = np.arange(4_211, dtype=np.float64) * 0.001
    values = np.sin(times * 7.0)
    values[11:19] = np.nan
    values[-5:] = np.nan

    PyramidBuilder(tmp_path, "signal").build_and_save(times, values)

    for level in (16, 256, 4096):
        expected_t, expected_min, expected_max = build_pyramid_level(times, values, level)
        actual_t = np.load(tmp_path / f"signal_pyr_{level}_t.npy")
        actual_min = np.load(tmp_path / f"signal_pyr_{level}_vmin.npy")
        actual_max = np.load(tmp_path / f"signal_pyr_{level}_vmax.npy")

        np.testing.assert_array_equal(actual_t, expected_t)
        np.testing.assert_allclose(actual_min, expected_min, equal_nan=True)
        np.testing.assert_allclose(actual_max, expected_max, equal_nan=True)
