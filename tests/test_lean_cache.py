"""The cache stores only what carries information, and reads binary sources in place (D-216).

A regular clock is a grid, but only when every stored timestamp equals it
exactly; a channel without a gap has no gap file; whole numbers are stored in
16 bits; and an Open Ephys or uncompressed NWB recording's samples stay in the
recording, bit-for-bit the values the copying import stored.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

from avialsync.core.channel_store import external_files_intact, read_level
from avialsync.core.columns import RegularTimes, ScaledColumn, fit_regular
from avialsync.core.pyramid import ChannelStage, PyramidBuilder, PyramidReader
from avialsync.engine.importer import ImportWorker
from avialsync.loaders.neo_loader import NeoLoader
from avialsync.loaders.nwb_loader import NWBLoader
from tests.nwb_fixture import write_nwb
from tools.make_fixtures import generate_openephys_binary

# ── verified grids ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "times",
    [
        12.5 + np.arange(20_000) / 30_000.0,  # a loader dividing by its rate
        np.arange(4_211) * 0.001,  # one multiplying by its interval
        np.array([float(f"{10 + i / 100:.2f}") for i in range(2_000)]),  # decimals in a CSV
        1.7e9 + np.arange(30_000) / 30_000.0,  # an epoch clock
    ],
)
def test_a_regular_clock_becomes_a_grid_that_reproduces_it_exactly(times: np.ndarray) -> None:
    grid = fit_regular(times)
    assert grid is not None
    np.testing.assert_array_equal(grid[:], times)
    np.testing.assert_array_equal(RegularTimes.from_record(grid.as_record())[:], times)
    np.testing.assert_array_equal(grid.level(16)[:], times[::16])


@pytest.mark.parametrize(
    "times",
    [
        np.delete(np.arange(1_000) / 100.0, 500),  # a dropped sample
        np.arange(1_000) / 100.0 + np.r_[np.zeros(999), 1e-9],  # one late sample
        np.array([float(f"{i / 30_000:.6f}") for i in range(3_000)]),  # rounded off the grid
    ],
)
def test_times_that_are_not_exactly_regular_are_kept(times: np.ndarray) -> None:
    assert fit_regular(times) is None


def test_a_grid_answers_searchsorted_as_its_array_would() -> None:
    times = 12.5 + np.arange(50_000) / 30_000.0
    grid = fit_regular(times)
    assert grid is not None
    queries = np.r_[
        times[::37], times[::41] + 1e-12, times[::43] - 1e-12, -np.inf, np.inf, np.nan, 0.0, 99.0
    ]
    for side in ("left", "right"):
        np.testing.assert_array_equal(
            np.searchsorted(grid, queries, side=side), np.searchsorted(times, queries, side=side)
        )
        for query in queries[:64]:
            assert np.searchsorted(grid, query, side=side) == np.searchsorted(
                times, query, side=side
            )


# ── what gets stored ────────────────────────────────────────────────────


def test_no_gap_no_gap_file_and_a_gap_is_kept(tmp_path: Path) -> None:
    regular = np.arange(5_000) / 100.0
    PyramidBuilder(tmp_path, "smooth").build_and_save(regular, np.sin(regular))
    assert not (tmp_path / "smooth_gap.npy").exists()
    assert not np.any(PyramidReader(tmp_path, "smooth").mapped_columns()[2])

    broken = regular.copy()
    broken[2_500:] += 10.0
    PyramidBuilder(tmp_path, "broken").build_and_save(broken, np.sin(broken))
    gaps = PyramidReader(tmp_path, "broken").mapped_columns()[2]
    assert (tmp_path / "broken_gap.npy").is_file()
    assert bool(gaps[2_499]) and int(np.count_nonzero(gaps)) == 1


def test_whole_numbers_are_stored_in_16_bits_and_read_back_unchanged(tmp_path: Path) -> None:
    counts = np.random.default_rng(1).integers(-32_768, 32_767, 10_000).astype(np.float64)
    stage = ChannelStage(tmp_path, "adc", allow_float32=True)
    stage.append(counts)
    stage.materialize(tmp_path / "adc_v.npy")
    assert np.load(tmp_path / "adc_v.npy", mmap_mode="r").dtype == np.int16
    np.save(tmp_path / "adc_tgrid.npy", RegularTimes(0.0, 100.0, len(counts)).as_record())
    _t, values, _same, _gap = read_level(tmp_path, "adc", 1)
    np.testing.assert_array_equal(values[:], counts)


def test_fractions_and_nan_are_not_forced_into_16_bits(tmp_path: Path) -> None:
    for name, values in (("half", np.array([0.5, 1.0])), ("nan", np.array([1.0, np.nan]))):
        stage = ChannelStage(tmp_path, name, allow_float32=True)
        stage.append(values)
        stage.materialize(tmp_path / f"{name}_v.npy")
        assert np.load(tmp_path / f"{name}_v.npy").dtype != np.int16


# ── Open Ephys read in place ────────────────────────────────────────────


def _import(path: Path, loader: type) -> Path:
    finished: list[tuple] = []
    errors: list[str] = []
    worker = ImportWorker(path, {}, loader)
    worker.finished.connect(lambda *args: finished.append(args))
    worker.error.connect(errors.append)
    worker.run()
    assert not errors, errors
    return Path(finished[0][1])


def _loader_columns(loader: object, name: str) -> tuple[np.ndarray, np.ndarray]:
    chunks = list(loader.read_all_chunks())  # type: ignore[attr-defined]
    return (
        np.concatenate([chunk[name][0] for chunk in chunks]),
        np.concatenate([chunk[name][1] for chunk in chunks]),
    )


@pytest.fixture
def recording(tmp_path: Path) -> Path:
    root = tmp_path / "oe"
    generate_openephys_binary(root, 2.0)
    return root


def test_open_ephys_samples_stay_in_the_recording(recording: Path) -> None:
    cache = _import(recording, NeoLoader)
    assert not list(cache.glob("*_v.npy")), "no level-1 copy of the samples"
    assert (cache / "CH1_layout.json").is_file()
    loader = NeoLoader()
    loader.open(recording, {})
    for name in ("CH1", "CH4"):
        times, values = _loader_columns(loader, name)
        cached_t, cached_v, gaps = PyramidReader(cache, name).mapped_columns()
        assert isinstance(cached_t, RegularTimes) and isinstance(cached_v, ScaledColumn)
        np.testing.assert_array_equal(cached_t[:], times)
        np.testing.assert_array_equal(cached_v[:], values)
        assert not np.any(gaps)
    raw = sum(path.stat().st_size for path in recording.rglob("continuous.dat"))
    stored = sum(path.stat().st_size for path in cache.iterdir())
    assert stored < raw / 4


def test_in_place_reads_answer_as_the_copied_samples_do(recording: Path, tmp_path: Path) -> None:
    """Plot envelopes reduced from stored counts, and single samples looked up, equal the copy's."""
    cache = _import(recording, NeoLoader)
    loader = NeoLoader()
    loader.open(recording, {})
    times, values = _loader_columns(loader, "CH2")
    copied = tmp_path / "copied"
    copied.mkdir()
    PyramidBuilder(copied, "CH2").build_and_save(times, values)
    in_place, reference = PyramidReader(cache, "CH2"), PyramidReader(copied, "CH2")
    assert isinstance(in_place.mapped_columns()[1], ScaledColumn)
    first, last = float(times[0]), float(times[-1])
    windows = [(first, last), (first + 0.0123, last - 0.0456), (0.5, 0.5004), (0.3, 1.7)]
    for t0, t1 in windows:
        for budget in (1, 7, 300, 1400, 50_000):
            for ours, theirs in zip(
                in_place.query(t0, t1, budget), reference.query(t0, t1, budget), strict=True
            ):
                np.testing.assert_array_equal(np.asarray(ours), np.asarray(theirs))
    for target in np.random.default_rng(3).uniform(first - 1, last + 1, 200):
        assert in_place.sample_at(float(target)) == reference.sample_at(float(target))


