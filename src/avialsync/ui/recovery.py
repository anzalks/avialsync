"""Crash and hot-exit recovery for sessions that were never saved.

``MainWindow.closeEvent`` has always documented "Always close" — the window
used to ``event.ignore()`` while a job ran, so a wedged probe on a network
share trapped the user in an application they could not quit.  That was fixed.
But it was only half a contract: ``session_controller.autosave()`` returned
early when there was no session path, so a session that had never been saved
had *no protection at all*.  Load four cameras, tune offsets, accept a fit,
drop forty annotations, never pick Save Session — and quitting discarded all of
it, silently.

The answer is not a save prompt.  A prompt is a gate, and the
application never blocks the user to tell them something.  Quitting
keeps proceeding without asking and becomes lossless instead: a recovery
snapshot is written unconditionally, and the *next* launch informs the user,
non-modally, that unsaved work is available.

The snapshot lives in the platform's app-data location, never in the user's own
directories — it is application state, not their document, and it must not
appear in their file manager next to the recordings.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QStandardPaths

from avialsync.core.session_io import (
    _EXACT_MAPPING_INLINE_LIMIT,
    _reusable_sidecar_digest,
    exact_mapping_dir,
    exact_pair_filename,
    load_exact_sidecars,
    prune_exact_sidecars,
)

if TYPE_CHECKING:
    from avialsync.core.session import SessionState

logger = logging.getLogger(__name__)

#: Snapshot filename inside the app-data directory.
_SNAPSHOT_NAME = "recovery.avv.json"
_DISMISSED_NAME = "recovery.dismissed.sha256"

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
    # An empty location is possible on a stripped-down system; fall back to
    # a temp dir rather than writing into the working directory, which would put
    # application state next to the user's recordings.
    base = Path(root) if root else Path(tempfile.gettempdir()) / "AvialSync"
    base.mkdir(parents=True, exist_ok=True)
    return base


def recovery_path() -> Path:
    """Return the snapshot's full path."""
    return recovery_dir() / _SNAPSHOT_NAME


def _fingerprint(snapshot: RecoverySnapshot) -> str:
    """Identify the work itself, regardless of a later autosave timestamp."""
    content = json.dumps(
        {"session_path": snapshot.session_path, "state": snapshot.state},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def dismiss_recovery(snapshot: RecoverySnapshot) -> None:
    """Remember that this version was declined, while preserving its snapshot."""
    try:
        (recovery_dir() / _DISMISSED_NAME).write_text(_fingerprint(snapshot), encoding="ascii")
    except OSError:
        logger.exception("Could not remember the dismissed recovery offer")


def _was_dismissed(snapshot: RecoverySnapshot) -> bool:
    try:
        return (recovery_dir() / _DISMISSED_NAME).read_text(encoding="ascii") == _fingerprint(
            snapshot
        )
    except FileNotFoundError:
        return False
    except OSError:
        logger.exception("Could not read the dismissed recovery marker")
        return False


def _attach_sidecar_ref(
    entry: object, mapping_path: Path, base_dir: Path, digest: str, count: int
) -> None:
    """Populate exact-mapping metadata on one serialised provenance dict."""
    if not isinstance(entry, dict):
        return
    entry["exact_master"] = []
    entry["exact_source"] = []
    entry["exact_mapping"] = {
        "file": mapping_path.relative_to(base_dir).as_posix(),
        "sha256": digest,
        "count": count,
    }


def write_recovery(
    state: dict[str, Any],
    session_path: str | None,
    *,
    exact_pairs: Sequence[tuple[NDArray[np.float64], NDArray[np.float64]]] = (),
    should_commit: Callable[[], bool] | None = None,
) -> bool:
    """Write a recovery snapshot and any large exact-sync sidecars atomically."""
    try:
        target = recovery_path()
        sidecar_dir = exact_mapping_dir(target)
        referenced: set[Path] = set()
        encoded_state = state
        raw_prov = state.get("sync_provenance")
        if exact_pairs and isinstance(raw_prov, list):
            prov_copy = [dict(item) if isinstance(item, dict) else item for item in raw_prov]
            for index, (master, source) in enumerate(exact_pairs):
                if len(master) <= _EXACT_MAPPING_INLINE_LIMIT or index >= len(prov_copy):
                    continue
                mc = np.ascontiguousarray(master, dtype=np.float64)
                sc = np.ascontiguousarray(source, dtype=np.float64)
                mapping_path = sidecar_dir / exact_pair_filename(mc, sc)
                digest = _reusable_sidecar_digest(mapping_path)
                if digest is None:
                    sidecar_dir.mkdir(parents=True, exist_ok=True)
                    sh, sname = tempfile.mkstemp(dir=str(sidecar_dir), suffix=".tmp.npz")
                    try:
                        with os.fdopen(sh, "wb") as npz_stream:
                            np.savez_compressed(npz_stream, master=mc, source=sc)
                        os.replace(sname, mapping_path)
                    except BaseException:
                        Path(sname).unlink(missing_ok=True)
                        raise
                    digest = hashlib.sha256(mapping_path.read_bytes()).hexdigest()
                referenced.add(mapping_path)
                _attach_sidecar_ref(prov_copy[index], mapping_path, target.parent, digest, len(mc))
            encoded_state = {**state, "sync_provenance": prov_copy}
        payload = {
            "recovered_at": time.time(),
            "session_path": session_path,
            "state": encoded_state,
        }
        handle, tmp_name = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream)
            if should_commit is not None and not should_commit():
                Path(tmp_name).unlink(missing_ok=True)
                return False
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        prune_exact_sidecars(sidecar_dir, referenced)
    except Exception:
        logger.exception("Could not write the recovery snapshot")
        return False
    return True


