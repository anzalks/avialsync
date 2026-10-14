"""Coordinate cache readers with replacement and eviction across processes."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from avialsync.core.cache_process_lock import ProcessLease
from avialsync.core.errors import CacheError

_PIN_LOCK = threading.RLock()
_PINNED: dict[Path, int] = {}
_MUTATING: set[Path] = set()
_READ_LEASES: dict[Path, ProcessLease] = {}


def _base_entry(directory: Path) -> Path:
    """Map an edited generation to its owning source entry."""
    path = directory.absolute()
    return path.parent.parent if path.parent.name == "edited" else path


class GenerationPin:
    """Keep a reader's cache directory available while a job holds it."""

    def __init__(self, directory: Path) -> None:
        pinned = directory.absolute()
        self.directory: Path | None = None
        with _PIN_LOCK:
            base = _base_entry(pinned)
            if base in _MUTATING or pinned in _MUTATING:
                raise FileNotFoundError(pinned)
            if pinned in _PINNED or (pinned == base and base in _READ_LEASES):
                # A worker already verified and leased this generation. Clone
                # its ownership in memory when building UI readers.
                _PINNED[pinned] = _PINNED.get(pinned, 0) + 1
                self.directory = pinned
                return
            if not pinned.is_dir():
                raise FileNotFoundError(pinned)
            acquired: list[Path] = []
            try:
                # The base protects replacement; an edited generation also
                # needs its own lease so unrelated generations can be pruned.
                for owner in dict.fromkeys((base, pinned)):
                    if owner not in _READ_LEASES:
                        lease = ProcessLease.acquire(owner, exclusive=False)
                        if lease is None:
                            raise FileNotFoundError(pinned)
                        _READ_LEASES[owner] = lease
                        acquired.append(owner)
                if not pinned.is_dir():
                    raise FileNotFoundError(pinned)
            except BaseException:
                for owner in reversed(acquired):
                    _READ_LEASES.pop(owner).close()
                raise
            _PINNED[pinned] = _PINNED.get(pinned, 0) + 1
            self.directory = pinned

    def close(self) -> None:
        """Release this generation once its reader reference is discarded."""
        with _PIN_LOCK:
            directory = getattr(self, "directory", None)
            if directory is None:
                return
            remaining = _PINNED[directory] - 1
            if remaining:
                _PINNED[directory] = remaining
            else:
                del _PINNED[directory]
                if directory != _base_entry(directory):
                    _READ_LEASES.pop(directory).close()
            self.directory = None
            base = _base_entry(directory)
            if not cache_entry_pinned(base):
                _READ_LEASES.pop(base).close()

    def __del__(self) -> None:
        self.close()


def pin_reader_directory(directory: Path) -> GenerationPin | None:
    """Pin a base or edited reader directory while a worker may open it."""
    try:
        return GenerationPin(directory)
    except FileNotFoundError:
        return None


def pin_published_reader(directory: Path) -> GenerationPin | None:
    """Pin a published entry; bare fixture directories have no entry lifecycle."""
    from avialsync.core.cache import SOURCES_DIR, TEMP_PREFIX, read_entry_record

    base = _base_entry(directory)
    with _PIN_LOCK:
        if directory.absolute() in _READ_LEASES:
            return GenerationPin(directory)
    if base.name.startswith(TEMP_PREFIX):
        return None
    if base.parent.name != SOURCES_DIR and read_entry_record(base) is None:
        return None
    pin = pin_reader_directory(directory)
    if pin is None:
        raise CacheError("Cache entry is in use by another process; retry the read")
    return pin


def cache_entry_pinned(directory: Path) -> bool:
    """Return whether a base entry or any of its edited generations is pinned.

    Called under ``_PIN_LOCK`` while installing a mutation reservation; that
    reservation then prevents new pins throughout the slower disk operation.
    """
    base = directory.absolute()
    return any(path == base or path.parent.parent == base for path in _PINNED)


def cache_entry_mutating(directory: Path) -> bool:
    """Return whether a replacement or eviction reserved this entry.

    Call while holding ``_PIN_LOCK`` when deciding to prune a generation.
    """
    return directory.absolute() in _MUTATING


@contextmanager
def reserve_cache_entry(directory: Path) -> Iterator[bool]:
    """Reserve a source entry without holding the pin lock during slow I/O."""
    base = directory.absolute()
    lease: ProcessLease | None = None
    with _PIN_LOCK:
        reserved = base not in _MUTATING and not cache_entry_pinned(base)
        if reserved:
            lease = ProcessLease.acquire(base, exclusive=True)
            reserved = lease is not None
            if reserved:
                _MUTATING.add(base)
    try:
        yield reserved
    finally:
        if reserved:
            with _PIN_LOCK:
                _MUTATING.remove(base)
                assert lease is not None
                lease.close()


def pinned_cache_entries() -> frozenset[Path]:
    """Return base entry paths held by worker snapshots."""
    with _PIN_LOCK:
        return frozenset(
            path.parent.parent if path.parent.name == "edited" else path for path in _PINNED
        )


@contextmanager
def reserve_edited_generation(directory: Path) -> Iterator[bool]:
    """Retire an unused edited generation while preserving other live readers."""
    path = directory.absolute()
    if path.parent.name != "edited":
        raise ValueError("Only an edited cache generation can be reserved")
    base = _base_entry(path)
    leases: list[ProcessLease] = []
    reserved = False
    with _PIN_LOCK:
        if path not in _PINNED and path not in _MUTATING and base not in _MUTATING:
            try:
                for owner, exclusive in ((base, False), (path, True)):
                    lease = ProcessLease.acquire(owner, exclusive=exclusive)
                    if lease is None:
                        break
                    leases.append(lease)
                else:
                    reserved = True
                    _MUTATING.add(path)
            except BaseException:
                for lease in reversed(leases):
                    lease.close()
                raise
    try:
        yield reserved
    finally:
        with _PIN_LOCK:
            if reserved:
                _MUTATING.remove(path)
            for lease in reversed(leases):
                lease.close()
