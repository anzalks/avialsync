"""NWB import benchmarks against the budgets D-188 set (BLUEPRINT.md "Performance budgets").

Three workloads, each the shape real NWB files take:

* **Electrophysiology**: 32 channels at 30 kHz for 60 s (57.6 M samples), int16,
  gzip-compressed in time-major chunks the way NWB writers chunk raw ephys.
* **Calcium traces**: 600 ROIs over 50 000 frames (30 M samples) -- the per-ROI
  matrices that a multi-plane two-photon session stores several times over.
* **Imaging proxy**: 2 000 frames of 512x512 16-bit noise, the incompressible
  worst case for the lossless proxy encoder.

Plus the costs a user pays on every reopen: scanning a file's structure, and
finding the import and the proxy already cached.

Local engineering checks, like every benchmark here; hosted CI does not run them.
"""

from __future__ import annotations

import time
from pathlib import Path

import h5py
import numpy as np
import pytest

from avialsync.loaders import nwb_format
from avialsync.loaders.nwb_imaging import NWBImagingSource
from avialsync.loaders.nwb_loader import NWBLoader
from tests.nwb_fixture import NWBSpec, _region, _series, write_nwb

_EPHYS_IMPORT_BUDGET_S = 10.0
_TRACES_IMPORT_BUDGET_S = 6.0
_PROXY_MIN_FRAMES_PER_S = 100.0
_SCAN_BUDGET_S = 0.25
_CACHED_REOPEN_BUDGET_S = 0.25

_EPHYS = (60 * 30_000, 32)
_TRACES = (50_000, 600)
_FRAMES = (2_000, 512, 512)


def _bare(path: Path) -> Path:
    spec = NWBSpec(
        ephys=False,
        position=False,
        imaging=False,
        fluorescence=False,
        intervals=False,
        trials=False,
        units=False,
        annotations=False,
    )
    return write_nwb(path, spec)


@pytest.fixture(scope="module")
def ephys_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = _bare(tmp_path_factory.mktemp("nwb") / "ephys.nwb")
    rng = np.random.default_rng(0)
    with h5py.File(path, "a") as f:
        group = f["acquisition"].create_group("ElectricalSeries")
        group.attrs["neurodata_type"] = "ElectricalSeries"
        data = group.create_dataset(
            "data", shape=_EPHYS, dtype=np.int16, chunks=(30_000, _EPHYS[1]), compression="gzip"
        )
        for start in range(0, _EPHYS[0], 300_000):
            stop = min(start + 300_000, _EPHYS[0])
            data[start:stop] = rng.integers(-2000, 2000, (stop - start, _EPHYS[1]), dtype=np.int16)
        data.attrs["unit"] = "volts"
        data.attrs["conversion"] = 0.195e-6
        starting = group.create_dataset("starting_time", data=0.0)
        starting.attrs["rate"] = 30_000.0
    return path


@pytest.fixture(scope="module")
def traces_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = _bare(tmp_path_factory.mktemp("nwb") / "traces.nwb")
    rng = np.random.default_rng(1)
    with h5py.File(path, "a") as f:
        module = f["processing"].create_group("ophys")
        dff = module.create_group("DfOverF")
        traces = rng.normal(0, 1, _TRACES).astype(np.float32)
        series = _series(
            dff,
            "RoiResponseSeries",
            "RoiResponseSeries",
            traces,
            "n.a.",
            timestamps=np.arange(_TRACES[0]) / 30.0,
        )
        table = module.create_group("rois")
        table.create_dataset("id", data=np.arange(_TRACES[1]))
        _region(series, "rois", table, list(range(_TRACES[1])))
    return path


@pytest.fixture(scope="module")
def imaging_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = _bare(tmp_path_factory.mktemp("nwb") / "imaging.nwb")
    rng = np.random.default_rng(2)
    with h5py.File(path, "a") as f:
        frames = rng.normal(1500, 300, _FRAMES).clip(0, 65535).astype(np.uint16)
        _series(f["acquisition"], "TwoPhotonSeries", "TwoPhotonSeries", frames, "n.a.", rate=30.0)
    return path


def _import(path: Path) -> float:
    from PySide6.QtCore import QCoreApplication

    from avialsync.engine.importer import ImportWorker

    QCoreApplication.instance() or QCoreApplication([])
    worker = ImportWorker(path, {}, NWBLoader)
    errors: list[str] = []
    worker.error.connect(errors.append)
    started = time.perf_counter()
    worker.run()
    elapsed = time.perf_counter() - started
    assert not errors, errors
    return elapsed


def _clear_cache() -> None:
    import shutil

    from avialsync.core.cache import cache_root

    # The suite's own sandbox (tests/conftest.py), never the user's cache.
    root = cache_root()
    assert "avialsync-cache-" in str(root), root
    shutil.rmtree(root / "sources", ignore_errors=True)


def test_bench_nwb_ephys_import(benchmark, ephys_file: Path) -> None:
    """32 ch x 30 kHz x 60 s, compressed: one pass over the rows, one stored clock."""
    benchmark.pedantic(_import, args=(ephys_file,), setup=_clear_cache, rounds=3)
    assert benchmark.stats["mean"] <= _EPHYS_IMPORT_BUDGET_S


def test_bench_nwb_traces_import(benchmark, traces_file: Path) -> None:
    """600 ROI channels: the per-channel cost of a wide matrix."""
    benchmark.pedantic(_import, args=(traces_file,), setup=_clear_cache, rounds=3)
    assert benchmark.stats["mean"] <= _TRACES_IMPORT_BUDGET_S


def test_bench_nwb_imaging_proxy(benchmark, imaging_file: Path) -> None:
    """Lossless proxy encoding throughput on incompressible 512x512 16-bit frames."""

    def encode() -> None:
        source = NWBImagingSource()
        source.open(imaging_file, {})
        source.prepare(lambda _fraction: None)

    benchmark.pedantic(encode, setup=_clear_cache, rounds=2)
    assert _FRAMES[0] / benchmark.stats["mean"] >= _PROXY_MIN_FRAMES_PER_S


def test_bench_nwb_scan(benchmark, traces_file: Path) -> None:
    benchmark(nwb_format.scan, traces_file)
    assert benchmark.stats["mean"] <= _SCAN_BUDGET_S


def test_bench_nwb_cached_reopen(benchmark, traces_file: Path, imaging_file: Path) -> None:
    """Second open: the import and the proxy are found, not rebuilt."""
    _import(traces_file)
    NWBImagingSource().open(imaging_file, {})
    first = NWBImagingSource()
    first.open(imaging_file, {})
    first.prepare(lambda _fraction: None)

    def reopen() -> None:
        _import(traces_file)
        source = NWBImagingSource()
        source.open(imaging_file, {})
        source.prepare(lambda _fraction: None)

    benchmark(reopen)
    assert benchmark.stats["mean"] <= _CACHED_REOPEN_BUDGET_S
