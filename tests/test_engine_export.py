"""Exact, bounded-memory export and statistics regression tests."""

import csv
import json
from pathlib import Path

import numpy as np

from avialsync.core.pyramid import PyramidBuilder, PyramidReader
from avialsync.engine.export import compute_region_stats, export_data_slice_csv
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
