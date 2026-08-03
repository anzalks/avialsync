"""Bounded pyramid read API and the guard that keeps ``_load_level`` private.

Trap 13: ``PyramidReader._load_level`` used to be called from readout, tracking,
synchronization, export, and plot construction.  Every one of those callers could
materialise a whole recording.  Reads now go through the explicit bounded API and
this module keeps that boundary enforced.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from avialsync.core.pyramid import RAW_CHUNK_SAMPLES, PyramidBuilder, PyramidReader

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "avialsync"


@pytest.fixture
def reader(tmp_path: Path) -> PyramidReader:
    """A 5 000-sample channel at 100 Hz starting at t=10.0."""
    t = 10.0 + np.arange(5_000, dtype=np.float64) / 100.0
    v = np.sin(t)
    PyramidBuilder(tmp_path, "ch0").build_and_save(t, v)
    return PyramidReader(tmp_path, "ch0")


@pytest.fixture
def empty_reader(tmp_path: Path) -> PyramidReader:
    PyramidBuilder(tmp_path, "empty").build_and_save(
        np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    )
    return PyramidReader(tmp_path, "empty")


# ── Guard ─────────────────────────────────────────────────────────────


def _private_level_calls(path: Path) -> list[int]:
    """Return line numbers of ``<expr>._load_level(...)`` calls in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_load_level"
    ]


def test_only_pyramid_module_calls_load_level() -> None:
    """No production module outside core/pyramid.py may reach past the read API."""
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if path.name == "pyramid.py" and path.parent.name == "core":
            continue
        for lineno in _private_level_calls(path):
            offenders.append(f"{path.relative_to(SRC_ROOT.parent.parent)}:{lineno}")
    assert not offenders, (
        "PyramidReader._load_level is private (Trap 13). Use coverage(), "
        "sample_at(), value_at(), raw_slice(), iter_raw_chunks(), or "
        "mapped_columns() instead. Offenders: " + ", ".join(offenders)
    )


# ── coverage / sample_count ───────────────────────────────────────────


def test_coverage_returns_first_and_last_timestamp(reader: PyramidReader) -> None:
    assert reader.coverage() == pytest.approx((10.0, 10.0 + 4_999 / 100.0))


def test_coverage_of_empty_channel_is_none(empty_reader: PyramidReader) -> None:
    assert empty_reader.coverage() is None


def test_sample_count(reader: PyramidReader, empty_reader: PyramidReader) -> None:
    assert reader.sample_count() == 5_000
    assert empty_reader.sample_count() == 0


# ── sample_at ─────────────────────────────────────────────────────────


def test_sample_at_returns_last_sample_at_or_before_target(reader: PyramidReader) -> None:
    index, value = reader.sample_at(10.0 + 42 / 100.0)
    assert index == 42
    assert value == pytest.approx(np.sin(10.0 + 42 / 100.0))


def test_sample_at_between_samples_takes_the_earlier_one(reader: PyramidReader) -> None:
    index, _ = reader.sample_at(10.0 + 42.9 / 100.0)
    assert index == 42


def test_sample_at_clamps_outside_coverage(reader: PyramidReader) -> None:
    assert reader.sample_at(0.0)[0] == 0
    assert reader.sample_at(1e9)[0] == 4_999


def test_sample_at_on_empty_channel_is_none(empty_reader: PyramidReader) -> None:
    assert empty_reader.sample_at(1.0) is None


# ── raw_slice ─────────────────────────────────────────────────────────


def test_raw_slice_is_bounded_to_the_request(reader: PyramidReader) -> None:
    t, v, gap = reader.raw_slice(20.0, 21.0)
    assert len(t) == len(v) == len(gap)
    assert 0 < len(t) < 5_000
    assert t[0] >= 20.0
    assert t[-1] <= 21.0


def test_raw_slice_is_inclusive_of_both_endpoints(reader: PyramidReader) -> None:
    t, _, _ = reader.raw_slice(10.0, 10.02)
    assert t.tolist() == pytest.approx([10.0, 10.01, 10.02])


def test_raw_slice_outside_coverage_is_empty(reader: PyramidReader) -> None:
    t, v, gap = reader.raw_slice(1e6, 1e7)
    assert len(t) == len(v) == len(gap) == 0


def test_raw_slice_returns_views_not_copies(reader: PyramidReader) -> None:
    """A slice must not allocate a recording-sized array."""
    t, _, _ = reader.raw_slice(20.0, 21.0)
    assert t.base is not None


# ── iter_raw_chunks ───────────────────────────────────────────────────


def test_iter_raw_chunks_covers_everything_exactly_once(reader: PyramidReader) -> None:
    times = np.concatenate([chunk[0] for chunk in reader.iter_raw_chunks(chunk_size=512)])
    values = np.concatenate([chunk[1] for chunk in reader.iter_raw_chunks(chunk_size=512)])
    assert len(times) == 5_000
    assert np.array_equal(times, reader.mapped_columns()[0])
    assert np.array_equal(values, reader.mapped_columns()[1])


def test_iter_raw_chunks_respects_the_size_bound(reader: PyramidReader) -> None:
    sizes = [len(chunk[0]) for chunk in reader.iter_raw_chunks(chunk_size=512)]
    assert max(sizes) <= 512
    assert sum(sizes) == 5_000


def test_iter_raw_chunks_honours_a_time_range(reader: PyramidReader) -> None:
    chunks = list(reader.iter_raw_chunks(chunk_size=512, t0=20.0, t1=21.0))
    times = np.concatenate([chunk[0] for chunk in chunks])
    assert times[0] >= 20.0
    assert times[-1] <= 21.0
    assert len(times) == 101


def test_iter_raw_chunks_rejects_a_non_positive_bound(reader: PyramidReader) -> None:
    with pytest.raises(ValueError, match="chunk_size must be positive"):
        list(reader.iter_raw_chunks(chunk_size=0))


def test_iter_raw_chunks_on_empty_channel_yields_nothing(
    empty_reader: PyramidReader,
) -> None:
    assert list(empty_reader.iter_raw_chunks()) == []


def test_default_chunk_bound_is_exported() -> None:
    assert RAW_CHUNK_SAMPLES == 1_000_000


# ── mapped_columns ────────────────────────────────────────────────────


def test_mapped_columns_returns_three_aligned_mmap_views(reader: PyramidReader) -> None:
    t, v, gap = reader.mapped_columns()
    assert len(t) == len(v) == len(gap) == 5_000
    assert gap.dtype == np.bool_
