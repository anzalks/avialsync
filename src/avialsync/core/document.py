"""The document model: what changed, whether it is saved, and how to undo it.

Before this module existed the application could not answer "has this session
changed?".  There was no dirty flag and no single place a mutation passed
through: an offset changed a spin box, an annotation changed a table, an
accepted fit changed a ``TimeMap``, and nothing observed all three.  Three
consequences followed — the window title was a constant, closing never
preserved anything, and nothing could be undone (D-087).

Every user-visible mutation is now a :class:`Command` executed against a
:class:`Document`.  Dirty state, undo, and the autosave trigger all derive from
that one log rather than being tracked separately.

Two constraints shape the design, and both are load-bearing:

**Inverse operations, never state snapshots.**  A snapshot of a session with
128 channels of pyramid metadata per undo step would consume the 2.5 GB
idle-RAM budget within roughly twenty edits.  A command carries only what it
needs to reverse itself — an offset command is a source id and two floats.
:data:`MAX_LOG_ENTRIES` bounds the rest.  :class:`ResetSessionCommand` is the
single sanctioned exception, and D-087 explains why it does not generalise.

**The bus is headless.**  ``core/`` may not import PySide6 (architecture rule
2, enforced by a test), so ``QUndoStack`` cannot live here.  This module is
plain Python; :mod:`avialsync.ui.undo_adapter` wraps each command in a
``QUndoCommand``.  Commands act on a :class:`MutationTarget` — a protocol the
UI implements — so the bus never touches a widget and stays testable against a
fake.

The concrete commands live in :mod:`avialsync.core.commands`; this module is
only the bus and the contracts it works against.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "MAX_LOG_ENTRIES",
    "Command",
    "MutationTarget",
    "MarkerRecord",
    "SourceRecord",
    "Document",
    "released",
]

#: Upper bound on retained undo history.  Commands are small (an offset command
#: is a source id and two floats, about 80 bytes), so 200 entries costs roughly
#: 16 KB — three orders of magnitude below the point where the idle-RAM budget
#: would notice.  The cap exists so that a pathological session cannot grow the
#: log without limit, not because the entries are expensive.
MAX_LOG_ENTRIES = 200


@dataclasses.dataclass(frozen=True)
class MarkerRecord:
    """An annotation marker, as the command bus sees it.

    Deliberately not :class:`avialsync.ui.annotations.Marker`: that type is a UI
    object carrying palette-resolved colour and per-video frame snapshots, and
    ``core/`` may not depend on it.  The adapter converts.
    """

    t_start: float
    t_end: float | None
    label: str
    index: int


@dataclasses.dataclass(frozen=True)
class SourceRecord:
    """Enough about a loaded source to put it back after a removal."""

    source_id: str
    path: str
    kind: str
    offset: float = 0.0
    drift_ppm: float = 0.0
    visible: bool = True
    payload: dict[str, Any] = dataclasses.field(default_factory=dict)


@runtime_checkable
class MutationTarget(Protocol):
    """The operations a command needs from the live application.

    The UI implements this; the bus only ever sees the protocol.  That is what
    keeps ``core/`` headless and lets :mod:`tests.test_document` exercise every
    command against a plain fake instead of a running ``QApplication``.

    Every method must be safe to call from the UI thread and must not block —
    architecture rule 3 applies to undo as much as to anything else.
    """

    def set_source_mapping(self, source_id: str, offset: float, drift_ppm: float) -> None:
        """Apply a source-to-master ``offset`` and ``drift_ppm``."""

    def source_mapping(self, source_id: str) -> tuple[float, float]:
        """Return the current ``(offset, drift_ppm)`` for *source_id*."""

    def add_marker(self, marker: MarkerRecord) -> None:
        """Insert *marker* into the annotation store."""

    def remove_marker(self, marker: MarkerRecord) -> None:
        """Remove the marker matching *marker* from the annotation store."""

    def set_marker_label(self, index: int, label: str) -> None:
        """Set the label of the marker at *index*."""

    def set_source_visible(self, source_id: str, visible: bool) -> None:
        """Show or hide a whole source without unloading it."""

    def set_channel_visible(self, source_id: str, channel: str, visible: bool) -> None:
        """Show or hide one channel of a time-series source."""

    def set_overlay_visible(self, overlay_id: str, camera: str | None, visible: bool) -> None:
        """Show or hide a registered overlay layer, globally or for one camera."""

    def set_tracked_point(
        self, source_id: str, point: str, index: int, position: tuple[float, float] | None
    ) -> None:
        """Override one tracked coordinate, or clear it when *position* is None.

        ``index`` is the sample index within *source_id*; ``position`` is in
        that recording's own video pixels.  The imported file and its cache are
        never written -- see :mod:`avialsync.core.point_edits`.
        """

    def add_source(self, record: SourceRecord) -> None:
        """Load a source back into the workspace."""

    def remove_source(self, source_id: str) -> None:
        """Unload a source from the workspace."""

    def apply_sync(self, source_id: str, offset: float, drift_ppm: float, evidence: Any) -> None:
        """Apply an accepted synchronization proposal, retaining its evidence."""

    def capture_workspace(self) -> Any:
        """Return an opaque snapshot sufficient to restore the whole workspace.

        Only :class:`ResetSessionCommand` uses this.  See D-087 for why it is
        not the general mechanism.
        """

    def restore_workspace(self, snapshot: Any) -> None:
        """Restore a snapshot previously returned by :meth:`capture_workspace`."""

    def clear_workspace(self) -> None:
        """Return the workspace to its empty, ready-to-open state."""


class Command(Protocol):
    """One reversible, user-visible mutation.

    ``label`` is shown verbatim in the Edit menu ("Set offset for cam2.mp4 to
    1.240 s"), so write it as the user would read it, not as a method name.
    """

    command_id: str

    @property
    def label(self) -> str:
        """What the Edit menu shows for this mutation."""

    def apply(self, target: MutationTarget) -> None:
        """Perform the mutation."""

    def revert(self, target: MutationTarget) -> None:
        """Undo exactly what :meth:`apply` did."""


def _merged(first: Any, second: Any) -> Any | None:
    """Return a command combining *first* then *second*, or ``None``.

    Coalescing lives here rather than on the protocol so that a command type
    which does not merge needs no boilerplate.  Only continuous controls merge:
    a spin-box drag emits ``valueChanged`` on every step, and without this a
    single drag would push two hundred entries and evict the real history
    behind it (WP-1 step 6).
    """
    merge = getattr(first, "merge_with", None)
    if merge is None:
        return None
    result = merge(second)
    return result


class Document:
    """The session's mutation log, and the single source of dirty state.

    Observers are plain callables, not Qt signals — this class must remain
    importable without PySide6.  The UI adapter converts them to signals.
    """

    def __init__(self, *, max_log_entries: int = MAX_LOG_ENTRIES) -> None:
        self._max_log_entries = max_log_entries
        self._done: list[Command] = []
        self._undone: list[Command] = []
        self._clean_depth = 0
        self._evicted = False
        self._observers: list[Callable[[bool], None]] = []
        self._log_observers: list[Callable[[], None]] = []
        self._session_path: str | None = None
        self._last_change: float = 0.0

    # ── dirty state ──────────────────────────────────────────────────

    @property
    def is_dirty(self) -> bool:
        """Whether the session has changes not present in the saved file.

        Once history has been evicted past the last save point the document can
        no longer prove itself clean by returning to a depth, so it stays dirty.
        Reporting clean on a document whose evidence has been discarded is the
        one failure mode here that silently loses a user's work.
        """
        if self._evicted and self._clean_depth > 0:
            return True
        return len(self._done) != self._clean_depth

    @property
    def session_path(self) -> str | None:
        """Path this document was last saved to or loaded from, if any."""
        return self._session_path

    @session_path.setter
    def session_path(self, path: str | None) -> None:
        self._session_path = path

    @property
    def last_change_time(self) -> float:
        """``time.time()`` of the most recent mutation, or 0.0 if untouched."""
        return self._last_change

    def observe_log(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register *callback*, called whenever the undo history changes.

        Distinct from :meth:`observe_dirty`, which fires only on a clean/dirty
        transition. An Edit menu needs more than that: recording a second
        command while already dirty changes what Undo would reverse and what it
        should be called, but crosses no transition at all.
        """
        self._log_observers.append(callback)

        def _dispose() -> None:
            if callback in self._log_observers:
                self._log_observers.remove(callback)

        return _dispose

    def _notify_log(self) -> None:
        for callback in list(self._log_observers):
            callback()

    def observe_dirty(self, callback: Callable[[bool], None]) -> Callable[[], None]:
        """Register *callback*, called with the new dirty state on change.

        Returns a function that unregisters it.  The callback fires only on a
        genuine transition, so a caller may connect a title repaint to it
        directly without adding a second throttle.
        """
        self._observers.append(callback)

        def _dispose() -> None:
            if callback in self._observers:
                self._observers.remove(callback)

        return _dispose

    def mark_saved(self) -> None:
        """Record that the current state has been written to disk."""
        was_dirty = self.is_dirty
        self._clean_depth = len(self._done)
        self._evicted = False
        self._notify(was_dirty)
        self._notify_log()

    def _notify(self, was_dirty: bool) -> None:
        now_dirty = self.is_dirty
        if now_dirty == was_dirty:
            return
        for callback in list(self._observers):
            callback(now_dirty)

    # ── the log ──────────────────────────────────────────────────────

    def execute(self, command: Command, target: MutationTarget) -> None:
        """Apply *command* to *target* and record it as undoable.

        A command that merges with the one before it replaces that entry rather
        than adding another, so a continuous drag stays a single undo step.
        """
        was_dirty = self.is_dirty
        command.apply(target)
        self._discard_redo()

        if self._done and len(self._done) > self._clean_depth:
            combined = _merged(self._done[-1], command)
            if combined is not None:
                self._done[-1] = combined
                self._last_change = time.time()
                self._notify(was_dirty)
                self._notify_log()
                return

        self._done.append(command)
        self._trim()
        self._last_change = time.time()
        self._notify(was_dirty)
        self._notify_log()

    def record(self, command: Command) -> None:
        """Record an already-applied *command* without re-applying it.

        For mutations the UI performs itself before the bus hears about them.
        Prefer :meth:`execute`; this exists so that wiring an existing widget
        does not require inverting its signal order first.
        """
        was_dirty = self.is_dirty
        self._discard_redo()
        if self._done and len(self._done) > self._clean_depth:
            combined = _merged(self._done[-1], command)
            if combined is not None:
                self._done[-1] = combined
                self._last_change = time.time()
                self._notify(was_dirty)
                self._notify_log()
                return
        self._done.append(command)
        self._trim()
        self._last_change = time.time()
        self._notify(was_dirty)
        self._notify_log()

    def _discard_redo(self) -> None:
        """Drop the redo stack after a new command diverges from it.

        Those commands are unreachable from here on, so anything they hold for
        undo's benefit is released with them.
        """
        if not self._undone:
            return
        released(self._undone)
        self._undone.clear()

    def _trim(self) -> None:
        overflow = len(self._done) - self._max_log_entries
        if overflow <= 0:
            return
        # An evicted command can never be undone again, so anything it was
        # holding on undo's behalf must go with it.  Without this the one
        # sanctioned bulk snapshot (ResetSessionCommand) would outlive its
        # usefulness and quietly defeat the memory bound this cap exists for.
        released(self._done[:overflow])
        del self._done[:overflow]
        self._clean_depth -= overflow
        if self._clean_depth < 0:
            self._clean_depth = 0
            self._evicted = True

    def can_undo(self) -> bool:
        """Whether there is a command to undo."""
        return bool(self._done)

    def can_redo(self) -> bool:
        """Whether there is an undone command to redo."""
        return bool(self._undone)

    def undo_label(self) -> str | None:
        """Label of the command :meth:`undo` would reverse."""
        return self._done[-1].label if self._done else None

    def redo_label(self) -> str | None:
        """Label of the command :meth:`redo` would re-apply."""
        return self._undone[-1].label if self._undone else None

    def undo(self, target: MutationTarget) -> bool:
        """Reverse the most recent command.  Returns whether anything happened."""
        if not self._done:
            return False
        was_dirty = self.is_dirty
        command = self._done.pop()
        command.revert(target)
        self._undone.append(command)
        self._last_change = time.time()
        self._notify(was_dirty)
        self._notify_log()
        return True

    def redo(self, target: MutationTarget) -> bool:
        """Re-apply the most recently undone command."""
        if not self._undone:
            return False
        was_dirty = self.is_dirty
        command = self._undone.pop()
        command.apply(target)
        self._done.append(command)
        self._last_change = time.time()
        self._notify(was_dirty)
        self._notify_log()
        return True

    def clear(self) -> None:
        """Drop all history and mark the document clean.

        Called when a session is loaded: undo is session-scoped, and carrying a
        previous session's commands across a load would let undo apply them to
        sources that are no longer there.
        """
        was_dirty = self.is_dirty
        released(self._done)
        released(self._undone)
        self._done.clear()
        self._undone.clear()
        self._clean_depth = 0
        self._evicted = False
        self._notify(was_dirty)
        self._notify_log()

    def __len__(self) -> int:
        return len(self._done)

    def __iter__(self) -> Iterator[Command]:
        return iter(self._done)

    # ── recovery ─────────────────────────────────────────────────────

    def recovery_payload(self, state: Any) -> dict[str, Any]:
        """Wrap a serialised session *state* as a recovery snapshot (D-089).

        The snapshot carries the originating path when there was one, so the
        launch-time check can compare it against that file's mtime and stay
        quiet when the saved file is already newer.
        """
        return {
            "recovered_at": time.time(),
            "session_path": self._session_path,
            "state": state,
        }


def released(commands: Sequence[Command]) -> None:
    """Release any bulk state held by *commands* being evicted from the log.

    Only :class:`~avialsync.core.commands.ResetSessionCommand` holds anything,
    but the bus must not know that: a future command that retains something is
    freed correctly without touching this file.
    """
    for command in commands:
        release = getattr(command, "release", None)
        if callable(release):
            release()
