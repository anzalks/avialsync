"""Cache columns preserve indexing, clock precision and conversion contracts."""

from __future__ import annotations

import numpy as np
import pytest

from avialsync.core.columns import LazyColumn, RegularTimes, ScaledColumn, fit_regular


@pytest.mark.parametrize(
    "key",
    [
        0.5,
        [1.5],
        np.array([0.0]),
        np.array([], dtype=float),
    ],
)
def test_invalid_indices_never_silently_select_another_sample(key: object) -> None:
    raw = np.arange(5.0)
    with pytest.raises(IndexError):
        raw[key]
    with pytest.raises(IndexError):
        RegularTimes(0.0, 1.0, len(raw))[key]


def test_unsigned_index_overflow_cannot_wrap_to_a_valid_negative_index() -> None:
    with pytest.raises(IndexError):
        RegularTimes(0.0, 1.0, 5)[np.array([2**64 - 1], dtype=np.uint64)]


@pytest.mark.parametrize(
    "key", [-1, (-2,), [0, -1], [True, False, True, False, False], slice(None, None, -1), []]
)
def test_supported_indices_match_stored_values(key: object) -> None:
    raw = np.arange(5.0)
    np.testing.assert_array_equal(RegularTimes(0.0, 1.0, len(raw))[key], raw[key])


@pytest.mark.parametrize("key", [5, -6, [5], [True, False]])
def test_out_of_range_or_wrong_mask_length_is_rejected(key: object) -> None:
    with pytest.raises(IndexError):
        RegularTimes(0.0, 1.0, 5)[key]


@pytest.mark.parametrize(
    "options", [{"rate": 0.0}, {"rate": np.inf}, {"step": -1.0}, {"step": np.nan}]
)
def test_invalid_clock_rate_or_step_cannot_be_used(options: dict) -> None:
    arguments = {"t0": 0.0, "rate": 1.0, "length": 5} | options
    with pytest.raises(ValueError, match="positive finite"):
        RegularTimes(**arguments)


def test_lazy_column_generic_accessors_and_materialization() -> None:
    class Computed(LazyColumn):
        dtype = np.dtype(float)

        def __len__(self) -> int:
            return 3

        def _take(self, positions: np.ndarray) -> np.ndarray:
            return positions.astype(float) + 2.0

    column = Computed()
    assert column.shape == (3,) and column.ndim == 1 and column.size == 3
    assert column[0] == 2.0
    assert list(column) == [2.0, 3.0, 4.0]
    np.testing.assert_array_equal(column.astype(np.int16), [2, 3, 4])
    np.testing.assert_array_equal(np.asarray(column, dtype=np.float32), [2, 3, 4])
    np.testing.assert_array_equal(column + 2.0, [4, 5, 6])


@pytest.mark.parametrize("kind", [np.float64, np.int32, np.int16])
def test_scaled_scalar_reads_match_block_conversion(kind: type) -> None:
    column = ScaledColumn(np.array([-2, 0, 3], dtype=kind), (1.0, 0.125), 4.5, np.float64)
    expected = column.convert(column.raw)
    np.testing.assert_array_equal([column[index] for index in range(3)], expected)
    assert column.conversion == ((1.0, 0.125), 4.5, np.dtype(np.float64).str)


@pytest.mark.parametrize("options", [{}, {"step": 0.01}, {"ticks": 170_000_000_000.0}])
def test_clock_search_handles_scalar_arrays_infinities_and_adjacent_rounding(options: dict) -> None:
    grid = RegularTimes(1.7e9, 100.0, 7, **options)
    raw = np.asarray(grid)
    queries = [
        np.array(raw[2]),
        np.nextafter(raw[2], -np.inf),
        np.nextafter(raw[2], np.inf),
        -np.inf,
        np.inf,
        np.nan,
    ]
    for side in ("left", "right"):
        for query in queries:
            assert grid.searchsorted(query, side) == raw.searchsorted(query, side)
    assert "RegularTimes" in repr(grid)


def test_vector_search_matches_numpy_when_epoch_precision_repeats_samples() -> None:
    grid = RegularTimes(1.7e9, 1e8, 64)
    raw = np.asarray(grid)
    queries = np.concatenate((raw, [np.nan, np.inf, -np.inf]))
    for side in ("left", "right"):
        np.testing.assert_array_equal(
            grid.searchsorted(queries, side), raw.searchsorted(queries, side)
        )


def test_search_corrections_preserve_tick_formula_and_next_float_boundaries() -> None:
    for grid, query in [
        (RegularTimes(0, 1, 20, ticks=10), 11.5),
        (RegularTimes(0, 3, 20), np.nextafter(1 / 3, np.inf)),
    ]:
        raw = np.asarray(grid)
        for side in ("left", "right"):
            assert grid.searchsorted(query, side) == raw.searchsorted(query, side)
    for values in ([1.0, 0.0], [np.nan, 1.0]):
        assert fit_regular(np.asarray(values)) is None
