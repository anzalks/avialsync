"""NWB files: what is found, how it is read, and where it lands in time (D-188)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("h5py")

from avialsync.core.errors import FileUnreadableError, SourceOpenError  # noqa: E402
from avialsync.core.source import display_unit  # noqa: E402
from avialsync.loaders import nwb_format  # noqa: E402
from avialsync.loaders.nwb_loader import NWBLoader, interval_grid, spike_pulses  # noqa: E402
from tests.nwb_fixture import (  # noqa: E402
    EPHYS_CHANNEL_CONVERSION,
    EPHYS_CONVERSION,
    EPHYS_RATE,
    EPHYS_SAMPLES,
    SESSION_EPOCH,
    NWBSpec,
    write_nwb,
    write_nwb1,
)


@pytest.fixture()
def nwb_file(tmp_path: Path) -> Path:
    return write_nwb(tmp_path / "session.nwb")


def _read_all(loader: NWBLoader, channel: str) -> tuple[np.ndarray, np.ndarray]:
    chunks = list(loader.read_chunks(channel))
    return np.concatenate([t for t, _ in chunks]), np.concatenate([v for _, v in chunks])


# ── What a file holds ─────────────────────────────────────────────────────


def test_scan_finds_every_kind_of_object_by_structure(nwb_file: Path) -> None:
    contents = nwb_format.scan(nwb_file)

    by_name = {info.name: info for info in contents.series}
    assert by_name["ElectricalSeries"].kind == "signal"
    assert by_name["Position.SpatialSeries"].kind == "signal"
    assert by_name["TwoPhotonSeries"].kind == "imaging"
    assert by_name["behavior.BehavioralEpochs.reward"].kind == "interval"
    assert by_name["notes"].kind == "annotation"
    assert [table.name for table in contents.interval_tables] == ["trials"]
    assert [table.name for table in contents.units_tables] == ["units"]
    assert contents.reference_epoch == pytest.approx(SESSION_EPOCH)
    assert not contents.reference_is_naive


def test_two_series_of_one_name_keep_apart_by_where_they_sit(nwb_file: Path) -> None:
    """``DfOverF/RoiResponseSeries`` beside ``Fluorescence/RoiResponseSeries``, as in real files."""
    names = {info.name for info in nwb_format.scan(nwb_file).series}

    assert "ophys.DfOverF.RoiResponseSeries" in names
    assert "ophys.Fluorescence.RoiResponseSeries" in names


def test_columns_are_named_after_what_they_measure(nwb_file: Path) -> None:
    by_name = {info.name: info for info in nwb_format.scan(nwb_file).series}

    assert by_name["ElectricalSeries"].columns == ("ch10", "ch11", "ch12", "ch13")
    assert by_name["ophys.DfOverF.RoiResponseSeries"].columns == ("roi3", "roi5", "roi8")
    assert by_name["Position.SpatialSeries"].columns == ("x", "y")


def test_a_declined_series_is_named_with_its_reason(nwb_file: Path) -> None:
    contents = nwb_format.scan(nwb_file)

    assert not any(info.name == "SpikeWaveforms" for info in contents.series)
    assert any("SpikeWaveforms" in reason and "waveforms" in reason for reason in contents.declined)


def test_an_extension_type_is_recognised_through_the_cached_spec(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "ext.nwb", NWBSpec(extension_imaging=True))

    by_name = {info.name: info for info in nwb_format.scan(path).series}

    assert by_name["LabScope"].neurodata_type == "LabScopeSeries"
    assert by_name["LabScope"].kind == "imaging"


def test_nwb1_reads_its_series_and_session_clock(tmp_path: Path) -> None:
    path = write_nwb1(tmp_path / "old.nwb")
    contents = nwb_format.scan(path)
    assert contents.version == "NWB-1.0.6"
    assert contents.reference_epoch == SESSION_EPOCH
    assert {info.name: info.kind for info in contents.series} == {
        "camera": "imaging",
        "voltage": "signal",
    }
    loader = NWBLoader()
    loader.open(path, {})
    times, values = _read_all(loader, "voltage")
    np.testing.assert_allclose(times[:2], [0.25, 0.251])
    np.testing.assert_allclose(values[:2], [0, 1e-6])


def test_plain_hdf5_is_not_mistaken_for_nwb(tmp_path: Path) -> None:
    import h5py

    path = tmp_path / "other.nwb"
    with h5py.File(path, "w") as f:
        f.create_dataset("x", data=[1, 2, 3])
    with pytest.raises(nwb_format.NWBFormatError, match="not NWB"):
        nwb_format.scan(path)


def test_a_file_that_is_not_hdf5_says_so(tmp_path: Path) -> None:
    path = tmp_path / "broken.nwb"
    path.write_bytes(b"not hdf5 at all")
    with pytest.raises(FileUnreadableError, match="HDF5"):
        nwb_format.scan(path)


@pytest.mark.parametrize("zarr_format", [2, 3])
def test_zarr_nwb_reads_series_without_conversion(tmp_path: Path, zarr_format: int) -> None:
    from tests.nwb_fixture import write_zarr_nwb

    folder = write_zarr_nwb(tmp_path / "session.nwb.zarr", zarr_format=zarr_format)
    assert nwb_format.is_zarr_nwb(folder)
    contents = nwb_format.scan(folder)
    assert {info.name: info.kind for info in contents.series} == {
        "camera": "imaging",
        "voltage": "signal",
    }
    loader = NWBLoader()
    loader.open(folder, {})
    times, values = _read_all(loader, "voltage")
    np.testing.assert_allclose(times[:2], [0.25, 0.251])
    np.testing.assert_allclose(values[:2], [0, 1e-6])


@pytest.mark.parametrize(
    ("text", "expected", "naive"),
    [
        ("2024-03-05T10:00:00+00:00", SESSION_EPOCH, False),
        ("2024-03-05T10:00:00Z", SESSION_EPOCH, False),
        ("2024-03-05T11:00:00+01:00", SESSION_EPOCH, False),
        ("2024-03-05T10:00:00", SESSION_EPOCH, True),
    ],
)
def test_session_start_times_parse_with_their_zone(text: str, expected: float, naive: bool) -> None:
    assert nwb_format.parse_iso_time(text) == (pytest.approx(expected), naive)


def test_an_unparseable_time_is_no_epoch() -> None:
    assert nwb_format.parse_iso_time("yesterday") is None
    assert nwb_format.parse_iso_time("") is None


# ── Reading samples ───────────────────────────────────────────────────────


def test_ephys_is_scaled_to_the_declared_unit(nwb_file: Path) -> None:
    """``data * channel_conversion * conversion + offset``, per the schema."""
    loader = NWBLoader()
    loader.open(nwb_file, {})
    units = {info.name: info.unit for info in loader.channels()}
    times, values = _read_all(loader, "ElectricalSeries.ch11")

    assert units["ElectricalSeries.ch11"] == "V"
    assert len(times) == EPHYS_SAMPLES
    assert times[1] - times[0] == pytest.approx(1.0 / EPHYS_RATE)
    raw = np.arange(EPHYS_SAMPLES) * 2
    np.testing.assert_allclose(values, raw * EPHYS_CHANNEL_CONVERSION[1] * EPHYS_CONVERSION)


def test_each_series_is_one_group_on_its_own_clock(nwb_file: Path) -> None:
    """One pass over a 2-D series' rows, and one timestamp array for its columns."""
    loader = NWBLoader()
    loader.open(nwb_file, {})
    groups = {tuple(names): list(chunks) for names, chunks in loader.iter_channel_groups()}

    ephys = groups[
        (
            "ElectricalSeries.ch10",
            "ElectricalSeries.ch11",
            "ElectricalSeries.ch12",
            "ElectricalSeries.ch13",
        )
    ]
    for chunk in ephys:
        times = [chunk[name][0] for name in chunk]
        assert all(t is times[0] for t in times), "columns of one series share one array"
    position = groups[("Position.SpatialSeries.x", "Position.SpatialSeries.y")]
    assert position[0]["Position.SpatialSeries.x"][0][0] == pytest.approx(0.2)
    declared = [info.name for info in loader.channels()]
    assert [name for names in groups for name in names] == declared


