"""Edge-case coverage for core scale-up, storage, alignment, and calibration paths."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from avialsync.core import (
    alignment,
    cache_store,
    channel_store,
    edit_cache,
    pose_export,
    prop_motion_calibration,
    session_io,
    triggers,
)
from avialsync.core.commands import SetChannelGroupVisibleCommand
from avialsync.core.edit_program import EditProgram
from avialsync.core.errors import ExportError, PropMotionCalibrationError
from avialsync.core.identity_swaps import SwapEvent, SwapGroup, SwapStore
from avialsync.core.pyramid import ChannelStage, PyramidBuilder
from avialsync.core.sync import SyncMatch
from avialsync.engine.export import export_data_slice_csv
from tests.test_core_motion_fit_validation import _ball, _belt
from tests.wheel_fixture import CAMERAS


def test_subsample_matches_preserves_short_sets_and_endpoints() -> None:
    short = tuple(SyncMatch(float(i), float(i), 0.0) for i in range(3))
    assert alignment.subsample_matches(short, limit=5) == short

    many = tuple(SyncMatch(float(i), float(i * 2), 0.0) for i in range(10))
    sampled = alignment.subsample_matches(many, limit=4)
    assert len(sampled) == 4
    assert sampled[0] == many[0]
    assert sampled[-1] == many[-1]


def test_tree_size_handles_missing_roots_and_symlinks(tmp_path: Path) -> None:
    assert cache_store._tree_size(tmp_path / "does_not_exist") == 0
    real_file = tmp_path / "real.bin"
    real_file.write_bytes(b"abcd")
    link = tmp_path / "link.bin"
    try:
        link.symlink_to(real_file)
    except OSError:
        pytest.skip("Symlinks unavailable on this filesystem")
    assert cache_store._tree_size(tmp_path) == 4


def test_channel_store_stem_edge_cases() -> None:
    assert channel_store.safe_channel_stem("") == "%~"
    assert channel_store._ensure_safe_stem("%~") == "%~"
    assert channel_store._ensure_safe_stem("trail.") == "trail%2E"
    assert channel_store._ensure_safe_stem("a/b") == "a%2Fb"


def test_group_visibility_command_falls_back_to_per_channel_target() -> None:
    calls: list[tuple[str, str, bool]] = []
    target = SimpleNamespace(set_channel_visible=lambda src, ch, vis: calls.append((src, ch, vis)))
    cmd = SetChannelGroupVisibleCommand("sensor.csv", "Acc", {"x": True, "y": False}, False)
    cmd.apply(target)  # type: ignore[arg-type]
    assert calls == [("sensor.csv", "x", False), ("sensor.csv", "y", False)]
    calls.clear()
    cmd.revert(target)  # type: ignore[arg-type]
    assert calls == [("sensor.csv", "x", True), ("sensor.csv", "y", False)]


def test_edit_cache_grouping_and_out_of_range_corrections(tmp_path: Path) -> None:
    PyramidBuilder(tmp_path, "m1_nose_x").build_and_save(
        np.array([0.0, 1.0]), np.array([10.0, 20.0])
    )
    PyramidBuilder(tmp_path, "m1_nose_y").build_and_save(
        np.array([0.0, 1.0]), np.array([11.0, 21.0])
    )
    PyramidBuilder(tmp_path, "m2_nose_x").build_and_save(
        np.array([0.0, 1.0]), np.array([30.0, 40.0])
    )
    PyramidBuilder(tmp_path, "m2_nose_y").build_and_save(
        np.array([0.0, 1.0]), np.array([31.0, 41.0])
    )
    PyramidBuilder(tmp_path, "ref_x").build_and_save(np.array([0.0, 1.0]), np.array([1.0, 2.0]))
    PyramidBuilder(tmp_path, "ref_y").build_and_save(np.array([0.0, 1.0]), np.array([3.0, 4.0]))

    program = EditProgram(
        source_id="pose.csv",
        boundaries=(1,),
        maps=({"m1_nose": "m2_nose", "m2_nose": "m1_nose"},),
        corrections={
            ("m1_nose", 1): (99.0, 98.0),
            ("ref", 1): (5.0, 6.0),
        },
        fingerprint="fp-edge-test",
    )
    grouped = edit_cache._group_corrections_by_display(program)
    assert grouped["m2_nose"] == [(1, (99.0, 98.0))]
    assert grouped["ref"] == [(1, (5.0, 6.0))]

    _t, vals = edit_cache._edited_values(
        tmp_path,
        program,
        "ref",
        "ref_x",
        0,
        point_corrections=[(-1, (77.0, 88.0)), (0, (42.0, 43.0))],
    )
    assert vals[0] == 42.0


def test_identity_swaps_ragged_groups_and_boundaries() -> None:
    store = SwapStore()
    ragged = SwapGroup(
        "animal",
        ("m1", "m2"),
        ("nose", "tail"),
        (
            ("m1", "nose", "m1_nose"),
            ("m2", "nose", "m2_nose"),
            ("m1", "tail", "m1_tail"),
        ),
    )
    store.set_groups("src.csv", (ragged,))
    store._events["src.csv"] = [
        SwapEvent(index=2, group="unknown_group", lanes=("m1", "m2")),
        SwapEvent(index=2, group="animal", lanes=("m1", "ghost")),
        SwapEvent(index=2, group="animal", lanes=("m1", "m2")),
    ]
    assert store.boundaries("src.csv") == (2,)
    bounds, maps = store.boundary_point_sources("src.csv")
    assert bounds == (2,)
    assert maps == ({"m1_nose": "m2_nose", "m2_nose": "m1_nose"},)


def test_pose_export_reroute_skips_identity_and_missing_donor_fields() -> None:
    columns = {
        ("p1", "x"): 0,
        ("p1", "likelihood"): 1,
        ("p2", "x"): 2,
    }
    row = ["10", "0.9", "20"]
    moved = pose_export._reroute(row, columns, {"p1": "p2", "p2": "p2"})
    assert moved is True
    assert row == ["20", "0.9", "20"]


def test_prop_motion_calibration_error_edges(monkeypatch) -> None:
    belt = _belt()
    ball = _ball()
    with pytest.raises(PropMotionCalibrationError, match="finite"):
        prop_motion_calibration.fit_belt_motion(belt, CAMERAS, reference_reading=float("nan"))
    with pytest.raises(PropMotionCalibrationError, match="belt-motion proposal"):
        prop_motion_calibration.fit_belt_motion(belt, {})
    with pytest.raises(PropMotionCalibrationError, match="ball-motion proposal"):
        prop_motion_calibration.fit_ball_motion(ball, {})

    def fail_ls(*_args, **_kwargs):
        raise PropMotionCalibrationError("transient projection error")

    monkeypatch.setattr(prop_motion_calibration, "least_squares", fail_ls)
    with pytest.raises(PropMotionCalibrationError, match="belt-motion proposal"):
        prop_motion_calibration.fit_belt_motion(belt, CAMERAS)
    with pytest.raises(PropMotionCalibrationError, match="ball-motion proposal"):
        prop_motion_calibration.fit_ball_motion(ball, CAMERAS)


def test_channel_stage_buffered_keep_open_false_and_closed_handle(tmp_path: Path) -> None:
    empty_stage = ChannelStage(tmp_path, "empty_buf", keep_open=False)
    empty_stage.close()
    empty_stage.close()

    open_stage = ChannelStage(tmp_path, "preclosed", keep_open=True)
    open_stage._handle.close()
    open_stage.close()

    stage = ChannelStage(tmp_path, "buffered", keep_open=False)
    stage.append(np.array([1.0, 2.0]))
    stage.append(np.ones(9_000, dtype=np.float64))
    stage.append(np.ones(9_000, dtype=np.float64))
    stage.append(np.ones(5_000, dtype=np.float64))
    stage.append(np.ones(5_000, dtype=np.float64))
    stage.append(np.array([3.0]))
    arr = stage.materialize(tmp_path / "buffered.npy")
    assert len(arr) == 28_003
    assert float(arr[0]) == 1.0
    assert float(arr[-1]) == 3.0


def test_session_io_sidecar_cleanup_and_malformed_provenance(tmp_path: Path, monkeypatch) -> None:
    sidecar_dir = tmp_path / "session_avv_sync"
    sidecar_dir.mkdir()
    stale = sidecar_dir / "exact-sync-old.npz"
    stale.write_bytes(b"stale")
    session_io.prune_exact_sidecars(sidecar_dir, set())
    assert not sidecar_dir.exists()

    readable = tmp_path / "sidecar.npz"
    readable.write_bytes(b"payload")
    monkeypatch.setattr(
        Path, "read_bytes", lambda _self: (_ for _ in ()).throw(OSError("unreadable"))
    )
    assert session_io._reusable_sidecar_digest(readable) is None

    assert session_io.load_exact_sidecars({"sync_provenance": "not-a-list"}, tmp_path) == []
    assert session_io.load_exact_sidecars({"sync_provenance": ["not-a-dict"]}, tmp_path) == []


def test_triggers_empty_integer_and_single_sample_gap_chunks() -> None:
    chunks = [
        (np.array([], dtype=np.float64), np.array([], dtype=np.int16)),
        (np.array([0.0], dtype=np.float64), np.array([np.nan]), np.array([True])),
        (np.array([1.0, 2.0, 3.0], dtype=np.float64), np.array([0, 1, 0], dtype=np.int16)),
    ]
    result = triggers.extract_pulses(
        chunks, source_id="ttl", kind=triggers.TriggerKind.SYNC_TRAIN, threshold=0.5
    )
    assert len(result.times) == 1


def test_export_csv_rejects_mismatched_chunk_lengths(tmp_path: Path) -> None:
    bad_reader = SimpleNamespace(
        source_id="bad.csv",
        channel_id="ch0",
        cache_dir=tmp_path,
        iter_raw_chunks_with_gaps=lambda **_kw: [
            (np.array([0.0, 1.0]), np.array([1.0]), np.array([False, False]))
        ],
    )
    with pytest.raises(ExportError, match="chunk lengths differ"):
        export_data_slice_csv([bad_reader], 0.0, 2.0, tmp_path / "out.csv")
