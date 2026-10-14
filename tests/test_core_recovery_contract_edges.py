"""Sparse and future metadata remain recoverable without inventing routes or observations."""

from pathlib import Path

import numpy as np

from avialsync.core import (
    cache,
    cache_store,
    edit_cache,
    imaging_axes,
    plugin_check,
    pose_export,
    trials,
)
from avialsync.core.commands import ResetSessionCommand, SetImagingLayoutCommand
from avialsync.core.identity_groups import groups_for_schema
from avialsync.core.identity_swaps import SwapEvent, SwapGroup, SwapStore
from avialsync.core.pose import PosePoint, PoseSchema
from avialsync.core.triggers import TriggerKind, extract_pulses
from tests.test_cache_process_leases import _published_entry
from tests.test_document import FakeTarget


def test_commands_without_retained_reset_snapshot_have_no_inverse_data() -> None:
    target = FakeTarget()
    ResetSessionCommand().revert(target)
    command = SetImagingLayoutCommand("source", {}, {"axes": "TYX"})
    command.apply(target)
    assert target.imaging_layouts == {"source": {"axes": "TYX"}}
    command.revert(target)
    assert target.imaging_layouts == {"source": {}}


def test_sparse_or_unknown_identity_lanes_never_duplicate_a_point() -> None:
    group = SwapGroup(
        "animals",
        ("a", "b"),
        ("head", "tail"),
        (("a", "head", "a_head"), ("b", "head", "b_head"), ("b", "tail", "b_tail")),
    )
    store = SwapStore()
    store.add("old", SwapEvent(0, "animals", ("a", "b")))
    store.remap_source("old", "new")
    store.set_groups("new", [group])
    store.add("new", SwapEvent(1, "animals", ("unknown", "other")))
    assert store.point_sources("new", 1) == {"a_head": "b_head", "b_head": "a_head"}
    schema = PoseSchema(
        (
            PosePoint("a", "head", ("x", "y")),
            PosePoint("b", "head", ("x", "y")),
            PosePoint("", "landmark", ("x", "y")),
        ),
        True,
    )
    assert len(groups_for_schema(schema)) == 1
    assert len(imaging_axes.axis_choices((10, 3, 20, 512, 512))) == 6


def test_missing_interval_helpers_preserve_stream_edges_and_infer_only_observed_spacing() -> None:
    assert trials._empty_stretches(0, 20, np.array([2.0, 3.0, 4.0]), 0) == [(5.0, 20.0)]
    assert trials._empty_stretches(0, 10, np.array([2.0]), -1) == [(0.0, 2.0), (1.0, 10.0)]
    assert all(a < b for a, b in trials._empty_stretches(0, 10, np.array([4.0, 2.0]), -1))
    assert trials.stream_spans((0, 10), [(0, 2), (8, 10)]) == [(2, 8)]
    train = extract_pulses(
        [(np.arange(3.0), np.ones(3), np.array([True, False, False]))],
        source_id="clock",
        kind=TriggerKind.FRAME_STROBE,
    )
    assert not len(train.times) and train.incomplete_count >= 1


def test_fresh_small_cache_is_retained_when_disk_budget_is_not_exceeded(tmp_path: Path) -> None:
    _, _, entry = _published_entry(tmp_path)
    root = entry.parent.parent
    assert cache_store.trim_cache(root, max_age_days=30).removed == 0


def test_source_tree_changed_to_directory_is_not_opened_as_a_file(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    child = source / "changed"
    child.write_text("contents")
    is_file = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda path: False if path == child else is_file(path))
    assert cache.CacheManager()._hash_file_edges(source)


def test_failed_edited_generation_retirement_keeps_every_array(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    generation = tmp_path / "edited" / "generation"
    generation.mkdir(parents=True)
    edit_cache._write_manifest(generation, "generation", [], None)

    def denied(*args):
        raise PermissionError("live mmap")

    monkeypatch.setattr(edit_cache.os, "rename", denied)
    assert edit_cache.prune(tmp_path, [], generations=0) == []
    assert generation.is_dir() and "Could not retire" in caplog.text


def test_short_donor_and_three_dimensional_edits_keep_unavailable_axes(tmp_path: Path) -> None:
    from avialsync.core.edit_program import EditProgram
    from avialsync.core.pyramid import PyramidBuilder

    for name, values in [
        ("head_x", np.arange(4.0)),
        ("head_y", np.arange(4.0)),
        ("donor_x", np.arange(1.0)),
        ("head_z", np.arange(4.0)),
    ]:
        PyramidBuilder(tmp_path, name).build_and_save(np.arange(len(values), dtype=float), values)
    program = EditProgram("source", (2,), ({"head": "donor"},), {}, "fixture")
    _, values = edit_cache._edited_values(tmp_path, program, "head", "head_x", 0)
    np.testing.assert_array_equal(values, np.arange(4.0))
    direct = EditProgram("source", (), (), {("head", 0): (9, 8)}, "second")
    destination = tmp_path / "output"
    destination.mkdir()
    assert edit_cache._write_point(
        tmp_path, destination, direct, PosePoint("", "head", ("x", "y", "z"))
    ) == ["head_x", "head_y", "head_z"]


def test_ragged_stream_preserves_unaddressable_corrections_in_its_report(tmp_path: Path) -> None:
    report = pose_export._stream(
        iter([["1", "kept"], ["image.png", "unmatched"]]),
        tmp_path / "output.csv",
        [],
        {("head", "x"): 1},
        {1: {"head": (3, 4)}},
        (),
    )
    assert report.rows == 2 and report.corrected_points == 0
    assert "kept" in (tmp_path / "output.csv").read_text()


def test_other_plugin_capabilities_do_not_attempt_series_or_video_reads(tmp_path: Path) -> None:
    class FutureSource:
        @classmethod
        def display_name(cls):
            return "Future format"

    report = plugin_check.PluginReport()
    plugin_check._check_source(tmp_path / "future", FutureSource, {}, report)
    assert report.lines and not report.problems
