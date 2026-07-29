import os
from pathlib import Path

import pytest

from avialview.core.cache import CacheManager
from avialview.core.errors import CacheError


def test_cache_manager_keys(tmp_path: Path):
    manager = CacheManager(loader_version=1)

    source = tmp_path / "data.csv"
    with open(source, "w") as f:
        f.write("a,b,c\n" * 100)

    key1 = manager.generate_key(source)

    # Modify file length
    with open(source, "a") as f:
        f.write("a,b,c\n")

    key2 = manager.generate_key(source)
    assert key1 != key2


def test_atomic_commit(tmp_path: Path):
    manager = CacheManager(loader_version=1)

    source = tmp_path / "data.csv"
    source.write_text("dummy")

    assert not manager.is_cache_valid(source)

    temp_dir = manager.get_temp_cache_dir(source)
    (temp_dir / "test_data.npy").write_text("numpy data")

    manager.commit_cache(source, temp_dir)

    assert manager.is_cache_valid(source)

    cache_dir = manager.get_cache_dir(source)
    assert (cache_dir / "test_data.npy").exists()
    assert (cache_dir / "meta.json").exists()


def test_cache_stale_invalidation(tmp_path: Path):
    import os

    manager = CacheManager(loader_version=1)
    source = tmp_path / "data.csv"

    # Create a dummy file > 64KB to test edge hashing
    dummy_data = b"a" * (100 * 1024)
    source.write_bytes(dummy_data)

    temp_dir = manager.get_temp_cache_dir(source)
    manager.commit_cache(source, temp_dir)
    assert manager.is_cache_valid(source)

    # Now modify the file content at the end without changing size
    # First, read original size and mtime
    st = source.stat()

    with open(source, "r+b") as f:
        f.seek(-10, os.SEEK_END)
        f.write(b"b" * 10)

    # Reset mtime so only the hash differs
    os.utime(source, (st.st_atime, st.st_mtime))

    # Cache should be invalid because xxhash tail changed
    assert not manager.is_cache_valid(source)


def test_cache_stale_on_loader_version_bump(tmp_path: Path):
    """A cache written by an older loader_version is stale post-change (D-023)."""
    manager_old = CacheManager(loader_version=2)
    source = tmp_path / "data_ver.csv"
    source.write_text("dummy")

    temp_dir = manager_old.get_temp_cache_dir(source)
    manager_old.commit_cache(source, temp_dir)
    assert manager_old.is_cache_valid(source)

    manager_new = CacheManager(loader_version=3)
    assert not manager_new.is_cache_valid(source), "Cache must be stale after loader_version bump"


def test_cache_commit_restores_previous_valid_sidecar_on_swap_failure(
    tmp_path: Path, monkeypatch
) -> None:
    manager = CacheManager(loader_version=1)
    source = tmp_path / "data.csv"
    source.write_text("source", encoding="utf-8")
    initial = manager.get_temp_cache_dir(source)
    (initial / "payload.txt").write_text("old", encoding="utf-8")
    manager.commit_cache(source, initial)

    replacement = manager.get_temp_cache_dir(source)
    (replacement / "payload.txt").write_text("new", encoding="utf-8")
    original_replace = os.replace

    def fail_replacement(src, dst):
        if str(src) == str(replacement):
            raise OSError("simulated replacement failure")
        return original_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_replacement)

    with pytest.raises(CacheError, match="simulated replacement failure"):
        manager.commit_cache(source, replacement)

    cache_dir = manager.get_cache_dir(source)
    assert manager.is_cache_valid(source)
    assert (cache_dir / "payload.txt").read_text(encoding="utf-8") == "old"
