"""Hand corrections to tracked body-part positions, stored beside the data.

A pose estimator is wrong sometimes: a paw jumps to the shadow of a paw, a
marker swaps between two animals, an occluded nose lands on the wall.  Until
now the only answer was to leave the session, fix the CSV, and re-import it.
"Fix Tracker" lets the point be dragged where it belongs in the pane that
showed the error.

**The correction never touches the imported data.**  The pose CSV is a
recording; the sidecar pyramid cache is derived from it; neither is rewritten
here.  A correction is a sparse override — one ``(source, body part, frame)``
key mapping to one ``(x, y)`` in video pixels — held in this store and applied
when the overlay reads a value.  That is also what makes the edit reversible:
:class:`SetTrackedPointCommand` carries the previous override (or its absence)
and puts it back, with no snapshot of anything.

This store is the in-memory state only.  Where corrections *live* is
:mod:`avialsync.core.point_edit_sidecar`: a CSV beside the pose file, because a
correction is a fact about the recording rather than about the session that was
open when it was made.  The ``.avv`` records a count so a missing sidecar is
reported instead of silently showing fewer points.

Sparse is not an optimisation, it is the semantics.  A user correcting a
dropped detection is annotating a handful of frames out of a hundred thousand,
and every frame they did not touch must keep saying what the model said.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator
from typing import Any

__all__ = [
    "PointKey",
    "PointMove",
    "PointEditStore",
]


@dataclasses.dataclass(frozen=True, slots=True, order=True)
class PointKey:
    """Identity of one correctable coordinate.

    ``index`` is the sample index within *this* source, which for a
    frame-indexed pose export is the video frame number.  Keying by index
    rather than by time is deliberate: an offset or an accepted TimeMap moves
    when a sample is shown without changing which sample it is, and a
    correction must survive that.
    """

    source_id: str
    point: str
    index: int


@dataclasses.dataclass(frozen=True, slots=True)
class PointMove:
    """One completed drag, carrying enough to undo it.

    ``before`` is the override that was in force, or ``None`` when the point
    was still showing the model's own prediction — the difference matters,
    because undoing back to "no override" is not the same as writing the old
    coordinate back as a correction.
    """

    key: PointKey
    before: tuple[float, float] | None
    after: tuple[float, float] | None


class PointEditStore:
    """Every hand correction in the session, keyed by :class:`PointKey`.

    Observers are plain callables so that ``core/`` stays importable without
    PySide6 (architecture rule 2).  They fire once per change, after it lands,
    and are told **which source changed** — ``None`` for a bulk replacement.
    That distinction is load-bearing: the writer persists a user's edit and must
    not write back what it has just finished reading.
    """

    def __init__(self) -> None:
        self._edits: dict[PointKey, tuple[float, float]] = {}
        self._observers: list[Callable[[str | None], None]] = []

    # ── reading ──────────────────────────────────────────────────────

    def get(self, key: PointKey) -> tuple[float, float] | None:
        """Return the corrected position for *key*, or None if untouched."""
        return self._edits.get(key)

    def __len__(self) -> int:
        return len(self._edits)

    def __iter__(self) -> Iterator[PointKey]:
        return iter(self._edits)

    def __contains__(self, key: object) -> bool:
        return key in self._edits

    def items(self) -> Iterator[tuple[PointKey, tuple[float, float]]]:
        """Yield every ``(key, position)`` currently overridden."""
        return iter(self._edits.items())

    def count_for(self, source_id: str) -> int:
        """How many corrections belong to one pose source."""
        return sum(1 for key in self._edits if key.source_id == source_id)

    def source_ids(self) -> set[str]:
        """Every pose source that currently has at least one correction."""
        return {key.source_id for key in self._edits}

    def for_source(self, source_id: str) -> list[tuple[int, str, float, float]]:
        """Return one source's corrections as ``(frame, body part, x, y)`` rows."""
        return sorted(
            (key.index, key.point, position[0], position[1])
            for key, position in self._edits.items()
            if key.source_id == source_id
        )

    # ── writing ──────────────────────────────────────────────────────

    def set(self, key: PointKey, position: tuple[float, float] | None) -> bool:
        """Override *key* with *position*, or clear it when *position* is None.

        Returns whether anything changed, so a no-op drag does not push an undo
        entry or mark the document dirty.
        """
        if position is None:
            if key not in self._edits:
                return False
            del self._edits[key]
        else:
            value = (float(position[0]), float(position[1]))
            if self._edits.get(key) == value:
                return False
            self._edits[key] = value
        self._notify(key.source_id)
        return True

    def clear(self) -> None:
        """Drop every correction.  Used when the workspace is reset."""
        if not self._edits:
            return
        self._edits.clear()
        self._notify(None)

    def clear_source(self, source_id: str) -> bool:
        """Drop every correction belonging to one pose source."""
        doomed = [key for key in self._edits if key.source_id == source_id]
        if not doomed:
            return False
        for key in doomed:
            del self._edits[key]
        self._notify(None)
        return True

    def load_source(self, source_id: str, rows: list[tuple[int, str, float, float]]) -> None:
        """Replace one source's corrections, leaving every other source alone.

        This is the read path -- adopting what a sidecar held when its pose file
        was imported -- so it notifies as a bulk change and the writer does not
        echo it straight back to disk.
        """
        for key in [k for k in self._edits if k.source_id == source_id]:
            del self._edits[key]
        for index, point, x, y in rows:
            self._edits[PointKey(source_id, point, int(index))] = (float(x), float(y))
        self._notify(None)

    # ── observation ──────────────────────────────────────────────────

    def observe(self, callback: Callable[[str | None], None]) -> Callable[[], None]:
        """Register *callback*, called with the changed source after any change.

        The argument is the source id for a single-point change and ``None`` for
        a bulk replacement.  Returns a disposer.
        """
        self._observers.append(callback)

        def _dispose() -> None:
            if callback in self._observers:
                self._observers.remove(callback)

        return _dispose

    def _notify(self, source_id: str | None) -> None:
        for callback in list(self._observers):
            callback(source_id)

    # ── session persistence ──────────────────────────────────────────

    def to_list(self, source_id: str | None = None) -> list[dict[str, Any]]:
        """Serialise to a JSON-compatible list, ordered so saves are stable.

        Used for the session-stored fallback, when the pose file's directory
        cannot be written.  Pass *source_id* to serialise one source only.
        """
        return [
            {
                "source": key.source_id,
                "point": key.point,
                "index": key.index,
                "x": position[0],
                "y": position[1],
            }
            for key, position in sorted(self._edits.items())
            if source_id is None or key.source_id == source_id
        ]

    def load(self, entries: list[dict[str, Any]] | None) -> None:
        """Replace the contents from a serialised list.

        Malformed entries are skipped rather than raising: a session that has
        lost one correction still opens showing everything else (Law 1 —
        never block, always inform).  The caller reports the count it asked for
        against :func:`len`.
        """
        self._edits.clear()
        self._load_entries(entries)
        self._notify(None)

    def adopt(self, entries: list[dict[str, Any]] | None) -> None:
        """Merge serialised *entries* in without dropping what is already held.

        The session-stored fallback arrives before the pose files finish
        importing, and each import then adopts its own sidecar; neither may
        discard the other's sources.
        """
        self._load_entries(entries)
        self._notify(None)

    def _load_entries(self, entries: list[dict[str, Any]] | None) -> None:
        for entry in entries or []:
            try:
                key = PointKey(
                    source_id=str(entry["source"]),
                    point=str(entry["point"]),
                    index=int(entry["index"]),
                )
                self._edits[key] = (float(entry["x"]), float(entry["y"]))
            except (KeyError, TypeError, ValueError):
                continue

    def remap_source(self, old_id: str, new_id: str) -> None:
        """Follow a relinked pose file to its new path.

        Corrections are keyed by source path, so a session whose CSV moved
        would otherwise open with every correction orphaned and silently
        inactive.
        """
        if old_id == new_id:
            return
        moved = {
            dataclasses.replace(key, source_id=new_id): position
            for key, position in self._edits.items()
            if key.source_id == old_id
        }
        if not moved:
            return
        for key in [k for k in self._edits if k.source_id == old_id]:
            del self._edits[key]
        self._edits.update(moved)
        self._notify(None)
