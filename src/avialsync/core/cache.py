"""Cache management for sidecar files."""

import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import xxhash

from avialsync.core.errors import CacheError

#: Suffix of a committed sidecar cache directory.  Named here because anything
#: that *walks* a user's folders has to recognise one and step over it: a cache
#: holds hundreds of ``.npy`` files, and a scanner that descends into one offers
#: every single of them as an import candidate.
CACHE_DIR_SUFFIX = ".avialcache"

#: Prefix of an in-progress cache directory, before the atomic swap.  Dotted, so
#: it is also caught by any filter that skips hidden entries.
TEMP_CACHE_PREFIX = ".tmp_avialcache_"


def is_cache_path(path: Path) -> bool:
    """Return whether *path* is one of our own sidecar directories."""
    return path.name.endswith(CACHE_DIR_SUFFIX) or path.name.startswith(TEMP_CACHE_PREFIX)


class CacheManager:
    """Manages .avialcache sidecar directories with atomic writes and hardened keys."""

    def __init__(
        self,
        loader_version: int = 1,
        cache_config: Mapping[str, Any] | None = None,
    ):
        self.loader_version = loader_version
        self._cache_config = dict(cache_config or {})

    def _hash_file_edges(self, path: Path) -> str:
        """Hash the first and last 64KB of the file."""
        if path.is_dir():
            # For directories, edge hashing is not applicable. The cache key
            # will rely on the directory's mtime and size in generate_key.
            return xxhash.xxh64(str(path.absolute()).encode("utf-8")).hexdigest()

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
            "cache_config": self._cache_config,
            "hash": edge_hash,
        }

        return json.dumps(key_data, sort_keys=True)

    def get_cache_dir(self, source_path: Path) -> Path:
        """Return the path to the sidecar cache directory."""
        return source_path.with_name(source_path.name + CACHE_DIR_SUFFIX)

    def is_cache_valid(self, source_path: Path) -> bool:
        """Check if the cache directory exists and the key matches."""
        cache_dir = self.get_cache_dir(source_path)
        self._recover_interrupted_swap(cache_dir)
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
        temp_dir = tempfile.mkdtemp(prefix=TEMP_CACHE_PREFIX, dir=parent)
        return Path(temp_dir)

    def commit_cache(self, source_path: Path, temp_dir: Path) -> None:
        """Commit a replacement without discarding the last valid sidecar first."""
        cache_dir = self.get_cache_dir(source_path)

        # Write metadata key
        meta_path = temp_dir / "meta.json"
        with open(meta_path, "w") as f:
            f.write(self.generate_key(source_path))

        backup_dir: Path | None = None
        try:
            if cache_dir.exists():
                backup_dir = cache_dir.with_name(f".{cache_dir.name}.backup-{uuid.uuid4().hex}")
                os.rename(cache_dir, backup_dir)
            os.rename(temp_dir, cache_dir)
        except OSError as rename_error:
            if backup_dir is not None and backup_dir.exists() and not cache_dir.exists():
                try:
                    os.rename(backup_dir, cache_dir)
                except OSError:
                    pass
            # Renaming a *directory* can fail even when its files are writable:
            # on Windows a sync client (OneDrive), search indexer or antivirus
            # commonly holds a handle on the directory itself, which is normal
            # under a synced Documents folder. Fall back to a file-level swap
            # that never renames a directory.
            try:
                self._commit_in_place(source_path, cache_dir, temp_dir)
            except OSError as swap_error:
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise CacheError(
                    f"Failed to commit cache: {rename_error}; "
                    f"in-place fallback also failed: {swap_error}"
                ) from swap_error
            return
        if backup_dir is not None:
            try:
                shutil.rmtree(backup_dir)
            except OSError as error:
                raise CacheError(f"Committed cache but could not remove backup: {error}") from error

    def _commit_in_place(self, source_path: Path, cache_dir: Path, temp_dir: Path) -> None:
        """Replace a sidecar's contents without renaming the directory.

        Individual files can be replaced even while the enclosing directory is
        held open. ``meta.json`` is removed first and written last, so an
        interruption leaves the sidecar *invalid* (and therefore rebuilt) rather
        than a mix of old and new arrays.
        """
        cache_dir.mkdir(parents=True, exist_ok=True)

        meta_path = cache_dir / "meta.json"
        if meta_path.exists():
            meta_path.unlink()

        staged = {item.name for item in temp_dir.iterdir() if item.is_file()}
        for item in temp_dir.iterdir():
            if item.is_file() and item.name != "meta.json":
                os.replace(item, cache_dir / item.name)

        # Drop arrays that the new build no longer produces.
        for existing in cache_dir.iterdir():
            if existing.is_file() and existing.name not in staged:
                existing.unlink()

        (cache_dir / "meta.json").write_text(self.generate_key(source_path), encoding="utf-8")
        shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _recover_interrupted_swap(cache_dir: Path) -> None:
        """Restore the most recent valid-sidecar backup after a process interruption."""
        if cache_dir.exists():
            return
        backups = sorted(
            cache_dir.parent.glob(f".{cache_dir.name}.backup-*"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not backups:
            return
        try:
            os.replace(backups[0], cache_dir)
        except OSError:
            return
