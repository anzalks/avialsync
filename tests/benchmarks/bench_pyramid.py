import gc
from pathlib import Path

import numpy as np
import pytest

from kinochronix.core.pyramid import PyramidBuilder, PyramidReader


@pytest.fixture(scope="session")
def large_dataset():
    """Generate 180M samples once per session to save time and memory."""
    N = 180_000_000
    t = np.linspace(0.0, 3600.0, N, dtype=np.float64)
    v = np.sin(t * 10.0)

    # Inject some NaNs and gaps
    v[1000:2000] = np.nan
    t[50000000:50000050] += 10.0

    return t, v


def test_bench_pyramid_build(benchmark, tmp_path: Path, large_dataset):
    t, v = large_dataset

    def setup():
        gc.collect()
        cache_dir = tmp_path / "bench.kcache"
        cache_dir.mkdir(exist_ok=True)
        builder = PyramidBuilder(cache_dir, "ch0")
        return (builder, t, v), {}

    def do_build(builder, t_arr, v_arr):
        builder.build_and_save(t_arr, v_arr)

    benchmark.pedantic(do_build, setup=setup, rounds=5)


def test_bench_pyramid_query(benchmark, tmp_path: Path, large_dataset):
    t, v = large_dataset

    cache_dir = tmp_path / "bench_q.kcache"
    cache_dir.mkdir(exist_ok=True)
    builder = PyramidBuilder(cache_dir, "ch0")
    builder.build_and_save(t, v)

    reader = PyramidReader(cache_dir, "ch0")

    # Query 1 hour of data, but max_points 1000 (so it should pick 4096 decimation level)
    def do_query():
        reader.query(100.0, 3500.0, max_points=1000)

    benchmark(do_query)
