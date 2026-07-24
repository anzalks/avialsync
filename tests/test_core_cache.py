from pathlib import Path

from kinochronix.core.cache import CacheManager


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
