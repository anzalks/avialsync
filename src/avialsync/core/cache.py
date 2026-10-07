"""Derived data, kept in one per-user cache folder (D-160).

Everything under the cache root is rebuilt from a source file: the imported
pyramids, a video's frame-timestamp table, and the edited-tracker generations
derived from the sidecars beside a pose file.  None of it is the user's work,
so deleting the whole folder costs a re-import and nothing else.  That is the
property which decides what may live here -- a hand correction, an identity
swap, a prop's geometry or an accepted sync mapping is *not* derived, and is
kept beside the data or the session instead.

**Where.**  The platform's per-user cache location, as every desktop tool that
keeps derived media does: ``~/Library/Caches/avialsync`` on macOS,
``%LOCALAPPDATA%\\avialsync\\Cache`` on Windows and ``$XDG_CACHE_HOME/avialsync``
(``~/.cache/avialsync``) on Linux.  ``AVIALSYNC_CACHE_DIR`` overrides it, for a
lab that wants the cache on a scratch disk and for the test suite.

**One entry per source.**  ``<root>/sources/<name>-<digest>/``, where the
digest is of the source's absolute path, so a file gets the same entry however
it arrived -- dropped with a folder, opened alone, or restored from a session --
and the readable prefix lets a person find it.  Each entry carries a
``source.json`` record naming the file it was built from: it is what lets one
trial's cache be found and removed, and what :mod:`avialsync.core.cache_store`
checks before it deletes anything.
"""

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import xxhash

from avialsync.core.errors import CacheError

#: Overrides the platform cache location when set to a non-empty path.
CACHE_DIR_ENV = "AVIALSYNC_CACHE_DIR"

#: Folder under the root holding one entry per source.  Kept apart from the
#: root itself so nothing else that may one day be cached shares its namespace.
SOURCES_DIR = "sources"

#: The record inside every entry naming the source it was built from.
ENTRY_RECORD = "source.json"

#: The record's ``format`` value -- the mark of a directory this module wrote.
ENTRY_FORMAT = "avialsync-cache-entry/1"

#: Prefix of an in-progress entry, before the atomic swap.  Dotted, so a
#: listing of committed entries steps over it without a second rule.
TEMP_PREFIX = ".tmp-"

#: Sub-directory of an entry that outlives a rebuild of the entry itself:
#: the edited-tracker generations (:mod:`avialsync.core.edit_cache`). They are
#: derived from the user's edits, readers hold paths into them, and a job may be
#: writing one while the source is re-imported, so a rebuild carries them into
#: the new entry rather than deleting them with the old one. Whether one is
#: still valid for the new base is :mod:`~avialsync.core.edit_cache`'s question.
EDITED_SUBDIR = "edited"

#: Characters kept in an entry's readable prefix.  Everything else -- including
#: the ones Windows rejects in a file name -- becomes ``_``.
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_LABEL_LIMIT = 40


