"""Bounded consumers preserve empty coverage, missing samples and native storage types."""

from pathlib import Path

import numpy as np
import pytest

from avialsync.core import channel_store, pyramid
from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.inspection import SourceInspection
from avialsync.core.pyramid import PyramidBuilder, PyramidReader


def test_empty_reader_has_no_samples_or_mapped_range(tmp_path: Path) -> None:
    PyramidBuilder(tmp_path, "signal").build_and_save(np.array([]), np.array([]))
    reader = MappedChannelReader(PyramidReader(tmp_path, "signal"))
    assert reader.available_sample_at(0) is None
    assert list(reader.iter_raw_chunks(t0=0)) == []
    assert reader.query(0, 1, 100)[0].size == 0


def test_interpolation_does_not_invent_a_finite_successor(tmp_path: Path) -> None:
    PyramidBuilder(tmp_path, "signal").build_and_save(np.array([0.0, 1.0]), np.array([3.0, np.nan]))
    reader = MappedChannelReader(PyramidReader(tmp_path, "signal"))
    assert reader.interpolated_sample_at(0.5) == 3
    assert list(reader.iter_raw_chunks(t0=10)) == []
    with pytest.raises(ValueError, match="positive"):
        list(reader.source_reader.iter_raw_chunks_with_gaps(0))
    assert reader.source_reader.query(10, 20, 100)[0].size == 0


def test_native_integer_envelope_and_storage_conversion_remain_bounded(tmp_path: Path) -> None:
    raw = np.arange(128, dtype=np.int16)
    assert pyramid._order_space(raw) == (raw, None, None)
    assert not pyramid._fits_int16(np.array([32768.0]))
    PyramidBuilder(tmp_path, "signal").build_and_save(np.arange(128.0), raw)
    reader = PyramidReader(tmp_path, "signal")
    times, low, high, _ = reader.query(0, 127, 4)
    assert len(times) <= 4 and low.min() == 0 and high.max() == 127


def test_cold_read_superseded_by_reopen_is_not_cached(tmp_path: Path, monkeypatch) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    for directory, value in [(old, 1), (new, 2)]:
        PyramidBuilder(directory, "signal").build_and_save(np.arange(3.0), np.full(3, value))
    reader = PyramidReader(old, "signal")
    load = pyramid.read_level

    def switch(directory, channel, level):
        result = load(directory, channel, level)
        reader.reopen(new)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(pyramid, "read_level", switch)
        assert reader.mapped_columns()[1][0] == 1
    assert reader.mapped_columns()[1][0] == 2
    reader.close()


def test_metadata_only_layout_and_invalid_unit_override_are_supported(tmp_path: Path) -> None:
    channel_store.write_layout(tmp_path, "signal", channel_store.Layout())
    assert channel_store.load_layout(tmp_path, "signal") == channel_store.Layout()
    inspection = SourceInspection(
        "source", import_config={"units": []}, channel_units={"signal": "V"}
    )
    assert inspection.units() == {"signal": "V"}


@pytest.mark.parametrize("scales", [(-1.0,), (2.0, -1.0), (-1.0, -1.0)])
def test_signed_storage_conversion_preserves_min_max_envelope(tmp_path: Path, scales) -> None:
    PyramidBuilder(tmp_path, "signal").build_and_save(
        np.arange(128.0), np.arange(128, dtype=np.int16)
    )
    channel_store.write_layout(tmp_path, "signal", channel_store.Layout(scales=scales))
    reader = PyramidReader(tmp_path, "signal")
    _, low, high, _ = reader.query(0, 127, 4)
    expected = np.arange(128.0) * np.prod(scales)
    assert low.min() == expected.min() and high.max() == expected.max()
    assert np.all(low <= high)
