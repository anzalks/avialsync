"""Runtime metadata for the currently open session."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from avialsync.ui.recovery import RecoverySnapshot


@dataclass
class SessionRuntimeState:
    """Session identity, declared metadata, and pending recovery offer."""

    path: Path | None = None
    generation: int = 0
    # Set before menu preconditions inspect it; no file read per sweep.
    pending_recovery: RecoverySnapshot | None = None
    # Async source arrivals during restore must not register as user edits.
    restoring: bool = False
    # The generation whose restore puts back work no file holds, so it ends
    # dirty rather than saved: deleting the cache reloads the trial (D-160).
    # A generation, not a flag, so a reset in between makes it stale.
    dirty_after_restore: int | None = None
    # Format-neutral declarations supplied by the session loader.
    camera_fps: float = 0.0
    anchor_epoch: float = 0.0
    item_labels: dict[str, str] = field(default_factory=dict)
    item_kinds: dict[str, str] = field(default_factory=dict)
    coverage_groups: dict[str, str] = field(default_factory=dict)
    # Unix epoch of master-clock zero, until a source declares wall time.
    start_time: float = 0.0

    def take_dirty_after_restore(self) -> bool:
        """Whether the restore that just drained put back unsaved work; clears it."""
        dirty = self.dirty_after_restore == self.generation
        self.dirty_after_restore = None
        return dirty
