"""The concrete, reversible mutations (D-087).

Each command is a small frozen-ish dataclass holding exactly what it needs to
go both ways — an offset command is a source id and two float pairs, roughly 80
bytes.  None of them snapshot session state; :class:`ResetSessionCommand` is the
single sanctioned exception and documents why.

``label`` is what the user reads in the Edit menu, so it is written as prose
("Set offset for cam2.mp4 to 1.240 s"), not as a method name.

Commands that back a continuous control implement ``merge_with`` so that a
drag or a burst of typing collapses into one undo step (WP-1 step 6).  The bus
calls it; nothing else should.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from avialsync.core.document import MarkerRecord, MutationTarget, SourceRecord

__all__ = [
    "SetSourceMappingCommand",
    "AddMarkerCommand",
    "RemoveMarkerCommand",
    "RelabelMarkerCommand",
    "SetSourceVisibleCommand",
    "SetChannelVisibleCommand",
    "SetOverlayVisibleCommand",
    "AcceptSyncCommand",
    "AddSourceCommand",
    "RemoveSourceCommand",
    "ResetSessionCommand",
]


#
# Each is a small frozen dataclass holding the values needed to go both ways.
# `label` is written as the user reads it in the Edit menu.


@dataclasses.dataclass
class SetSourceMappingCommand:
    """Change a source's offset and drift.

    Merges with itself so that dragging the offset spin box is one undo step
    (WP-1 step 6).  The merged command keeps the *original* before-values, so
    undoing a drag returns to where it started rather than to its penultimate
    step.
    """

    source_id: str
    before: tuple[float, float]
    after: tuple[float, float]
    display_name: str = ""
    command_id: str = "source.mapping"

    @property
    def label(self) -> str:
        name = self.display_name or self.source_id
        return f"Set offset for {name} to {self.after[0]:.3f} s"

    def apply(self, target: MutationTarget) -> None:
        target.set_source_mapping(self.source_id, self.after[0], self.after[1])

    def revert(self, target: MutationTarget) -> None:
        target.set_source_mapping(self.source_id, self.before[0], self.before[1])

    def merge_with(self, other: object) -> SetSourceMappingCommand | None:
        if not isinstance(other, SetSourceMappingCommand):
            return None
        if other.source_id != self.source_id:
            return None
        return dataclasses.replace(self, after=other.after)


@dataclasses.dataclass
class AddMarkerCommand:
    """Add an annotation marker."""

    marker: MarkerRecord
    command_id: str = "marker.add"

    @property
    def label(self) -> str:
        return f"Add marker {self.marker.label!r}" if self.marker.label else "Add marker"

    def apply(self, target: MutationTarget) -> None:
        target.add_marker(self.marker)

    def revert(self, target: MutationTarget) -> None:
        target.remove_marker(self.marker)


@dataclasses.dataclass
class RemoveMarkerCommand:
    """Delete an annotation marker."""

    marker: MarkerRecord
    command_id: str = "marker.remove"

    @property
    def label(self) -> str:
        return f"Delete marker {self.marker.label!r}" if self.marker.label else "Delete marker"

    def apply(self, target: MutationTarget) -> None:
        target.remove_marker(self.marker)

    def revert(self, target: MutationTarget) -> None:
        target.add_marker(self.marker)


@dataclasses.dataclass
class RelabelMarkerCommand:
    """Rename an annotation marker.

    Merges with itself so that typing a label is one undo step rather than one
    per keystroke.
    """

    index: int
    before: str
    after: str
    command_id: str = "marker.relabel"

    @property
    def label(self) -> str:
        return f"Rename marker to {self.after!r}"

    def apply(self, target: MutationTarget) -> None:
        target.set_marker_label(self.index, self.after)

    def revert(self, target: MutationTarget) -> None:
        target.set_marker_label(self.index, self.before)

    def merge_with(self, other: object) -> RelabelMarkerCommand | None:
        if not isinstance(other, RelabelMarkerCommand) or other.index != self.index:
            return None
        return dataclasses.replace(self, after=other.after)


@dataclasses.dataclass
class SetSourceVisibleCommand:
    """Show or hide a whole source without unloading it."""

    source_id: str
    visible: bool
    display_name: str = ""
    command_id: str = "source.visible"

    @property
    def label(self) -> str:
        name = self.display_name or self.source_id
        return f"{'Show' if self.visible else 'Hide'} {name}"

    def apply(self, target: MutationTarget) -> None:
        target.set_source_visible(self.source_id, self.visible)

    def revert(self, target: MutationTarget) -> None:
        target.set_source_visible(self.source_id, not self.visible)


@dataclasses.dataclass
class SetChannelVisibleCommand:
    """Show or hide one channel of a time-series source."""

    source_id: str
    channel: str
    visible: bool
    command_id: str = "channel.visible"

    @property
    def label(self) -> str:
        return f"{'Show' if self.visible else 'Hide'} channel {self.channel}"

    def apply(self, target: MutationTarget) -> None:
        target.set_channel_visible(self.source_id, self.channel, self.visible)

    def revert(self, target: MutationTarget) -> None:
        target.set_channel_visible(self.source_id, self.channel, not self.visible)


@dataclasses.dataclass
class SetOverlayVisibleCommand:
    """Show or hide a registered overlay layer (D-090).

    ``camera`` is ``None`` for the global default and a camera path for a
    per-pane override.
    """

    overlay_id: str
    visible: bool
    camera: str | None = None
    display_name: str = ""
    command_id: str = "overlay.visible"

    @property
    def label(self) -> str:
        name = self.display_name or self.overlay_id
        verb = "Show" if self.visible else "Hide"
        return f"{verb} overlay {name}" if self.camera is None else f"{verb} {name} on this camera"

    def apply(self, target: MutationTarget) -> None:
        target.set_overlay_visible(self.overlay_id, self.camera, self.visible)

    def revert(self, target: MutationTarget) -> None:
        target.set_overlay_visible(self.overlay_id, self.camera, not self.visible)


@dataclasses.dataclass
class AcceptSyncCommand:
    """Apply an accepted synchronization proposal.

    Acceptance stays explicit (architecture rule 8); this only makes the
    accepted result reversible, so a user who accepts the wrong fit is not left
    reconstructing their previous mapping by hand.
    """

    source_id: str
    before: tuple[float, float]
    after: tuple[float, float]
    evidence: Any = None
    before_evidence: Any = None
    command_id: str = "sync.accept"

    @property
    def label(self) -> str:
        return f"Accept alignment for {self.source_id}"

    def apply(self, target: MutationTarget) -> None:
        target.apply_sync(self.source_id, self.after[0], self.after[1], self.evidence)

    def revert(self, target: MutationTarget) -> None:
        target.apply_sync(self.source_id, self.before[0], self.before[1], self.before_evidence)


@dataclasses.dataclass
class AddSourceCommand:
    """Load a source into the workspace."""

    record: SourceRecord
    command_id: str = "source.add"

    @property
    def label(self) -> str:
        return f"Open {self.record.path}"

    def apply(self, target: MutationTarget) -> None:
        target.add_source(self.record)

    def revert(self, target: MutationTarget) -> None:
        target.remove_source(self.record.source_id)


@dataclasses.dataclass
class RemoveSourceCommand:
    """Unload a source, retaining enough to put it back."""

    record: SourceRecord
    command_id: str = "source.remove"

    @property
    def label(self) -> str:
        return f"Close {self.record.path}"

    def apply(self, target: MutationTarget) -> None:
        target.remove_source(self.record.source_id)

    def revert(self, target: MutationTarget) -> None:
        target.add_source(self.record)


@dataclasses.dataclass
class ResetSessionCommand:
    """Return the workspace to empty, reversibly.

    Reset Session is the most destructive action in the application: one
    sidebar button cancels pending loads, removes every pane, and clears both
    the annotation and message stores.  It had no confirmation and no undo.

    It is also the single command whose inverse legitimately needs a bulk
    snapshot rather than a small inverse operation — there is no compact way to
    describe "everything that was open".  D-087 permits that for reset alone,
    capped at one retained state held only while this command sits on the undo
    stack.  It is not a licence to generalise snapshotting, which is the thing
    that entry exists to forbid.

    The snapshot is captured on first :meth:`apply` and dropped by
    :meth:`release`, which the adapter calls when the command is evicted.
    """

    snapshot: Any = None
    command_id: str = "session.reset"
    label: str = "Reset session"

    def apply(self, target: MutationTarget) -> None:
        if self.snapshot is None:
            self.snapshot = target.capture_workspace()
        target.clear_workspace()

    def revert(self, target: MutationTarget) -> None:
        if self.snapshot is not None:
            target.restore_workspace(self.snapshot)

    def release(self) -> None:
        """Drop the retained workspace, once this command can no longer be undone."""
        self.snapshot = None
