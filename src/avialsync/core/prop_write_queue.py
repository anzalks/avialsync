"""Thread-safe latest-revision queue for authored prop records, drained by a worker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Condition

from avialsync.core.prop_file import PropKind, PropRecord


@dataclass(frozen=True)
class PropWriteRequest:
    """An immutable accepted revision and its recording ownership."""

    folder: Path
    name: str
    prop: PropRecord | None
    kind: PropKind
    overwrite: bool
    generation: int
    revision: int


class PropWriteQueue:
    """Coalesce by file without depending on the UI event loop to start the next write."""

    def __init__(self) -> None:
        self._lock = Condition()
        self._pending: dict[tuple[Path, str, int], PropWriteRequest] = {}
        self._latest: dict[tuple[Path, str, int], int] = {}
        self._owned: set[tuple[Path, str, int]] = set()
        self._running = False

    def enqueue(
        self,
        folder: Path,
        name: str,
        prop: PropRecord | None,
        kind: PropKind,
        overwrite: bool,
        generation: int,
    ) -> bool:
        """Keep the newest revision; return whether the caller must register a worker."""
        with self._lock:
            key = (folder, name, generation)
            revision = self._latest.get(key, 0) + 1
            self._latest[key] = revision
            self._pending[key] = PropWriteRequest(
                folder, name, prop, kind, overwrite, generation, revision
            )
            start = not self._running
            self._running = True
            return start

    def take(self) -> PropWriteRequest | None:
        """Claim the oldest waiting path, or atomically release worker ownership."""
        with self._lock:
            if not self._pending:
                self._running = False
                self._lock.notify_all()
                return None
            return self._pending.pop(next(iter(self._pending)))

    def may_overwrite(self, request: PropWriteRequest) -> bool:
        """A record this queue wrote successfully is safe to update on its next revision."""
        with self._lock:
            return (
                request.overwrite
                or (request.folder, request.name, request.generation) in self._owned
            )

    def published(self, request: PropWriteRequest) -> None:
        """Record ownership independently of delayed UI notifications."""
        with self._lock:
            self._owned.add((request.folder, request.name, request.generation))

    def is_current(self, request: PropWriteRequest) -> bool:
        """Whether this result still describes the newest accepted revision."""
        with self._lock:
            return request.revision == self._latest.get(
                (request.folder, request.name, request.generation)
            )

    def wait_until_idle(self, timeout: float = 10.0) -> bool:
        """Let a discovery worker wait for accepted saves; never call from the UI."""
        with self._lock:
            return self._lock.wait_for(lambda: not self._running, timeout=timeout)
