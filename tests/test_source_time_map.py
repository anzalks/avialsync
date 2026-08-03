"""Every time-series source gets the same TimeMap treatment as video (P3.5 P0).

A sensor recorded on an independent clock is aligned by changing its mapping,
never by rewriting cached samples.  These tests cover the headless mapping layer,
the plot/readout/export consumers that read through it, and session round-trip.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.pyramid import PyramidBuilder, PyramidReader
from avialsync.core.session import SensorEntry, SessionState
from avialsync.core.timeline import TimeMap

RATE_HZ = 100.0
COUNT = 4_000
OFFSET = 12.5


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """One channel spanning source time [0, 39.99] s."""
    t = np.arange(COUNT, dtype=np.float64) / RATE_HZ
    PyramidBuilder(tmp_path, "sig").build_and_save(t, t * 2.0)
    return tmp_path


@pytest.fixture
def identity(cache_dir: Path) -> MappedChannelReader:
    return MappedChannelReader(PyramidReader(cache_dir, "sig"))


@pytest.fixture
def shifted(cache_dir: Path) -> MappedChannelReader:
    """Source time runs OFFSET seconds ahead of master time."""
    return MappedChannelReader(PyramidReader(cache_dir, "sig"), TimeMap(offset=OFFSET))


# ── TimeMap vector helpers ────────────────────────────────────────────


def test_to_master_array_matches_the_scalar_conversion() -> None:
    time_map = TimeMap(offset=3.0, drift_ppm=250.0)
    source = np.linspace(0.0, 100.0, 41)
    expected = [time_map.to_master(value) for value in source]
    assert time_map.to_master_array(source) == pytest.approx(expected)


def test_to_source_array_matches_the_scalar_conversion() -> None:
    time_map = TimeMap(offset=-2.5, drift_ppm=-80.0)
    master = np.linspace(0.0, 100.0, 41)
    expected = [time_map.to_source(value) for value in master]
    assert time_map.to_source_array(master) == pytest.approx(expected)


def test_array_conversions_round_trip() -> None:
    time_map = TimeMap(offset=7.25, drift_ppm=1_000.0)
    master = np.linspace(0.0, 500.0, 101)
    assert time_map.to_master_array(time_map.to_source_array(master)) == pytest.approx(master)


def test_array_conversion_uses_accepted_exact_evidence() -> None:
    time_map = TimeMap()
    time_map.set_exact_mapping(np.array([0.0, 10.0]), np.array([5.0, 25.0]))
    assert time_map.to_source_array(np.array([0.0, 5.0, 10.0])) == pytest.approx([5.0, 15.0, 25.0])


# ── MappedChannelReader ───────────────────────────────────────────────


def test_identity_mapping_matches_the_underlying_reader(
    identity: MappedChannelReader, cache_dir: Path
) -> None:
    plain = PyramidReader(cache_dir, "sig")
    assert identity.coverage() == pytest.approx(plain.coverage())
    assert identity.sample_at(10.0) == plain.sample_at(10.0)
    assert identity.sample_count() == plain.sample_count()


def test_coverage_is_reported_in_master_time(shifted: MappedChannelReader) -> None:
    t0, t1 = shifted.coverage()
    assert t0 == pytest.approx(-OFFSET)
    assert t1 == pytest.approx((COUNT - 1) / RATE_HZ - OFFSET)


def test_sample_at_maps_the_query_into_source_time(shifted: MappedChannelReader) -> None:
    """Master t must select the sample stored at source time t + OFFSET."""
    index, value = shifted.sample_at(5.0)
    assert index == int(round((5.0 + OFFSET) * RATE_HZ))
    assert value == pytest.approx((5.0 + OFFSET) * 2.0)


def test_value_at_maps_the_query_into_source_time(shifted: MappedChannelReader) -> None:
    assert shifted.value_at(5.0) == pytest.approx((5.0 + OFFSET) * 2.0)


def test_raw_slice_returns_master_timestamps(shifted: MappedChannelReader) -> None:
    t, v, _gap = shifted.raw_slice(5.0, 6.0)
    assert len(t) == len(v) > 0
    assert t[0] == pytest.approx(5.0, abs=1 / RATE_HZ)
    assert t[-1] == pytest.approx(6.0, abs=1 / RATE_HZ)
    # Values still come from the source samples under those master times.
    assert v[0] == pytest.approx((5.0 + OFFSET) * 2.0, abs=0.05)


def test_query_returns_master_timestamps(shifted: MappedChannelReader) -> None:
    t, _vmin, _vmax, _gap = shifted.query(0.0, 20.0, max_points=64)
    assert len(t) > 0
    assert t[0] >= 0.0 - 1 / RATE_HZ
    assert t[-1] <= 20.0 + 1 / RATE_HZ


def test_iter_raw_chunks_returns_master_timestamps_and_stays_bounded(
    shifted: MappedChannelReader,
) -> None:
    chunks = list(shifted.iter_raw_chunks(chunk_size=256, t0=0.0, t1=10.0))
    assert chunks
    assert max(len(chunk[0]) for chunk in chunks) <= 256
    times = np.concatenate([chunk[0] for chunk in chunks])
    assert times[0] == pytest.approx(0.0, abs=1 / RATE_HZ)
    assert times[-1] == pytest.approx(10.0, abs=1 / RATE_HZ)


def test_mapped_columns_stay_in_source_time(shifted: MappedChannelReader) -> None:
    """Converting a whole recording would copy it; the scalar query is mapped."""
    t, _v, _gap = shifted.mapped_columns()
    assert t[0] == pytest.approx(0.0)


def test_set_mapping_remaps_in_place_without_reopening(shifted: MappedChannelReader) -> None:
    before = shifted.sample_at(5.0)
    shifted.set_mapping(0.0, 0.0)
    after = shifted.sample_at(5.0)
    assert before != after
    assert after[0] == int(round(5.0 * RATE_HZ))


def test_drift_is_applied_to_the_query(cache_dir: Path) -> None:
    reader = MappedChannelReader(
        PyramidReader(cache_dir, "sig"), TimeMap(offset=0.0, drift_ppm=10_000.0)
    )
    # 1 % faster source clock: master t=10 lands at source t=10.1.
    index, _value = reader.sample_at(10.0)
    assert index == pytest.approx(int(10.1 * RATE_HZ), abs=1)


# ── Session persistence ───────────────────────────────────────────────


def test_sensor_mapping_survives_a_session_round_trip(tmp_path: Path) -> None:
    state = SessionState(sensors=[SensorEntry(path="/tmp/a.csv", offset=1.25, drift_ppm=-40.0)])
    path = tmp_path / "s.avv"
    state.save(path)
    restored = SessionState.load(path)
    assert restored.sensors[0].offset == pytest.approx(1.25)
    assert restored.sensors[0].drift_ppm == pytest.approx(-40.0)


def test_pre_v6_sensor_entries_default_to_the_identity_mapping() -> None:
    state = SessionState.from_dict(
        {"version": 5, "sensors": [{"path": "/tmp/a.csv", "channels": ["x"]}]}
    )
    assert state.sensors[0].offset == 0.0
    assert state.sensors[0].drift_ppm == 0.0
