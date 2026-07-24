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
