"""Regression tests for hierarchical pyramid construction."""

from __future__ import annotations

import numpy as np

from avialsync.core.channel_store import read_level
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
        # Read through the layout: a regular clock's level times are a grid.
        level_t, level_min, level_max, _gap = read_level(tmp_path, "signal", level)
        actual_t, actual_min, actual_max = (
            np.asarray(column[:]) for column in (level_t, level_min, level_max)
        )

        np.testing.assert_array_equal(actual_t, expected_t)
        np.testing.assert_allclose(actual_min, expected_min, equal_nan=True)
        np.testing.assert_allclose(actual_max, expected_max, equal_nan=True)
