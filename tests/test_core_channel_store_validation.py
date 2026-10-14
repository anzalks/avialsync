"""Validate legacy cached column headers and external storage before reuse."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from avialsync.core.channel_store import (
    ExternalArray,
    Layout,
    columns_intact,
    external_files_intact,
    read_level,
    safe_save,
    write_layout,
    write_times,
)
from avialsync.core.columns import RegularTimes


def _columns(root: Path, regular: bool = False) -> None:
    times = RegularTimes(0.0, 1.0, 4) if regular else np.arange(4.0)
    write_times(root, "signal", times)
    np.save(root / "signal_v.npy", np.arange(4.0))
    write_times(root, "signal_pyr_2", times.level(2) if regular else times[::2])
    np.save(root / "signal_pyr_2_vmin.npy", np.array([0.0, 2.0]))
    np.save(root / "signal_pyr_2_vmax.npy", np.array([1.0, 3.0]))


@pytest.mark.parametrize("regular", [True, False])
def test_headers_validate_without_mapping_sample_arrays(tmp_path: Path, regular: bool) -> None:
    _columns(tmp_path, regular)
    assert columns_intact(tmp_path, "signal", [1, 2])
    assert columns_intact(tmp_path, "signal", [1, 2], {p.name for p in tmp_path.iterdir()})


@pytest.mark.parametrize(
    ("name", "values"),
    [
        ("signal_t.npy", np.arange(4, dtype=np.float32)),
        ("signal_t.npy", np.zeros((2, 2))),
        ("signal_v.npy", np.arange(3.0)),
        ("signal_v.npy", np.array(["a"] * 4)),
        ("signal_pyr_2_vmin.npy", np.arange(1.0)),
        ("signal_pyr_2_vmax.npy", np.array(["a", "b"])),
        ("signal_pyr_2_t.npy", np.arange(3.0)),
        ("signal_gap.npy", np.zeros(4, dtype=np.int8)),
        ("signal_gap.npy", np.zeros(3, dtype=bool)),
    ],
)
def test_inconsistent_shape_dtype_or_gaps_are_not_trusted(
    tmp_path: Path, name: str, values: np.ndarray
) -> None:
    _columns(tmp_path)
    np.save(tmp_path / name, values)
    assert not columns_intact(tmp_path, "signal", [1, 2])


@pytest.mark.parametrize("name", ["signal_t.npy", "signal_v.npy", "signal_pyr_2_vmax.npy"])
def test_missing_columns_are_not_trusted(tmp_path: Path, name: str) -> None:
    _columns(tmp_path)
    (tmp_path / name).unlink()
    assert not columns_intact(tmp_path, "signal", [1, 2])


def test_valid_boolean_gaps_and_empty_recordings(tmp_path: Path) -> None:
    _columns(tmp_path)
    np.save(tmp_path / "signal_gap.npy", np.array([False, True, False, False]))
    assert columns_intact(tmp_path, "signal", [1, 2])
    np.save(tmp_path / "signal_t.npy", np.array([], dtype=float))
    np.save(tmp_path / "signal_v.npy", np.array([], dtype=float))
    assert not columns_intact(tmp_path, "signal", [1])


def test_external_times_values_and_change_detection(tmp_path: Path) -> None:
    times, values = tmp_path / "times.dat", tmp_path / "values.dat"
    np.arange(4.0).tofile(times)
    np.arange(4, dtype=np.int16).tofile(values)
    directory = tmp_path / "cache"
    directory.mkdir()
    layout = Layout(
        times=ExternalArray.describe(times, float, 0, (4,)),
        values=ExternalArray.describe(values, np.int16, 0, (4,)),
        scales=(2.0,),
        offset=1.0,
    )
    write_layout(directory, "signal", layout)
    assert external_files_intact(directory, "signal")
    assert columns_intact(directory, "signal", [1])
    t, v, _, _ = read_level(directory, "signal", 1)
    np.testing.assert_array_equal(t, np.arange(4.0))
    np.testing.assert_array_equal(v, np.arange(4.0) * 2.0 + 1.0)
    # Release mmap views before deletion on Windows.
    del t, v
    values.unlink()
    assert not external_files_intact(directory, "signal")
    assert not columns_intact(directory, "signal", [1])


def test_corrupt_layout_and_unreadable_headers_fail_validation(tmp_path: Path) -> None:
    (tmp_path / "signal_layout.json").write_text("not JSON")
    assert not external_files_intact(tmp_path, "signal")
    assert not columns_intact(tmp_path, "signal", [1])
    (tmp_path / "signal_layout.json").unlink()
    (tmp_path / "signal_t.npy").write_bytes(b"broken header")
    assert not columns_intact(tmp_path, "signal", [1])


def test_version_two_npy_headers_are_supported(tmp_path: Path) -> None:
    _columns(tmp_path)
    with (tmp_path / "signal_v.npy").open("wb") as handle:
        np.lib.format.write_array(handle, np.arange(4.0), version=(2, 0))
    assert columns_intact(tmp_path, "signal", [1, 2])


def test_interrupted_array_write_recovers_through_memmap(tmp_path: Path, monkeypatch) -> None:
    def interrupted(*_args, **_kwargs) -> None:
        raise InterruptedError("signal during fwrite")

    monkeypatch.setattr(np, "save", interrupted)
    path = tmp_path / "saved.npy"
    values = np.array([1.0, np.nan, 3.0])
    safe_save(path, values)
    np.testing.assert_array_equal(np.load(path), values)
