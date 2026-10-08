"""Local measurements for derived-cache writes and warm video index reuse."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from avialsync.core.inspection import SourceInspection
from avialsync.core.pyramid import ChannelStage, PyramidBuilder
from avialsync.engine.importer import ImportWorker
from avialsync.engine.pyav_reader import PyAVReader
from tests.util_pyav_fixtures import cfr_times, write_video


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
    """Measure all-level warm checks for a 32-channel cached source."""
    axis = np.arange(100_000, dtype=np.float64) / 1_000.0
    for index in range(32):
        PyramidBuilder(tmp_path, f"ch{index}").build_and_save(axis, np.sin(axis + index))
    names = [f"ch{index}" for index in range(32)]
    ImportWorker._write_manifest(tmp_path, names, (0.0, float(axis[-1])), SourceInspection(path=""))

    manifest = json.loads((tmp_path / "import.json").read_text(encoding="utf-8"))
    benchmark(
        ImportWorker._arrays_intact,
        tmp_path,
        names,
        manifest["array_sizes"],
        manifest["array_fingerprints"],
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