def test_out_of_order_timestamps_are_sorted_and_duplicates_keep_the_last(tmp_path: Path) -> None:
    times = np.array([0.0, 0.2, 0.1, 0.3, 0.3, 0.4])
    path = write_nwb(tmp_path / "jumbled.nwb", NWBSpec(position_timestamps=times))
    loader = NWBLoader()
    loader.open(path, {})

    sorted_times, x = _read_all(loader, "Position.SpatialSeries.x")

    np.testing.assert_array_equal(sorted_times, [0.0, 0.1, 0.2, 0.3, 0.4])
    expected = np.sin(np.arange(6) * 0.1)
    np.testing.assert_allclose(x, expected[[0, 2, 1, 4, 5]])


def test_trials_become_a_box_and_a_message_per_row(nwb_file: Path) -> None:
    loader = NWBLoader()
    loader.open(nwb_file, {})
    times, values = _read_all(loader, "trials")

    inside = values[(times > 1.01) & (times < 2.99)]
    between = values[(times > 3.01) & (times < 3.99)]
    assert inside.size and np.all(inside == 1.0)
    assert between.size and np.all(between == 0.0)
    messages = [m for m in loader.messages() if m.channel == "trials"]
    assert [m.time for m in messages] == [1.0, 4.0, 7.0]
    assert "condition=right" in messages[1].text and "correct=no" in messages[1].text


