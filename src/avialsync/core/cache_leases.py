"""Coordinate cache readers with replacement and eviction in this process."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_PIN_LOCK = threading.RLock()
_PINNED: dict[Path, int] = {}
_MUTATING: set[Path] = set()


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
            if _base_entry(pinned) in _MUTATING:
                raise FileNotFoundError(pinned)
            if not pinned.is_dir():
                raise FileNotFoundError(pinned)
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
            self.directory = None

    def __del__(self) -> None:
        self.close()


def pin_reader_directory(directory: Path) -> GenerationPin | None:
    """Pin a base or edited reader directory while a worker may open it."""
    try:
        return GenerationPin(directory)
    except FileNotFoundError:
        return None


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
    with _PIN_LOCK:
        reserved = base not in _MUTATING and not cache_entry_pinned(base)
        if reserved:
            _MUTATING.add(base)
    try:
        yield reserved
    finally:
        if reserved:
            with _PIN_LOCK:
                _MUTATING.remove(base)


def pinned_cache_entries() -> frozenset[Path]:
    """Return base entry paths held by worker snapshots."""
    with _PIN_LOCK:
        return frozenset(
            path.parent.parent if path.parent.name == "edited" else path for path in _PINNED
        )
