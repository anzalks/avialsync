"""Missing generations, borrowed ownership and unusual source trees retain safe cache behavior."""

from pathlib import Path

import pytest

from avialsync.core.cache import CacheManager
from avialsync.core.cache_leases import GenerationPin, reserve_edited_generation
from tests.test_cache_process_leases import _published_entry


def test_missing_generation_has_no_reader_ownership(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        GenerationPin(tmp_path / "missing")


def test_two_edited_generations_share_the_base_lease_and_block_retirement(tmp_path: Path) -> None:
    _, _, entry = _published_entry(tmp_path)
    first, second = entry / "edited" / "first", entry / "edited" / "second"
    first.mkdir(parents=True)
    second.mkdir()
    a, b = GenerationPin(first), GenerationPin(second)
    try:
        with reserve_edited_generation(first) as reserved:
            assert not reserved
    finally:
        a.close()
        b.close()
    with reserve_edited_generation(first) as reserved:
        assert reserved


def test_commit_of_caller_owned_stage_needs_no_manager_stage_lease(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("source")
    stage = tmp_path / "caller-stage"
    stage.mkdir()
    (stage / "data").write_text("cached")
    manager = CacheManager(root=tmp_path / "cache")
    manager.commit_cache(source, stage)
    assert (manager.get_cache_dir(source) / "data").read_text() == "cached"


def test_directory_fingerprint_records_link_targets_and_broken_links(
    tmp_path: Path, monkeypatch
) -> None:
    import os

    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    link = source / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"This account cannot create symbolic links: {error}")
    manager = CacheManager()
    valid = manager._hash_file_edges(source)
    target.rmdir()
    # A target can disappear between walk's directory listing and stat.
    monkeypatch.setattr(os, "walk", lambda root: iter([(str(source), ["link"], [])]))
    broken = manager._hash_file_edges(source)
    assert valid != broken


def test_a_pin_collected_at_interpreter_exit_leaves_the_unlock_to_the_os(
    tmp_path, monkeypatch
) -> None:
    """Unlocking during finalisation imports a module after imports stop working."""
    import sys

    from avialsync.core.cache_leases import cache_entry_pinned

    entry = tmp_path / "entry"
    entry.mkdir()
    pin = GenerationPin(entry)
    with monkeypatch.context() as finalizing:
        finalizing.setattr(sys, "is_finalizing", lambda: True)
        pin.__del__()
        assert cache_entry_pinned(entry.absolute())
    pin.__del__()
    assert not cache_entry_pinned(entry.absolute())
