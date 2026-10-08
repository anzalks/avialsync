"""Exact, bounded-memory export and statistics regression tests."""

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from avialsync.core.cache_leases import reserve_cache_entry
from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.errors import CacheError
from avialsync.core.pyramid import PyramidBuilder, PyramidReader
from avialsync.core.timeline import TimeMap
from avialsync.engine.export import (
    compute_region_stats,
    export_data_slice_csv,
    export_data_slice_parquet,
)
from avialsync.engine.export_worker import (
    DataExportWorker,
    ReaderReference,
    RegionStatsWorker,
    VideoClipWorker,
)


def test_export_and_stats_use_only_the_requested_raw_slice(tmp_path: Path) -> None:
    times = np.arange(100_000, dtype=np.float64) * 0.001
    values = np.sin(times)
    PyramidBuilder(tmp_path, "signal").build_and_save(times, values)
    reader = PyramidReader(tmp_path, "signal")

    stats = compute_region_stats([reader], 10.0, 10.01)
    output = tmp_path / "slice.csv"
    export_data_slice_csv([reader], 10.0, 10.01, output)

    expected = values[10_000:10_011]
    assert stats[0]["n"] == len(expected)
    assert stats[0]["mean"] == np.mean(expected)
    lines = output.read_text(encoding="utf-8").splitlines()
    # Source header + channel header + column header + one row per sample.
    assert lines[0].startswith("# Source: ")
    assert lines[1] == "# Channel: signal"
    assert lines[2] == "time,signal"
    assert len(lines) == len(expected) + 5
    assert lines[-1].startswith('"# avialsync: ')


def test_background_export_and_stats_open_worker_local_readers(tmp_path: Path) -> None:
    times = np.arange(100, dtype=np.float64) * 0.1
    values = np.square(times)
    PyramidBuilder(tmp_path, "signal").build_and_save(times, values)
    reference = ReaderReference(tmp_path, "signal")

    stats_results: list[tuple[int, list[dict[str, float | str]]]] = []
    stats_worker = RegionStatsWorker(3, [reference], 2.0, 2.2)
    stats_worker.finished.connect(
        lambda request_id, stats: stats_results.append((request_id, stats))
    )
    stats_worker.run()

    output = tmp_path / "background.csv"
    export_results: list[str] = []
    export_worker = DataExportWorker([reference], 2.0, 2.2, output)
    export_worker.finished.connect(export_results.append)
    export_worker.run()

    assert stats_results[0][0] == 3
    assert stats_results[0][1][0]["n"] == 3
    assert export_results == [str(output)]
    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# Source: ")
    assert len(lines) == 8


def test_snapshot_open_refuses_a_generation_busy_with_replacement(tmp_path: Path) -> None:
    PyramidBuilder(tmp_path, "signal").build_and_save(np.array([0.0]), np.array([1.0]))
    reader = MappedChannelReader(PyramidReader(tmp_path, "signal"))
    with reserve_cache_entry(tmp_path) as reserved:
        assert reserved
        reference = ReaderReference.from_reader(reader)
        with pytest.raises(CacheError, match="in use"):
            reference.open()


def test_data_export_preserves_source_identity_and_mapping(tmp_path: Path) -> None:
    source = tmp_path / "signal.csv"
    source.write_text("original", encoding="utf-8")
    cache = tmp_path / "pyramid"
    cache.mkdir()
    PyramidBuilder(cache, "signal").build_and_save(np.array([0.0, 1.0]), np.array([2.0, 3.0]))
    reference = ReaderReference(cache, "signal", 0.25, 1.5, str(source))
    session = tmp_path / "trial.avv"
    output = tmp_path / "slice.csv"
    worker = DataExportWorker([reference], 0.0, 2.0, output, session)
    finished: list[str] = []
    worker.finished.connect(finished.append)
    worker.run()
    assert finished == [str(output)]
    rows = list(csv.reader(output.open(encoding="utf-8", newline="")))
    provenance = json.loads(rows[-1][0].removeprefix("# avialsync: "))
    assert provenance["sources"] == [{"name": "signal.csv", "size_bytes": 8}]
    assert provenance["session"] == str(session)
    assert provenance["time_maps"][str(source)] == {
        "offset_seconds": 0.25,
        "drift_ms_per_hour": 1.5,
    }

    blocked = DataExportWorker([reference], 0.0, 2.0, source, session)
    errors: list[str] = []
    blocked.error.connect(errors.append)
    blocked.run()
    assert errors and "loaded source" in errors[0]
    assert source.read_text(encoding="utf-8") == "original"


def test_csv_preserves_epoch_timestamps_at_sensor_rate(tmp_path: Path) -> None:
    epoch = 1_700_000_000.123456
    times = epoch + np.arange(4, dtype=np.float64) / 50_000
    values = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float64)
    PyramidBuilder(tmp_path, "signal").build_and_save(times, values)
    output = tmp_path / "precise.csv"

    export_data_slice_csv([PyramidReader(tmp_path, "signal")], times[0], times[-1], output)

    rows = list(csv.reader(output.open(encoding="utf-8", newline="")))
    exported_times = np.asarray([float(row[0]) for row in rows[3:7]])
    exported_values = np.asarray([float(row[1]) for row in rows[3:7]])
    np.testing.assert_array_equal(exported_times, times)
    np.testing.assert_array_equal(exported_values, values)