def test_annotations_become_messages(nwb_file: Path) -> None:
    loader = NWBLoader()
    loader.open(nwb_file, {})

    notes = [(m.time, m.text) for m in loader.messages() if m.channel == "notes"]

    assert notes == [(0.1, "start"), (5.0, "lick bout"), (9.5, "end")]


def test_spikes_keep_their_exact_times(nwb_file: Path) -> None:
    loader = NWBLoader()
    loader.open(nwb_file, {})
    names = [info.name for info in loader.channels() if info.name.startswith("units")]

    # Unit 8 never fired: no channel stands for it with nothing behind it.
    assert names == ["units.unit7", "units.unit9"]
    times, values = _read_all(loader, "units.unit9")
    np.testing.assert_array_equal(times[values == 1.0], [0.5, 0.75])


def test_a_short_interval_survives_a_coarse_grid() -> None:
    """A 0.4 ms reward pulse in a long session must still read as on somewhere."""
    starts = np.array([0.0, 50_000.0])
    stops = np.array([1.0, 50_000.0004])

    times, values, rate = interval_grid(starts, stops)

    assert rate < 1000.0
    near = values[np.abs(times - 50_000.0) < 2.0 / rate]
    assert near.max() == 1.0


def test_an_interval_without_a_stop_still_marks_its_start() -> None:
    times, values, _rate = interval_grid(np.array([2.0]), np.array([np.nan]))

    assert values.max() == 1.0
    assert times[np.argmax(values)] == pytest.approx(2.0, abs=2e-3)


def test_reward_interval_series_pairs_its_edges(nwb_file: Path) -> None:
    loader = NWBLoader()
    loader.open(nwb_file, {})
    times, values = _read_all(loader, "behavior.BehavioralEpochs.reward")

    on = times[values == 1.0]
    assert on.min() == pytest.approx(2.0, abs=1e-3)
    assert np.any(np.abs(on - 3.0) < 2e-3), "the 0.4 ms pulse still shows"
    assert not np.any((times > 2.06) & (times < 2.99) & (values == 1.0))


def test_spike_pulses_stay_strictly_increasing_for_close_spikes() -> None:
    times, values = spike_pulses(np.array([1.0, 1.0001, 1.0001, np.nan]))

    assert np.all(np.diff(times) > 0)
    np.testing.assert_array_equal(times[values == 1.0], [1.0, 1.0001])


def test_an_empty_file_is_refused_with_a_reason(tmp_path: Path) -> None:
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
    path = write_nwb(tmp_path / "empty.nwb", spec)

    with pytest.raises(SourceOpenError, match="no time series"):
        NWBLoader().open(path, {})


def test_nwb_unit_spellings_read_as_one_spelling() -> None:
    assert display_unit("volts") == "V"
    assert display_unit("meters") == "m"
    assert display_unit("amperes") == "A"
    assert display_unit("seconds") == "s"
    assert display_unit("n.a.") == ""
    assert display_unit("n/a") == ""
    assert display_unit("cm/s") == "cm/s"
