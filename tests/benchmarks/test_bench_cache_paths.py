"""Local measurements for derived-cache writes and warm video index reuse."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from avialsync.core.cache import CacheManager
from avialsync.core.cache_leases import GenerationPin
from avialsync.core.columns import RegularTimes
from avialsync.core.inspection import SourceInspection
from avialsync.core.pyramid import ChannelStage, PyramidBuilder, PyramidReader
from avialsync.engine.importer import ImportWorker
from avialsync.engine.pyav_reader import PyAVReader
from tests.util_pyav_fixtures import cfr_times, write_video


def _published_channel(tmp_path: Path) -> Path:
    source = tmp_path / "source.csv"
    source.write_text("time,signal\n0,1\n", encoding="utf-8")
    manager = CacheManager(root=tmp_path / "cache")
    staging = manager.get_temp_cache_dir(source)
    PyramidBuilder(staging, "signal").build_and_save(np.array([0.0]), np.array([1.0]))
    manager.commit_cache(source, staging)
    return manager.get_cache_dir(source)


def test_bench_shared_reader_pin(benchmark, tmp_path: Path) -> None:
    """Snapshotting another channel reuses the source's one OS lease."""
    entry = _published_channel(tmp_path)
    held = GenerationPin(entry)

    def snapshot() -> None:
        pin = GenerationPin(entry)
        pin.close()

    try:
        benchmark(snapshot)
    finally:
        held.close()


def test_bench_published_reader_open(benchmark, tmp_path: Path) -> None:
    """Measure actual generation ownership when a published reader opens."""
    entry = _published_channel(tmp_path)

    def open_reader() -> None:
        reader = PyramidReader(entry, "signal")
        reader.close()

    benchmark(open_reader)


def test_bench_streamed_stage_finalize(benchmark, tmp_path: Path) -> None:
    """Measure the one-write float64 stage used for precision-sensitive values."""
    values = np.arange(1_000_000, dtype=np.float64) / 7.0
    target = tmp_path / "values.npy"

    def write() -> None:
        stage = ChannelStage(tmp_path, "values")
        for start in range(0, len(values), 100_000):
            stage.append(values[start : start + 100_000])
        stage.materialize(target)
        target.unlink()

    benchmark(write)


def test_bench_streamed_timestamp_digest(benchmark, tmp_path: Path) -> None:
    """Measure streamed equality detection for separately loaded time axes."""
    values = np.arange(1_000_000, dtype=np.float64) / 1_000.0
    target = tmp_path / "times.npy"

    def write() -> None:
        stage = ChannelStage(tmp_path, "times", hash_content=True)
        for start in range(0, len(values), 100_000):
            stage.append(values[start : start + 100_000])
        assert stage.content_digest is not None
        stage.materialize(target)
        target.unlink()

    benchmark(write)


def test_bench_warm_pyramid_manifest_validation(benchmark, tmp_path: Path) -> None:
    """Measure warm manifest validation for a 32-channel cached source."""
    axis = np.arange(100_000, dtype=np.float64) / 1_000.0
    for index in range(32):
        PyramidBuilder(tmp_path, f"ch{index}").build_and_save(axis, np.sin(axis + index))
    names = [f"ch{index}" for index in range(32)]
    ImportWorker._write_manifest(tmp_path, names, (0.0, float(axis[-1])), SourceInspection(path=""))

    manifest = json.loads((tmp_path / "import.json").read_text(encoding="utf-8"))
    assert benchmark(
        ImportWorker._arrays_intact,
        tmp_path,
        names,
        manifest["array_sizes"],
        manifest["array_fingerprints"],
        manifest["array_mtimes"],
    )


def test_bench_warm_video_index_open(benchmark, tmp_path: Path) -> None:
    """Measure a second video open after the PTS/keyframe index is cached."""
    source = tmp_path / "indexed.mp4"
    write_video(source, frame_times=cfr_times(300), gop_size=30)
    with PyAVReader(source):
        pass

    def open_cached() -> None:
        with PyAVReader(source) as reader:
            assert reader.frame_count == 300

    benchmark(open_cached)


def test_bench_regular_epoch_scalar_search(benchmark) -> None:
    """A cursor's regular-clock lookup stays inside the query budget."""
    grid = RegularTimes(1.7e9, 50_000, 1_000_000)
    target = float(grid[500_000])
    assert benchmark(grid.searchsorted, target) == 500_000
    assert benchmark.stats.stats.mean < 0.005


def test_bench_regular_epoch_vector_search(benchmark) -> None:
    """Bounded plot time queries retain their arithmetic fast path."""
    grid = RegularTimes(1.7e9, 50_000, 1_000_000)
    indices = np.arange(0, 1_000_000, 1_000, dtype=np.int64)
    targets = grid[indices]
    np.testing.assert_array_equal(benchmark(grid.searchsorted, targets), indices)
    assert benchmark.stats.stats.mean < 0.005