def test_one_sample_reads_as_the_whole_column_converts_it() -> None:
    """Single samples come from a table of every 16-bit value; it must agree with the bulk path."""
    raw = np.arange(-32_768, 32_768, dtype=np.int64).astype(np.int16)
    for scales, offset in (((0.195,), 0.0), ((-0.25, 3.0), 1.5)):
        column = ScaledColumn(raw, scales, offset)
        bulk = column[:]
        assert all(column[n] == bulk[n] for n in (0, 1, 32_767, 32_768, -1))
        column[0]  # builds the table
        np.testing.assert_array_equal([column[n] for n in range(0, len(raw), 997)], bulk[::997])


def test_dropped_sample_numbers_date_samples_by_their_numbers(recording: Path) -> None:
    """The header's rate claims a grid; the data's own numbers say a sample went missing."""
    numbers_path = next(recording.rglob("timestamps.npy"))
    numbers = np.load(numbers_path)
    numbers[30_000:] += 1  # one sample number skipped one second in
    np.save(numbers_path, numbers)

    cache = _import(recording, NeoLoader)
    times, _values, gaps = PyramidReader(cache, "CH1").mapped_columns()
    assert not isinstance(times, RegularTimes)
    step = 1.0 / 30_000.0
    assert times[30_000] - times[29_999] == pytest.approx(2 * step)
    assert times[1] - times[0] == pytest.approx(step)


def test_a_changed_recording_is_imported_again(recording: Path) -> None:
    cache = _import(recording, NeoLoader)
    assert external_files_intact(cache, "CH1")
    data = next(recording.rglob("continuous.dat"))
    stat = data.stat()
    os.utime(data, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert not external_files_intact(cache, "CH1")


# ── NWB read in place ───────────────────────────────────────────────────


def test_uncompressed_nwb_series_stay_in_the_file(tmp_path: Path) -> None:
    source = write_nwb(tmp_path / "session.nwb")
    cache = _import(source, NWBLoader)
    assert (cache / "ElectricalSeries.ch10_layout.json").is_file()
    assert not (cache / "ElectricalSeries.ch10_v.npy").exists()
    loader = NWBLoader()
    loader.open(source, {})
    for names, chunks in loader.iter_channel_groups():
        listed = list(chunks)
        for name in names:
            times = np.concatenate([chunk[name][0] for chunk in listed])
            values = np.concatenate([chunk[name][1] for chunk in listed])
            cached_t, cached_v, _gaps = PyramidReader(cache, name).mapped_columns()
            np.testing.assert_array_equal(cached_t[:], times)
            np.testing.assert_array_equal(cached_v[:], values)


def test_a_compressed_nwb_series_is_copied_as_before(tmp_path: Path) -> None:
    source = write_nwb(tmp_path / "session.nwb")
    with h5py.File(source, "r+") as handle:
        group = handle["acquisition/ElectricalSeries"]
        data = group["data"]
        values, attrs = data[()], dict(data.attrs)
        del group["data"]
        squeezed = group.create_dataset("data", data=values, compression="gzip", chunks=True)
        for key, value in attrs.items():
            squeezed.attrs[key] = value
    cache = _import(source, NWBLoader)
    assert (cache / "ElectricalSeries.ch10_v.npy").is_file()
    assert not (cache / "ElectricalSeries.ch10_layout.json").exists()
    shutil.rmtree(cache, ignore_errors=True)
