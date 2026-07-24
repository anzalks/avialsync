"""Cache management for sidecar files."""

import json
import os
import shutil
import tempfile
from pathlib import Path

import xxhash

from kinochronix.core.errors import CacheError


class CacheManager:
    """Manages .kcache sidecar directories with atomic writes and hardened keys."""

    def __init__(self, loader_version: int = 1):
        self.loader_version = loader_version

    def _hash_file_edges(self, path: Path) -> str:
        """Hash the first and last 64KB of the file."""
        if path.is_dir():
            # For directories, edge hashing is not applicable. The cache key 
            # will rely on the directory's mtime and size in generate_key.
            return xxhash.xxh64(str(path.absolute()).encode('utf-8')).hexdigest()

        size = path.stat().st_size
        chunk_size = 64 * 1024

        h = xxhash.xxh64()
        with open(path, "rb") as f:
            # First 64KB
            chunk = f.read(chunk_size)
            h.update(chunk)

            # Last 64KB
            if size > chunk_size:
                seek_pos = max(chunk_size, size - chunk_size)
                f.seek(seek_pos)
                chunk = f.read(chunk_size)
                h.update(chunk)

        return h.hexdigest()

    def generate_key(self, path: Path) -> str:
        """Generate cache invalidation key per D-008."""
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {path}")

        stat = path.stat()
        edge_hash = self._hash_file_edges(path)

        key_data = {
            "path": str(path.absolute()),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "loader_version": self.loader_version,
            "hash": edge_hash,
        }

        return json.dumps(key_data, sort_keys=True)

    def get_cache_dir(self, source_path: Path) -> Path:
        """Return the path to the sidecar cache directory."""
        return source_path.with_name(source_path.name + ".kcache")

    def is_cache_valid(self, source_path: Path) -> bool:
        """Check if the cache directory exists and the key matches."""
        cache_dir = self.get_cache_dir(source_path)
        meta_path = cache_dir / "meta.json"

        if not cache_dir.exists() or not meta_path.exists():
            return False

        try:
            with open(meta_path) as f:
                cached_key = f.read()

            current_key = self.generate_key(source_path)
            return cached_key == current_key
        except Exception:
            return False

    def get_temp_cache_dir(self, source_path: Path) -> Path:
        """Get a temporary directory for writing cache. Ensure atomic swap later."""
        parent = source_path.parent
        temp_dir = tempfile.mkdtemp(prefix=".tmp_kcache_", dir=parent)
        return Path(temp_dir)

    def commit_cache(self, source_path: Path, temp_dir: Path) -> None:
        """Atomically commit the temporary cache directory to the final sidecar path."""
        cache_dir = self.get_cache_dir(source_path)

        # Write metadata key
        meta_path = temp_dir / "meta.json"
        with open(meta_path, "w") as f:
            f.write(self.generate_key(source_path))

        # Atomic swap (POSIX rename replaces directories if empty,
        # but cross-platform we might need to remove first)
        try:
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
            os.rename(temp_dir, cache_dir)
        except OSError as e:
            raise CacheError(f"Failed to commit cache atomically: {e}") from e
