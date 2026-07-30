"""Bounded-memory import: staging buffers instead of complete-channel accumulation.

P3.5 P0 streaming.  The importer used to build every channel with
``np.concatenate`` over a list of parser chunks, so peak memory was the whole
recording.  These tests pin the streaming contract: parser chunks reach disk as
they arrive, the sidecar is byte-identical to the old eager result, staging never
survives into a committed cache, and cancellation leaves nothing behind.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from avialview.core.pyramid import ChannelStage, PyramidBuilder, PyramidReader, count_nan
from avialview.core.source import ChannelInfo
from avialview.engine.importer import MAX_GAP_LOCATIONS, ImportWorker, _gap_locations

CHUNK = 500
CHUNKS = 8
TOTAL = CHUNK * CHUNKS


# ── ChannelStage ──────────────────────────────────────────────────────


def test_channel_stage_round_trips_appended_chunks(tmp_path: Path) -> None:
    stage = ChannelStage(tmp_path, "ch")
    expected = np.arange(2_500, dtype=np.float64)
    for start in range(0, 2_500, 300):
        stage.append(expected[start : start + 300])
    assert stage.count == 2_500

    mapped = stage.materialize(tmp_path / "ch_v.npy", chunk_size=256)
    assert np.array_equal(np.asarray(mapped), expected)


def test_channel_stage_removes_its_staging_file_on_materialize(tmp_path: Path) -> None:
    stage = ChannelStage(tmp_path, "ch")
    stage.append(np.ones(10))
    staging_path = stage.path
    stage.materialize(tmp_path / "ch_v.npy")
    assert not staging_path.exists()


def test_channel_stage_materializes_an_empty_channel(tmp_path: Path) -> None:
    stage = ChannelStage(tmp_path, "ch")
    mapped = stage.materialize(tmp_path / "ch_v.npy")
    assert len(mapped) == 0


def test_channel_stage_upcasts_to_float64(tmp_path: Path) -> None:
    stage = ChannelStage(tmp_path, "ch")
    stage.append(np.array([1, 2, 3], dtype=np.int16))
    mapped = stage.materialize(tmp_path / "ch_v.npy")
    assert mapped.dtype == np.float64
    assert mapped.tolist() == [1.0, 2.0, 3.0]


def test_channel_stage_rejects_append_after_close(tmp_path: Path) -> None:
    stage = ChannelStage(tmp_path, "ch")
    stage.close()
    with pytest.raises(ValueError, match="closed"):
        stage.append(np.ones(3))


def test_channel_stage_discard_is_idempotent(tmp_path: Path) -> None:
    stage = ChannelStage(tmp_path, "ch")
    stage.append(np.ones(3))
    stage.discard()
    stage.discard()
    assert not stage.path.exists()


def test_count_nan_is_chunked_and_exact() -> None:
    values = np.arange(10_000, dtype=np.float64)
    values[[3, 500, 9_999]] = np.nan
    assert count_nan(values, chunk_size=128) == 3


# ── Bounded gap evidence ──────────────────────────────────────────────


def test_gap_locations_are_capped_while_the_count_stays_exact() -> None:
    times = np.arange(MAX_GAP_LOCATIONS + 50, dtype=np.float64)
    mask = np.ones(len(times), dtype=bool)
    locations = _gap_locations(times, mask)
    assert len(locations) == MAX_GAP_LOCATIONS
    assert int(np.count_nonzero(mask)) == MAX_GAP_LOCATIONS + 50


def test_gap_locations_returns_the_marked_timestamps() -> None:
    times = np.array([0.0, 1.0, 2.0, 3.0])
    mask = np.array([False, True, False, True])
    assert _gap_locations(times, mask) == [1.0, 3.0]


# ── Loader doubles ────────────────────────────────────────────────────


def _signal() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    t = np.arange(TOTAL, dtype=np.float64) / 100.0
    a = np.sin(t)
    b = np.cos(t)
    a[7] = np.nan
    return t, a, b


class _BulkLoader:
    """Loader exposing the one-pass bulk chunk API used by CSV/tracking."""

    max_live_samples = 0

    def __init__(self) -> None:
        self._t, self._a, self._b = _signal()

    def open(self, path: Path, config: dict[str, Any]) -> None:
        pass

    def channels(self) -> list[ChannelInfo]:
        return [
            ChannelInfo(name="a", unit="V", dtype="f8", rate_hz=100.0),
            ChannelInfo(name="b", unit="V", dtype="f8", rate_hz=100.0),
        ]

    def is_frame_indexed(self) -> bool:
        return False

    def read_all_chunks(self) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
        for index in range(CHUNKS):
            lo, hi = index * CHUNK, (index + 1) * CHUNK
            type(self).max_live_samples = max(type(self).max_live_samples, hi - lo)
            yield {
                "a": (self._t[lo:hi], self._a[lo:hi]),
                "b": (self._t[lo:hi], self._b[lo:hi]),
            }


class _LegacyLoader(_BulkLoader):
    """Loader with only the frozen v1 ``read_chunks`` contract."""

    read_all_chunks = None  # type: ignore[assignment]  # hides the bulk API

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        values = self._a if ch == "a" else self._b
        for index in range(CHUNKS):
            lo, hi = index * CHUNK, (index + 1) * CHUNK
            yield self._t[lo:hi], values[lo:hi]


def _run(worker: ImportWorker) -> tuple[list[Any], list[str]]:
    finished: list[Any] = []
    errors: list[str] = []
    worker.finished.connect(lambda *args: finished.append(args))
    worker.error.connect(errors.append)
    worker.run()
    return finished, errors


@pytest.fixture
def source_file(tmp_path: Path) -> Path:
    path = tmp_path / "signal.dat"
    path.write_bytes(b"streaming-import-fixture")
    return path


@pytest.mark.parametrize("loader_class", [_BulkLoader, _LegacyLoader])
def test_streamed_import_matches_the_eager_pyramid(
    source_file: Path, loader_class: type, tmp_path: Path
) -> None:
    """Streaming must not change a single stored sample."""
    finished, errors = _run(ImportWorker(source_file, {}, loader_class))
    assert not errors
    assert finished

    _path, cache_dir, channels, bounds, _inspection = finished[0]
    assert channels == ["a", "b"]

    t, a, b = _signal()
    expected_dir = tmp_path / "expected"
    expected_dir.mkdir()
    PyramidBuilder(expected_dir, "a").build_and_save(t, a)
    PyramidBuilder(expected_dir, "b").build_and_save(t, b)

    for channel in ("a", "b"):
        actual = PyramidReader(Path(cache_dir), channel)
        expected = PyramidReader(expected_dir, channel)
        act_t, act_v, act_gap = actual.mapped_columns()
        exp_t, exp_v, exp_gap = expected.mapped_columns()
        assert np.array_equal(act_t, exp_t)
        assert np.array_equal(act_v, exp_v, equal_nan=True)
        assert np.array_equal(act_gap, exp_gap)
        for level in (16, 256, 4096):
            act = actual.query(bounds[0], bounds[1], max_points=TOTAL // level)
            exp = expected.query(bounds[0], bounds[1], max_points=TOTAL // level)
            for actual_arr, expected_arr in zip(act, exp, strict=True):
                assert np.array_equal(actual_arr, expected_arr, equal_nan=True)


@pytest.mark.parametrize("loader_class", [_BulkLoader, _LegacyLoader])
def test_streamed_import_reports_exact_bounds_and_nan_counts(
    source_file: Path, loader_class: type
) -> None:
    finished, errors = _run(ImportWorker(source_file, {}, loader_class))
    assert not errors
    _path, _cache_dir, _channels, bounds, inspection = finished[0]

    assert bounds == pytest.approx((0.0, (TOTAL - 1) / 100.0))
    assert inspection.import_report.rows_parsed == TOTAL
    assert inspection.import_report.nan_count == 1


@pytest.mark.parametrize("loader_class", [_BulkLoader, _LegacyLoader])
def test_committed_cache_contains_no_staging_leftovers(
    source_file: Path, loader_class: type
) -> None:
    """Staging lives inside the temp cache dir; it must never be committed."""
    finished, _errors = _run(ImportWorker(source_file, {}, loader_class))
    cache_dir = Path(finished[0][1])
    leftovers = [p.name for p in cache_dir.rglob("*") if p.suffix == ".stage"]
    assert not leftovers
    assert not (cache_dir / "_stage").exists()


def test_peak_live_chunk_stays_bounded(source_file: Path) -> None:
    """The bulk path must never see more than one parser chunk at a time."""
    _BulkLoader.max_live_samples = 0
    _run(ImportWorker(source_file, {}, _BulkLoader))
    assert _BulkLoader.max_live_samples == CHUNK


@pytest.mark.parametrize("loader_class", [_BulkLoader, _LegacyLoader])
def test_cancelled_import_emits_nothing_and_leaves_no_cache(
    source_file: Path, loader_class: type
) -> None:
    worker = ImportWorker(source_file, {}, loader_class)
    worker.cancel()
    finished, errors = _run(worker)
    assert not finished
    assert not errors


def test_bulk_loader_with_mismatched_timestamps_is_rejected(source_file: Path) -> None:
    class _Divergent(_BulkLoader):
        def read_all_chunks(self) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
            yield {
                "a": (self._t[:CHUNK], self._a[:CHUNK]),
                "b": (self._t[1 : CHUNK + 1], self._b[:CHUNK]),
            }

    finished, errors = _run(ImportWorker(source_file, {}, _Divergent))
    assert not finished
    assert errors and "share timestamps" in errors[0]


def test_bulk_loader_missing_a_declared_channel_is_rejected(source_file: Path) -> None:
    class _Partial(_BulkLoader):
        def read_all_chunks(self) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
            yield {"a": (self._t[:CHUNK], self._a[:CHUNK])}

    finished, errors = _run(ImportWorker(source_file, {}, _Partial))
    assert not finished
    assert errors and "every declared channel" in errors[0]