def test_worker_snapshot_uses_edited_values_and_exact_mapping(tmp_path: Path) -> None:
    base = tmp_path / "import"
    edited = base / "edited" / "generation"
    base.mkdir()
    edited.mkdir(parents=True)
    source_times = np.array([0.0, 1.0, 2.0])
    PyramidBuilder(base, "signal").build_and_save(source_times, np.array([1.0, 2.0, 3.0]))
    PyramidBuilder(edited, "signal").build_and_save(source_times, np.array([10.0, 20.0, 30.0]))
    mapping = TimeMap()
    master_times = np.array([100.0, 100.7, 102.0])
    mapping.set_exact_mapping(master_times, source_times)
    displayed = MappedChannelReader(PyramidReader(base, "signal"), mapping, "source.csv")
    displayed.read_from(edited)
    reference = ReaderReference.from_reader(displayed)
    mapping.set_mapping(50.0, 0.0)
    displayed.read_from(base)

    output = tmp_path / "edited.csv"
    worker = DataExportWorker([reference], 99.0, 103.0, output)
    worker.run()
    rows = list(csv.reader(output.open(encoding="utf-8", newline="")))
    np.testing.assert_array_equal([float(row[0]) for row in rows[3:6]], master_times)
    np.testing.assert_array_equal([float(row[1]) for row in rows[3:6]], [10.0, 20.0, 30.0])
    assert reference.cache_dir == edited


def test_parquet_export_preserves_time_values_and_gap_column(tmp_path: Path) -> None:
    parquet = pytest.importorskip("pyarrow.parquet")
    times = np.array([0.0, 0.1, 2.0, 2.1])
    values = np.array([1.0, np.nan, 3.0, 4.0])
    PyramidBuilder(tmp_path, "signal").build_and_save(times, values)
    output = tmp_path / "slice.parquet"

    export_data_slice_parquet([PyramidReader(tmp_path, "signal")], 0.0, 2.1, output)

    table = parquet.read_table(output)
    np.testing.assert_array_equal(table["time"].to_numpy(), times)
    np.testing.assert_allclose(table["value"].to_numpy(), values, equal_nan=True)
    assert table["gap_after"].to_pylist() == [False, True, False, False]


def test_region_stats_reduce_chunks_without_full_range_materialization(tmp_path: Path) -> None:
    class ChunkedReader:
        channel_id = "signal"
        cache_dir = tmp_path

        def iter_raw_chunks_with_gaps(self, **_kwargs):
            yield np.array([0.0, 1.0]), np.array([1.0, np.nan]), np.zeros(2, dtype=bool)
            yield np.array([2.0, 3.0]), np.array([3.0, 5.0]), np.zeros(2, dtype=bool)

    stats = compute_region_stats([ChunkedReader()], 0.0, 3.0)[0]
    assert stats["n"] == 3
    assert stats["min"] == 1.0
    assert stats["max"] == 5.0
    assert stats["mean"] == 3.0
    assert stats["rms"] == pytest.approx(np.sqrt(35.0 / 3.0))


def test_parquet_fallback_reports_the_csv_it_wrote(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "pyarrow", None)
    PyramidBuilder(tmp_path, "signal").build_and_save(np.array([0.0, 1.0]), np.array([2.0, 3.0]))
    requested = tmp_path / "data.parquet"
    finished: list[str] = []
    worker = DataExportWorker([ReaderReference(tmp_path, "signal")], 0.0, 1.0, requested)
    worker.finished.connect(finished.append)

    worker.run()

    assert finished == [str(tmp_path / "data.csv")]
    assert (tmp_path / "data.csv").is_file()
    assert not requested.exists()


def test_video_clip_worker_runs_ffmpeg_jobs_off_the_ui_path(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, float, float, Path]] = []

    def record_clip(path: str, t0: float, t1: float, output: Path) -> bool:
        calls.append((path, t0, t1, output))
        return path != "bad.mp4"

    monkeypatch.setattr("avialsync.engine.export_worker.trim_video_clip", record_clip)
    results: list[tuple[int, int]] = []
    worker = VideoClipWorker(
        [("good.mp4", 1.0, 2.0, tmp_path / "good.mp4"), ("bad.mp4", 1.0, 2.0, tmp_path / "bad.mp4")]
    )
    worker.finished.connect(lambda successful, total: results.append((successful, total)))

    worker.run()

    assert calls[0][0] == "good.mp4"
    assert results == [(1, 2)]


# Snapshot composition and capture live in tests/test_snapshot_figure.py, which
# owns the figure that replaced the old stacked widget grabs.
