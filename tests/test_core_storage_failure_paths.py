"""Storage retries and incomplete generations preserve previous data and cleanup ownership."""

from pathlib import Path

import numpy as np
import pytest

from avialsync.core import artifact_io, cache_store, edit_cache
from avialsync.core.artifacts import ExistingFile, get_kind
from avialsync.core.cache_store import CacheEntry
from avialsync.core.edit_program import EditProgram
from avialsync.core.pose import PosePoint, PoseSchema
from avialsync.core.pyramid import PyramidBuilder
from tests.test_cache_process_leases import _published_entry


def test_cache_discovery_and_removal_skip_unowned_paths(tmp_path: Path) -> None:
    assert cache_store.list_entries(tmp_path) == []
    assert cache_store.entries_under([], tmp_path) == []
    assert cache_store.working_folders([]) == []
    report = cache_store.remove_entries(
        [CacheEntry(tmp_path / "sources" / "unowned", "source")], tmp_path
    )
    assert report.removed == 0 and report.failed
    assert cache_store._sources_dir(None) == cache_store.cache_root() / "sources"


def test_exhausted_cache_rename_retries_leave_entry_intact(tmp_path: Path, monkeypatch) -> None:
    _, _, entry = _published_entry(tmp_path)
    original = entry / "keep"
    original.write_text("data")
    monkeypatch.setattr(cache_store.time, "sleep", lambda delay: None)

    def denied(*args):
        raise PermissionError("reader owns the entry")

    monkeypatch.setattr(cache_store.os, "rename", denied)
    root = entry.parent.parent
    report = cache_store.remove_entries(cache_store.list_entries(root), root)
    assert report.removed == 0 and report.failed and original.read_text() == "data"


def test_other_rename_errors_and_failed_tree_stats_are_reported(
    tmp_path: Path, monkeypatch
) -> None:
    def denied(*args):
        raise OSError("storage unavailable")

    monkeypatch.setattr(cache_store.os, "rename", denied)
    assert isinstance(cache_store._rename_aside(tmp_path / "source", tmp_path / "trash"), OSError)
    (tmp_path / "data").write_text("data")
    monkeypatch.setattr(cache_store.os, "lstat", denied)
    assert cache_store._tree_size(tmp_path) == 0


def test_invalid_cache_limits_and_disappeared_entries_are_handled(
    tmp_path: Path, monkeypatch
) -> None:
    with pytest.raises(ValueError):
        cache_store.trim_cache(tmp_path, max_bytes=-1)
    with pytest.raises(ValueError):
        cache_store.trim_cache(tmp_path, max_age_days=-1)
    monkeypatch.setattr(
        cache_store, "list_entries", lambda root: [CacheEntry(tmp_path / "missing", "source")]
    )
    assert cache_store.trim_cache(tmp_path).removed == 0
    monkeypatch.setattr(
        cache_store.os.path,
        "commonpath",
        lambda paths: (_ for _ in ()).throw(ValueError("two drives")),
    )
    sources = [tmp_path / "source"]
    assert cache_store.working_folders(sources) == sources


def test_refuse_policy_uses_atomic_file_publication(tmp_path: Path) -> None:
    from dataclasses import replace

    kind = replace(get_kind("data-slice-csv"), existing=ExistingFile.REFUSE)
    output = artifact_io.publish(tmp_path / "output.csv", lambda p: p.write_text("data"), kind=kind)
    assert output.read_text() == "data" and list(tmp_path.iterdir()) == [output]


def test_malformed_edited_manifest_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("[]")
    assert edit_cache._read_manifest(tmp_path) is None


def test_partial_pose_cache_keeps_missing_coordinates_and_likelihood_unmodified(
    tmp_path: Path,
) -> None:
    PyramidBuilder(tmp_path, "head_x").build_and_save(np.arange(3.0), np.arange(3.0))
    program = EditProgram("source", (), (), {("head", 1): (9, 8)}, "fixture")
    point = PosePoint("", "head", ("x", "y"), has_likelihood=True)
    schema = PoseSchema((point,), frame_indexed=True)
    edited = edit_cache.materialise(tmp_path, program, schema)
    assert edited.channels == frozenset({"head_x"})
    assert not list((tmp_path / "edited").glob(".tmp_*"))


def test_edit_routes_beyond_recording_cannot_read_a_donor(tmp_path: Path) -> None:
    PyramidBuilder(tmp_path, "head_x").build_and_save(np.arange(3.0), np.arange(3.0))
    program = EditProgram("source", (100,), ({"head": "missing"},), {}, "fixture")
    _, values = edit_cache._edited_values(tmp_path, program, "head", "head_x", 0)
    np.testing.assert_array_equal(values, np.arange(3.0))


def test_generation_removal_failure_is_logged_and_not_raised(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    def denied(*args, **kwargs):
        raise PermissionError("open array")

    monkeypatch.setattr(edit_cache.shutil, "rmtree", denied)
    edit_cache._remove_generation(tmp_path)
    assert tmp_path.exists() and "Could not remove" in caplog.text


def test_trash_sweep_keeps_unowned_folders_and_counts_hardlinks_once(
    tmp_path: Path, monkeypatch
) -> None:
    import os

    trash = tmp_path / ".trash-leftover"
    trash.mkdir()
    cache_store._sweep_trash(tmp_path)
    assert not trash.exists()
    source = tmp_path / "data"
    source.write_bytes(b"data")
    os.link(source, tmp_path / "alias")
    assert cache_store._tree_size(tmp_path) == 4
    monkeypatch.setattr(cache_store, "cache_root", lambda: tmp_path)
    assert cache_store.cache_size() == 4


def test_cache_retirement_can_succeed_on_the_final_retry(tmp_path: Path, monkeypatch) -> None:
    source, target = tmp_path / "entry", tmp_path / ".trash-entry"
    source.mkdir()
    rename = cache_store.os.rename
    attempts, delays = [], []

    def busy_then_ready(directory, trash):
        attempts.append(True)
        if len(attempts) <= len(cache_store._RETRY_DELAYS):
            raise PermissionError("scanner still owns the entry")
        rename(directory, trash)

    monkeypatch.setattr(cache_store.os, "rename", busy_then_ready)
    monkeypatch.setattr(cache_store.time, "sleep", delays.append)
    assert cache_store._rename_aside(source, target) is None
    assert len(attempts) == 5 and delays == list(cache_store._RETRY_DELAYS)
    assert target.is_dir() and not source.exists()