def cache_root() -> Path:
    """Return the folder holding every cached entry; it may not exist yet."""
    override = os.environ.get(CACHE_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "avialsync" / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "avialsync"
    # The XDG spec says a relative value is invalid and must be ignored.
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".cache"
    return base / "avialsync"


def source_identity(source_path: Path | str) -> str:
    """Return the absolute path that names *source_path*'s entry."""
    return os.path.abspath(source_path)


def entry_name(source_path: Path | str) -> str:
    """Return the entry directory name for *source_path*.

    ``normcase`` before hashing, so the same file reached through a different
    letter case on Windows shares one entry; ``fsencode`` so a POSIX name that
    is not valid UTF-8 still hashes rather than raising.
    """
    identity = source_identity(source_path)
    digest = hashlib.sha256(os.fsencode(os.path.normcase(identity))).hexdigest()[:16]
    label = _UNSAFE_NAME.sub("_", Path(identity).name)[:_LABEL_LIMIT].strip("._ ")
    return f"{label or 'source'}-{digest}"


def cache_dir_for(source_path: Path | str, root: Path | None = None) -> Path:
    """Return the entry directory for *source_path* under *root*."""
    return (root if root is not None else cache_root()) / SOURCES_DIR / entry_name(source_path)


def write_entry_record(directory: Path, source_path: Path | str) -> None:
    """Mark *directory* as an entry built from *source_path*."""
    record = {"format": ENTRY_FORMAT, "source": source_identity(source_path)}
    (directory / ENTRY_RECORD).write_text(json.dumps(record), encoding="utf-8")


def read_entry_record(directory: Path) -> str | None:
    """Return the source an entry was built from, or None if it is not ours."""
    try:
        record = json.loads((directory / ENTRY_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("format") != ENTRY_FORMAT:
        return None
    source = record.get("source")
    return source if isinstance(source, str) and source else None


class CacheManager:
    """Manages one source's cache entry with atomic writes and hardened keys."""

    def __init__(
        self,
        loader_version: int = 1,
        cache_config: Mapping[str, Any] | None = None,
        root: Path | None = None,
    ):
        self.loader_version = loader_version
        self._cache_config = dict(cache_config or {})
        self._root = root

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
        """Return the cache entry directory for *source_path*."""
        return cache_dir_for(source_path, self._root)

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
        """Return a fresh staging directory beside the entry, for an atomic swap.

        Beside it, under the same root, so the commit is a rename on one file
        system.  The record is written first: a staging directory a crash leaves
        behind is still recognisably ours, and so still removable.
        """
        sources = self.get_cache_dir(source_path).parent
        sources.mkdir(parents=True, exist_ok=True)
        prefix = f"{TEMP_PREFIX}{entry_name(source_path)}-"
        temp_dir = Path(tempfile.mkdtemp(prefix=prefix, dir=sources))
        write_entry_record(temp_dir, source_path)
        return temp_dir

    def commit_cache(self, source_path: Path, temp_dir: Path) -> None:
        """Commit a replacement without discarding the last valid entry first."""
        cache_dir = self.get_cache_dir(source_path)

        # Write metadata key
        meta_path = temp_dir / "meta.json"
        with open(meta_path, "w") as f:
            f.write(self.generate_key(source_path))
        # Rewritten even though staging wrote one: a caller may have staged into
        # a directory of its own, and an entry without its record is one that
        # neither a trial's cleanup nor "delete all" will ever remove.
        write_entry_record(temp_dir, source_path)

        backup_dir: Path | None = None
        try:
            if cache_dir.exists():
                backup_dir = cache_dir.with_name(f".{cache_dir.name}.backup-{uuid.uuid4().hex}")
                os.rename(cache_dir, backup_dir)
            os.rename(temp_dir, cache_dir)
            if backup_dir is not None:
                self._carry_edited(backup_dir, cache_dir)
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

    @staticmethod
    def _carry_edited(backup_dir: Path, cache_dir: Path) -> None:
        """Move the outgoing entry's edited generations into the new one.

        Deleting them with the backup is what crashed a running build: a
        provisional frame rate is replaced as soon as a camera can date the
        frames, which re-imports the pose file, and every reader pointing into
        ``edited/`` then found its next array gone mid-paint. A failure here is
        not a failed commit -- generations are derived and are rebuilt on
        demand -- so it is left for the backup's removal to deal with.
        """
        edited = backup_dir / EDITED_SUBDIR
        if not edited.is_dir():
            return
        try:
            os.rename(edited, cache_dir / EDITED_SUBDIR)
        except OSError:
            return

    def _commit_in_place(self, source_path: Path, cache_dir: Path, temp_dir: Path) -> None:
        """Replace an entry's contents without renaming the directory.

        Individual files can be replaced even while the enclosing directory is
        held open. ``meta.json`` is removed first and written last, so an
        interruption leaves the entry *invalid* (and therefore rebuilt) rather
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
        """Restore the most recent valid-entry backup after a process interruption."""
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
