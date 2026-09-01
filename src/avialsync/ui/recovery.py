"""Crash and hot-exit recovery for sessions that were never saved (D-089).

``MainWindow.closeEvent`` has always documented "Always close" — the window
used to ``event.ignore()`` while a job ran, so a wedged probe on a network
share trapped the user in an application they could not quit.  That was fixed.
But it was only half a contract: ``session_controller.autosave()`` returned
early when there was no session path, so a session that had never been saved
had *no protection at all*.  Load four cameras, tune offsets, accept a fit,
drop forty annotations, never pick Save Session — and quitting discarded all of
it, silently.

The answer is not a save prompt.  A prompt is a gate, and Law 1 says the
application never blocks the user to tell them something (D-088).  Quitting
keeps proceeding without asking and becomes lossless instead: a recovery
snapshot is written unconditionally, and the *next* launch informs the user,
non-modally, that unsaved work is available.

The snapshot lives in the platform's app-data location, never in the user's own
directories — it is application state, not their document, and it must not
appear in their file manager next to the recordings.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QStandardPaths

logger = logging.getLogger(__name__)

#: Snapshot filename inside the app-data directory.
_SNAPSHOT_NAME = "recovery.avv.json"

#: A snapshot this much newer than its session file (seconds) counts as unsaved
#: work.  Without a margin, a snapshot written microseconds before the save it
#: accompanies would look like work the save did not capture, and every clean
#: quit would offer a pointless recovery on the next launch.
_NEWER_THAN_SAVE_MARGIN_S = 2.0


@dataclasses.dataclass(frozen=True)
class RecoverySnapshot:
    """Unsaved work found at launch."""

    recovered_at: float
    session_path: str | None
    state: dict[str, Any]

    @property
    def describes_untitled_session(self) -> bool:
        """Whether this snapshot belongs to a session that was never saved."""
        return not self.session_path


def recovery_dir() -> Path:
    """Return the app-data directory holding the snapshot, creating it."""
    root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    # An empty location is possible on a stripped test environment; fall back to
    # a temp dir rather than writing into the working directory, which would put
    # application state next to the user's recordings.
    base = Path(root) if root else Path(tempfile.gettempdir()) / "AvialSync"
    base.mkdir(parents=True, exist_ok=True)
    return base


def recovery_path() -> Path:
    """Return the snapshot's full path."""
    return recovery_dir() / _SNAPSHOT_NAME


def write_recovery(state: dict[str, Any], session_path: str | None) -> bool:
    """Write a recovery snapshot atomically.  Returns whether it was written.

    Called on the two-minute autosave when there is no session path, and
    unconditionally at close.  Never raises: this runs during shutdown, where a
    raised exception would abandon the remaining teardown steps and leave the
    process alive with decoder threads running — the "window won't close" the
    user actually sees.
    """
    payload = {
        "recovered_at": time.time(),
        "session_path": session_path,
        "state": state,
    }
    try:
        target = recovery_path()
        # Atomic replace, so an interrupted write leaves the previous good
        # snapshot rather than a truncated one. The cache layer takes the same
        # approach for the same reason.
        handle, tmp_name = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream)
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
    except Exception:
        logger.exception("Could not write the recovery snapshot")
        return False
    return True


def read_recovery() -> RecoverySnapshot | None:
    """Return the stored snapshot, or ``None`` if there is nothing usable.

    A corrupt snapshot is discarded rather than reported: it is a safety net,
    and a safety net that raises on the way up is worse than one that is absent.
    """
    path = recovery_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return RecoverySnapshot(
            recovered_at=float(payload["recovered_at"]),
            session_path=payload.get("session_path"),
            state=payload["state"],
        )
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("Discarding an unreadable recovery snapshot at %s", path)
        clear_recovery()
        return None


def clear_recovery() -> None:
    """Remove the snapshot.

    Called after a successful explicit save, after the user discards or
    restores the offer, and — importantly — on Reset Session.  A reset empties
    the workspace and sets ``_session_path`` to ``None``; leaving the snapshot
    in place would let a subsequent quit overwrite good unsaved work with an
    empty workspace, turning the safety net into the data loss it exists to
    prevent (WP-1 step 7).
    """
    try:
        recovery_path().unlink(missing_ok=True)
    except OSError:
        logger.exception("Could not clear the recovery snapshot")


def pending_recovery() -> RecoverySnapshot | None:
    """Return unsaved work worth offering at launch, or ``None``.

    A snapshot whose session file is already at least as new was superseded by
    a real save and is silently dropped — offering it would train the user to
    dismiss the bar without reading it.
    """
    snapshot = read_recovery()
    if snapshot is None:
        return None
    if snapshot.describes_untitled_session:
        return snapshot if snapshot.state else None

    session_file = Path(str(snapshot.session_path))
    try:
        if not session_file.exists():
            return snapshot
        if snapshot.recovered_at > session_file.stat().st_mtime + _NEWER_THAN_SAVE_MARGIN_S:
            return snapshot
    except OSError:
        return snapshot

    clear_recovery()
    return None


def is_empty_state(state: dict[str, Any]) -> bool:
    """Whether *state* holds nothing worth recovering.

    An empty workspace never produces a snapshot: writing one would replace a
    good snapshot with nothing, which is exactly the reset-then-quit trap.
    """
    return not any(state.get(key) for key in ("videos", "sensors", "markers", "sync_provenance"))
