"""The large certification input is bounded, chronological and backed by known sample values."""

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from tools.make_fixtures import generate_certification_signal


def test_certification_csv_preserves_chronology_and_counts_across_chunks(tmp_path: Path) -> None:
    target = tmp_path / "fixture.csv"
    report = generate_certification_signal(target, 30_000, chunk_rows=128)
    data = pl.read_csv(target)
    assert report["bytes"] == target.stat().st_size >= 30_000
    assert len(data) == report["samples"] > 128
    assert report["rate_hz"] == 50_000
    times = data["time"].to_numpy()
    indices = np.arange(len(data), dtype=np.int64)
    np.testing.assert_array_equal(times, indices / 50_000)
    np.testing.assert_array_equal(data["ch0"], (np.sin(2 * np.pi * times) * 32000).astype(np.int16))
    np.testing.assert_array_equal(data["ch1"], ((indices % 2000 - 1000) * 32).astype(np.int16))
    assert data["ch3"].min() >= -5000 and data["ch3"].max() <= 5000


@pytest.mark.parametrize("size,chunk", [(0, 128), (1000, 0), (-1, 128)])
def test_invalid_certification_fixture_sizes_do_not_create_a_file(
    tmp_path: Path, size, chunk
) -> None:
    target = tmp_path / "fixture.csv"
    with pytest.raises(ValueError, match="positive"):
        generate_certification_signal(target, size, chunk_rows=chunk)
    assert not target.exists()
