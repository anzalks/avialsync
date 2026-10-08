"""Find and remove cache entries -- and nothing else (D-160).

The cache root is the one folder a user is told they can delete, so removing
from it must never reach anything that is not derived.  Every removal here goes
through :func:`remove_entries`, which deletes a directory only when all of these
hold:

* it sits directly in ``<root>/sources/``;
* it is not a symbolic link, so nothing is followed out of the cache;
* it carries the ``source.json`` record :mod:`avialsync.core.cache` writes.

A directory that fails any of them is reported and left where it is, whatever
it looks like.  The user's data, their sidecars and their sessions are never in
the cache, so none of them can be reached from here.

**Renamed aside, then deleted.**  An entry is first renamed to a ``.trash-``
name in the same folder.  On Windows a file another process holds open makes
that rename fail, which leaves the entry whole and reports it -- rather than a
half-deleted entry whose record went first and which nothing would recognise
afterwards.  A trash directory that could not be finished is removed by the
next sweep; the prefix is one only this module creates, inside a folder only
this package writes.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from avialsync.core.cache import SOURCES_DIR, cache_root, read_entry_record
from avialsync.core.cache_leases import reserve_cache_entry
from avialsync.core.edit_cache import pinned_cache_entries

__all__ = [
    "CacheEntry",
    "RemovalReport",
    "entries_under",
    "list_entries",
    "remove_all",
    "remove_entries",
    "trim_cache",
    "working_folders",
]

#: Prefix of an entry that has been renamed aside for deletion.
TRASH_PREFIX = ".trash-"

#: Pauses before retrying a rename Windows refused.  A virus scanner or the
#: search indexer opening a freshly written file is the common cause, and it
#: lets go within moments; a reader that really holds the file does not, and
#: the entry is then reported and kept.
_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4)


@dataclass(frozen=True)
class CacheEntry:
    """One directory in the cache, and the source it was built from."""

    directory: Path
    source: str


@dataclass
class RemovalReport:
    """What a removal did, for the notification that reports it."""

    removed: int = 0
    freed_bytes: int = 0
    #: ``(directory, reason)`` for every entry left in place.
    failed: list[tuple[str, str]] = field(default_factory=list)


def _sources_dir(root: Path | None) -> Path:
    return (root if root is not None else cache_root()) / SOURCES_DIR


def _normalised(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(path))


def list_entries(root: Path | None = None) -> list[CacheEntry]:
    """Return every entry this package wrote, staging and backups included."""
    try:
        children = list(os.scandir(_sources_dir(root)))
    except OSError:
        return []
    entries = []
    for child in children:
        if child.is_symlink() or not child.is_dir(follow_symlinks=False):
            continue
        if child.name.startswith(TRASH_PREFIX):
            continue
        source = read_entry_record(Path(child.path))
        if source is not None:
            entries.append(CacheEntry(Path(child.path), source))
    return sorted(entries, key=lambda entry: entry.directory.name)


def entries_under(folders: Iterable[Path | str], root: Path | None = None) -> list[CacheEntry]:
    """Return the entries whose source lies in any of *folders*, at any depth."""
    prefixes = [_normalised(folder) for folder in folders]
    if not prefixes:
        return []

    def inside(source: str) -> bool:
        candidate = os.path.normcase(source)
        return any(
            candidate == prefix or candidate.startswith(prefix.rstrip(os.sep) + os.sep)
            for prefix in prefixes
        )

    return [entry for entry in list_entries(root) if inside(entry.source)]


def working_folders(sources: Iterable[Path | str]) -> list[Path]:
    """Return what a loaded trial's cache removal should cover.

    The deepest folder holding every source -- the recording folder when the
    trial is one, whatever subfolders its cameras and pose files sit in.  When
    there is no such folder (two Windows drives), or it is so broad that it is
    no longer one trial's (a filesystem root, the home folder or above it), the
    sources themselves are returned instead, so a trial loaded from scattered
    places never takes every other trial's cache with it.
    """
    absolute = sorted({os.path.abspath(source) for source in sources})
    if not absolute:
        return []
    parents = {os.path.dirname(source) for source in absolute}
    try:
        common = Path(os.path.commonpath(sorted(parents)))
    except ValueError:
        return [Path(source) for source in absolute]
    home = Path(os.path.abspath(Path.home()))
    if str(common) == common.anchor or home.is_relative_to(common):
        return [Path(source) for source in absolute]
    return [common]


def remove_entries(entries: Iterable[CacheEntry], root: Path | None = None) -> RemovalReport:
    """Delete *entries* from the cache, refusing anything that is not one."""
    sources = _sources_dir(root)
    expected_parent = _normalised(sources)
    report = RemovalReport()
    for entry in entries:
        directory = entry.directory
        if _normalised(directory.parent) != expected_parent:
            report.failed.append((str(directory), "not inside the cache folder"))
            continue
        if directory.is_symlink() or not directory.is_dir():
            report.failed.append((str(directory), "not a cache directory"))
            continue
        if read_entry_record(directory) is None:
            report.failed.append((str(directory), "carries no AvialSync cache record"))
            continue
        with reserve_cache_entry(directory) as reserved:
            if not reserved:
                report.failed.append((str(directory), "in use by a running reader"))
                continue
            size = _tree_size(directory)
            trash = sources / f"{TRASH_PREFIX}{uuid.uuid4().hex}"
            error = _rename_aside(directory, trash)
        if error is not None:
            report.failed.append((str(directory), f"in use: {error.strerror or error}"))
            continue
        report.removed += 1
        report.freed_bytes += size
        shutil.rmtree(trash, ignore_errors=True)
    _sweep_trash(sources)
    return report


def remove_all(root: Path | None = None) -> RemovalReport:
    """Delete every entry in the cache."""
    return remove_entries(list_entries(root), root)


def trim_cache(
    root: Path | None = None,
    *,
    max_bytes: int = 10_000_000_000,
    max_age_days: int = 30,
    protected_sources: Iterable[Path | str] = (),
) -> RemovalReport:
    """Evict old, unused derived entries until the optional disk budget fits.

    Entries held by a worker snapshot or named as loaded sources are never
    candidates. Their size still counts toward the budget, so a single large
    active trial can exceed it without losing its arrays mid-read.
    """
    if max_bytes < 0 or max_age_days < 0:
        raise ValueError("Cache limits must be non-negative")
    protected = {_normalised(source) for source in protected_sources}
    pinned = pinned_cache_entries()
    cutoff = time.time() - max_age_days * 86_400
    measured: list[tuple[CacheEntry, int, float]] = []
    for entry in list_entries(root):
        try:
            age = entry.directory.stat().st_mtime
            size = _tree_size(entry.directory)
        except OSError:
            continue
        measured.append((entry, size, age))
    total = sum(size for _, size, _ in measured)
    selected: list[CacheEntry] = []
    for entry, size, age in sorted(measured, key=lambda row: row[2]):
        if _normalised(entry.source) in protected or entry.directory.absolute() in pinned:
            continue
        if age < cutoff or total > max_bytes:
            selected.append(entry)
            total -= size
    return remove_entries(selected, root)


def _rename_aside(directory: Path, trash: Path) -> OSError | None:
    """Rename *directory* to *trash*, retrying a refusal; the last error if it never moved."""
    for delay in (*_RETRY_DELAYS, None):
        try:
            os.rename(directory, trash)
        except PermissionError as error:
            if delay is None:
                return error
            time.sleep(delay)
        except OSError as error:
            return error
        else:
            return None
    return None


def _sweep_trash(sources: Path) -> None:
    """Finish deleting entries an earlier removal renamed aside."""
    try:
        children = list(os.scandir(sources))
    except OSError:
        return
    for child in children:
        if child.name.startswith(TRASH_PREFIX) and not child.is_symlink():
            shutil.rmtree(child.path, ignore_errors=True)


def _tree_size(directory: Path) -> int:
    """Bytes held by *directory*, counting a hard-linked file once.

    The importer hard-links one timestamp array into every channel of a stream
    (D-071), so summing ``st_size`` per name would report freeing many times
    what the disk actually gets back.
    """
    seen: set[tuple[int, int]] = set()
    total = 0
    for folder, _dirs, files in os.walk(directory, followlinks=False):
        for name in files:
            try:
                stat = os.lstat(os.path.join(folder, name))
            except OSError:
                continue
            identity = (stat.st_dev, stat.st_ino)
            if stat.st_nlink > 1 and identity in seen:
                continue
            seen.add(identity)
            total += stat.st_size
    return total
