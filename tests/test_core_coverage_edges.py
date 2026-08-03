"""Edge paths in ``core/`` that no other test reached (P6.1, TESTING §1).

TESTING §1 gates ``core/`` at 100 % branch coverage. These are the error,
recovery, and fallback branches — the ones that only run when something has
already gone wrong, and therefore the ones most likely to be broken silently.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from avialsync.core.cache import CacheManager
from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.errors import CacheError
from avialsync.core.inspection import IntegrityFlags
from avialsync.core.pyramid import PyramidBuilder, PyramidReader
from avialsync.core.registry import LoaderRegistry
from avialsync.core.session import SessionState, SyncProvenance
from avialsync.core.timeline import TimeMap

# ── cache: error and recovery branches ────────────────────────────────


def test_generate_key_for_a_missing_source_is_refused(tmp_path: Path) -> None:
    """A key over a file that is not there would cache nothing meaningful."""
    manager = CacheManager(loader_version=1)

    with pytest.raises(FileNotFoundError, match="Source file not found"):
        manager.generate_key(tmp_path / "absent.csv")


def test_cache_validity_of_an_unreadable_sidecar_is_false(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "data.csv"
    source.write_text("x", encoding="utf-8")
    manager = CacheManager(loader_version=1)
    staged = manager.get_temp_cache_dir(source)
    manager.commit_cache(source, staged)

    import builtins

    real_open = builtins.open

    def explode(file, *args, **kwargs):
        if str(file).endswith("meta.json"):
            raise OSError("meta unreadable")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", explode)

    assert manager.is_cache_valid(source) is False


def test_commit_reports_a_backup_it_could_not_remove(tmp_path: Path, monkeypatch) -> None:
    """A committed cache with a stranded backup must say so, not pass silently."""
    source = tmp_path / "data.csv"
    source.write_text("x", encoding="utf-8")
    manager = CacheManager(loader_version=1)
    manager.commit_cache(source, manager.get_temp_cache_dir(source))

    import shutil

    monkeypatch.setattr(
        shutil, "rmtree", lambda *a, **k: (_ for _ in ()).throw(OSError("backup held"))
    )

    with pytest.raises(CacheError, match="could not remove backup"):
        manager.commit_cache(source, manager.get_temp_cache_dir(source))


def test_in_place_commit_drops_arrays_the_new_build_no_longer_produces(
    tmp_path: Path, monkeypatch
) -> None:
    """A stale array left behind would be read as if it belonged to the new data."""
    source = tmp_path / "data.csv"
    source.write_text("x", encoding="utf-8")
    manager = CacheManager(loader_version=1)
    first = manager.get_temp_cache_dir(source)
    (first / "old_channel.npy").write_bytes(b"\x00")
    (first / "kept.npy").write_bytes(b"\x00")
    manager.commit_cache(source, first)

    second = manager.get_temp_cache_dir(source)
    (second / "kept.npy").write_bytes(b"\x01")
    original_rename = os.rename
    monkeypatch.setattr(
        os,
        "rename",
        lambda s, d: (
            (_ for _ in ()).throw(OSError("held"))
            if str(s) == str(second)
            else original_rename(s, d)
        ),
    )

    manager.commit_cache(source, second)

    cache_dir = manager.get_cache_dir(source)
    assert not (cache_dir / "old_channel.npy").exists()
    assert (cache_dir / "kept.npy").exists()


def test_interrupted_swap_recovery_tolerates_an_unrestorable_backup(
    tmp_path: Path, monkeypatch
) -> None:
    """Recovery is best-effort; failing to restore must not raise on a read path."""
    source = tmp_path / "data.csv"
    source.write_text("x", encoding="utf-8")
    manager = CacheManager(loader_version=1)
    cache_dir = manager.get_cache_dir(source)
    backup = cache_dir.with_name(f".{cache_dir.name}.backup-deadbeef")
    backup.mkdir(parents=True)

    monkeypatch.setattr(
        os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("cannot restore"))
    )

    assert manager.is_cache_valid(source) is False


# ── channel_reader ────────────────────────────────────────────────────


@pytest.fixture
def channel(tmp_path: Path) -> Path:
    t = np.arange(100, dtype=np.float64) / 10.0
    PyramidBuilder(tmp_path, "ch").build_and_save(t, t)
    return tmp_path


def test_mapped_reader_exposes_its_source_reader(channel: Path) -> None:
    inner = PyramidReader(channel, "ch")

    assert MappedChannelReader(inner).source_reader is inner


def test_mapped_coverage_of_an_empty_channel_is_none(tmp_path: Path) -> None:
    PyramidBuilder(tmp_path, "empty").build_and_save(
        np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    )

    assert MappedChannelReader(PyramidReader(tmp_path, "empty")).coverage() is None


# ── inspection: the remaining flag labels ─────────────────────────────


def test_drift_and_provisional_fps_are_named_in_the_flag_labels() -> None:
    labels = IntegrityFlags(drift_nonzero=True, fps_provisional=True).flag_labels()

    assert any("drift" in label.lower() for label in labels)
    assert any("provisional" in label.lower() for label in labels)


# ── timeline: fallback branches ───────────────────────────────────────


def test_rate_scale_without_exact_evidence_uses_the_drift_parameter() -> None:
    assert TimeMap(drift_ppm=1_000.0).rate_scale == pytest.approx(1.001)


def test_snap_without_exact_evidence_returns_the_time_unchanged() -> None:
    assert TimeMap(offset=5.0).snap_master_time(12.5) == pytest.approx(12.5)


def test_snap_before_the_first_accepted_pair_returns_that_pair() -> None:
    time_map = TimeMap()
    time_map.set_exact_mapping(np.array([10.0, 20.0]), np.array([0.0, 10.0]))

    assert time_map.snap_master_time(-100.0) == pytest.approx(10.0)


def test_to_master_array_uses_accepted_exact_evidence() -> None:
    time_map = TimeMap()
    time_map.set_exact_mapping(np.array([0.0, 10.0]), np.array([5.0, 25.0]))

    mapped = time_map.to_master_array(np.array([5.0, 15.0, 25.0]))

    assert mapped == pytest.approx([0.0, 5.0, 10.0])


# ── session: malformed sync provenance ────────────────────────────────


def _provenance(master: list[float], source: list[float]) -> SyncProvenance:
    return SyncProvenance(
        reference_id="sensor:ttl",
        target_id="video:cam",
        offset=0.0,
        drift_ppm=0.0,
        rms_residual=0.0,
        max_residual=0.0,
        matched_count=len(master),
        rejected_count=0,
        tolerance=0.01,
        exact_master=master,
        exact_source=source,
    )


def test_saving_mismatched_exact_arrays_is_refused(tmp_path: Path) -> None:
    """Unequal arrays would silently mis-map frames on reload."""
    state = SessionState(sync_provenance=[_provenance([0.0, 1.0], [0.0])])

    with pytest.raises(ValueError, match="different lengths"):
        state.save(tmp_path / "bad.avv")


def test_a_sidecar_whose_arrays_disagree_with_its_count_is_rejected(tmp_path: Path) -> None:
    """A large mapping lives in a sidecar; a corrupt one must not load silently."""
    import hashlib
    import json

    master = np.arange(600, dtype=np.float64)
    session_path = tmp_path / "s.avv"
    sidecar_dir = tmp_path / "s.avv.avialcache"
    sidecar_dir.mkdir()
    mapping_path = sidecar_dir / "exact-sync-0-corrupt.npz"
    # Deliberately store fewer source samples than the declared count.
    np.savez_compressed(mapping_path, master=master, source=master[:-1])
    digest = hashlib.sha256(mapping_path.read_bytes()).hexdigest()

    session_path.write_text(
        json.dumps(
            {
                "version": 6,
                "sync_provenance": [
                    {
                        "reference_id": "a",
                        "target_id": "b",
                        "offset": 0.0,
                        "drift_ppm": 0.0,
                        "rms_residual": 0.0,
                        "max_residual": 0.0,
                        "matched_count": len(master),
                        "rejected_count": 0,
                        "tolerance": 0.01,
                        "exact_master": [],
                        "exact_source": [],
                        "exact_mapping": {
                            "file": f"s.avv.avialcache/{mapping_path.name}",
                            "sha256": digest,
                            "count": len(master),
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid exact synchronization sidecar"):
        SessionState.load(session_path)


# ── registry: failure diagnostics ─────────────────────────────────────


def test_a_directory_that_is_not_a_plugin_dir_is_skipped(tmp_path: Path) -> None:
    registry = LoaderRegistry(plugin_dirs=[tmp_path / "does-not-exist"])

    assert registry.loaders()


def test_underscore_prefixed_plugin_files_are_ignored(tmp_path: Path) -> None:
    """`_helper.py` beside a plugin is support code, not a plugin."""
    (tmp_path / "_helper.py").write_text("raise RuntimeError('must not import')", encoding="utf-8")

    registry = LoaderRegistry(plugin_dirs=[tmp_path])

    assert registry.loaders()


def test_a_path_with_no_import_spec_is_reported(tmp_path: Path, monkeypatch, caplog) -> None:
    import logging

    import avialsync.core.registry as registry_module

    monkeypatch.setattr(
        registry_module.importlib.util, "spec_from_file_location", lambda *a, **k: None
    )

    with caplog.at_level(logging.WARNING, logger="avialsync.core.registry"):
        module, reason = registry_module.LoaderRegistry._load_module(tmp_path / "toy.py")

    assert module is None
    assert reason is not None
    assert any("import spec" in record.getMessage() for record in caplog.records)