def decode_recovery_state(snapshot: RecoverySnapshot) -> SessionState:
    """Decode *snapshot* into a :class:`SessionState`, loading any exact-sync sidecars."""
    from avialsync.core.session import SessionState

    state = SessionState.from_dict(snapshot.state)
    for index, prepared in load_exact_sidecars(snapshot.state, recovery_dir()):
        state.sync_provenance[index].exact_master = prepared.master
        state.sync_provenance[index].exact_source = prepared.source
    return state


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

    Called after a successful explicit save, after a restore, and — importantly —
    on Reset Session. A reset empties
    the workspace and sets ``_session_path`` to ``None``; leaving the snapshot
    in place would let a subsequent quit overwrite good unsaved work with an
    empty workspace, turning the safety net into the data loss it exists to
    prevent.
    """
    try:
        target = recovery_path()
        target.unlink(missing_ok=True)
        (recovery_dir() / _DISMISSED_NAME).unlink(missing_ok=True)
        shutil.rmtree(exact_mapping_dir(target), ignore_errors=True)
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
        return snapshot if snapshot.state and not _was_dismissed(snapshot) else None

    session_file = Path(str(snapshot.session_path))
    try:
        if not session_file.exists():
            return None if _was_dismissed(snapshot) else snapshot
        if snapshot.recovered_at > session_file.stat().st_mtime + _NEWER_THAN_SAVE_MARGIN_S:
            return None if _was_dismissed(snapshot) else snapshot
    except OSError:
        return None if _was_dismissed(snapshot) else snapshot

    clear_recovery()
    return None


_RECOVERABLE_KEYS = (
    "videos",
    "imaging",
    "sensors",
    "markers",
    "sync_provenance",
    "triggers",
    "point_edits",
    "identity_swaps",
)


def is_empty_state(state: dict[str, Any]) -> bool:
    """Whether *state* holds nothing worth recovering.

    An empty workspace never produces a snapshot: writing one would replace a
    good snapshot with nothing, which is exactly the reset-then-quit trap.
    """
    return not any(state.get(key) for key in _RECOVERABLE_KEYS)
