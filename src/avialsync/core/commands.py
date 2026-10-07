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

from avialsync.core.custom_markers import CustomMarker
from avialsync.core.document import MarkerRecord, MutationTarget, SourceRecord
from avialsync.core.physical_props import Ladder, LadderLayout, LadderStep, PhysicalProp
from avialsync.core.wheel import Wheel

__all__ = [
    "SetSourceMappingCommand",
    "AddMarkerCommand",
    "RemoveMarkerCommand",
    "RelabelMarkerCommand",
    "SetSourceVisibleCommand",
    "SetImagingViewCommand",
    "SetChannelVisibleCommand",
    "SetChannelGroupVisibleCommand",
    "SetOverlayVisibleCommand",
    "SetTrackingVisibleCommand",
    "SetOriginalTrackerVisibleCommand",
    "SetTrackedPointCommand",
    "SetIdentitySwapCommand",
    "SetIdentityGroupCommand",
    "ClearIdentitySwapsCommand",
    "SetCustomMarkerCommand",
    "SetWheelCommand",
    "SetLadderCommand",
    "SetPhysicalPropCommand",
    "SetLadderStepCommand",
    "MoveLadderStepCommand",
    "SetLadderLayoutCommand",
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
class SetImagingViewCommand:
    """Change how an imaging stack is shown: channels, levels, averaging (D-190).

    Merges with the next change to the same *aspect* of the same stack, so a
    brightness drag is one undo step while a brightness drag followed by a
    contrast drag stays two.
    """

    source_id: str
    before: dict[str, Any]
    after: dict[str, Any]
    aspect: str
    display_name: str = ""
    command_id: str = "imaging.view"

    @property
    def label(self) -> str:
        return f"Change {self.aspect} for {self.display_name or self.source_id}"

    def apply(self, target: MutationTarget) -> None:
        target.set_imaging_view(self.source_id, self.after)

    def revert(self, target: MutationTarget) -> None:
        target.set_imaging_view(self.source_id, self.before)

    def merge_with(self, other: object) -> SetImagingViewCommand | None:
        if not isinstance(other, SetImagingViewCommand):
            return None
        if (other.source_id, other.aspect) != (self.source_id, self.aspect):
            return None
        return dataclasses.replace(self, after=other.after)


@dataclasses.dataclass
class SetImagingLayoutCommand:
    """Read an imaging stack with another axis order or depth plane (D-194).

    *before* and *after* hold the ``axes`` and ``z`` import choices. A stack
    opens with a default order so it is visible at once; this is how the user
    corrects it, and how that correction is undone.
    """

    source_id: str
    before: dict[str, Any]
    after: dict[str, Any]
    display_name: str = ""
    command_id: str = "imaging.layout"

    @property
    def label(self) -> str:
        return f"Change axes for {self.display_name or self.source_id}"

    def apply(self, target: MutationTarget) -> None:
        target.set_imaging_layout(self.source_id, self.after)

    def revert(self, target: MutationTarget) -> None:
        target.set_imaging_layout(self.source_id, self.before)


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
class SetChannelGroupVisibleCommand:
    """Show or hide a whole group of channels at once.

    One command rather than one per channel. Hiding a group of forty is a
    single decision, and an undo history that needed forty presses to reverse
    one click would be worse than no undo for it.

    ``before`` holds each channel's previous state rather than a single flag,
    so undoing a mixed group restores the mixture instead of turning
    everything on.
    """

    source_id: str
    group_label: str
    before: dict[str, bool]
    visible: bool
    command_id: str = "channel_group.visible"

    @property
    def label(self) -> str:
        count = len(self.before)
        verb = "Show" if self.visible else "Hide"
        return f"{verb} {count} channels in {self.group_label}"

    def apply(self, target: MutationTarget) -> None:
        for channel in self.before:
            target.set_channel_visible(self.source_id, channel, self.visible)

    def revert(self, target: MutationTarget) -> None:
        for channel, was_visible in self.before.items():
            target.set_channel_visible(self.source_id, channel, was_visible)


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
class SetTrackingVisibleCommand:
    """Show or hide one tracking source on one presentation surface."""

    source_id: str
    surface: str
    visible: bool
    display_name: str = ""
    command_id: str = "tracking.visible"

    @property
    def label(self) -> str:
        name = self.display_name or self.source_id
        verb = "Show" if self.visible else "Hide"
        return f"{verb} {self.surface} for {name}"

    def apply(self, target: MutationTarget) -> None:
        target.set_tracking_visible(self.source_id, self.surface, self.visible)

    def revert(self, target: MutationTarget) -> None:
        target.set_tracking_visible(self.source_id, self.surface, not self.visible)


@dataclasses.dataclass
class SetOriginalTrackerVisibleCommand:
    """Switch the pose readers between the raw and edited cache generations."""

    visible: bool
    command_id: str = "tracking.original_view"

    @property
    def label(self) -> str:
        return "Play original tracking" if self.visible else "Play edited tracking"

    def apply(self, target: MutationTarget) -> None:
        target.set_original_tracker_visible(self.visible)

    def revert(self, target: MutationTarget) -> None:
        target.set_original_tracker_visible(not self.visible)


@dataclasses.dataclass
class SetTrackedPointCommand:
    """Move one tracked body part to where the user says it really was.

    ``before`` and ``after`` are the *override* on either side of the drag, not
    the model's prediction: ``None`` means "no correction here", so undoing the
    first correction of a point restores the prediction rather than pinning it
    as a correction of itself.  Nothing about the imported file or its cache is
    carried -- see :mod:`avialsync.core.point_edits` for why an edit is an
    overlay rather than a rewrite.

    Deliberately does not merge.  A drag commits once, on release, so each
    entry is already one gesture; coalescing successive corrections of the same
    point would make one Undo jump back past a deliberate second judgement.
    """

    source_id: str
    point: str
    index: int
    before: tuple[float, float] | None
    after: tuple[float, float] | None
    #: The video frame ``index`` names, for the menu text only. ``index`` is a
    #: sample index within the pose source and the two differ for a file that
    #: does not start at frame 0; resolving that needs the source's own time
    #: column, which ``core/`` has no business reaching for (the caller passes
    #: it, as ``display_name`` is passed elsewhere here).
    display_frame: int | None = None
    #: What the point was called on screen when it was dragged. Differs from
    #: ``point`` -- the file's own column -- only while an identity flip is in
    #: force, and is carried so undo and redo record the same provenance the
    #: original drag did (D-143).
    shown_as: str = ""
    command_id: str = "tracking.point"

    @property
    def label(self) -> str:
        frame = self.index if self.display_frame is None else self.display_frame
        name = self.shown_as or self.point
        if self.after is None:
            return f"Restore predicted {name} at frame {frame}"
        x, y = self.after
        return f"Move {name} to ({x:.1f}, {y:.1f}) px at frame {frame}"

    def apply(self, target: MutationTarget) -> None:
        target.set_tracked_point(self.source_id, self.point, self.index, self.after, self.shown_as)

    def revert(self, target: MutationTarget) -> None:
        target.set_tracked_point(self.source_id, self.point, self.index, self.before, self.shown_as)


@dataclasses.dataclass
class SetIdentitySwapCommand:
    """Accept or undo one identity flip on a pose source (D-141).

    The inverse of accepting a flip is *removing* it, not accepting its
    opposite: two transpositions compose to the identity and would look the
    same on screen, while leaving two events in the sidecar that say a person
    judged two crossings where they judged one.

    Carries no data, only the statement: the recording, its imported cache and
    the derived generation are all reproduced from this plus the corrections
    (:mod:`avialsync.core.edit_program`), so an undo costs nothing to store.
    """

    source_id: str
    event: Any
    accepted: bool
    #: The video frame ``event.index`` names, for the menu text only -- the same
    #: reason `SetTrackedPointCommand` carries one.
    display_frame: int | None = None
    command_id: str = "tracking.identity"

    @property
    def label(self) -> str:
        frame = self.display_frame if self.display_frame is not None else self.event.index
        first, second = self.event.lanes
        if self.accepted:
            return f"Swap {first} and {second} from frame {frame}"
        return f"Undo the {first}/{second} swap at frame {frame}"

    def apply(self, target: MutationTarget) -> None:
        target.set_identity_swap(self.source_id, self.event, self.accepted)

    def revert(self, target: MutationTarget) -> None:
        target.set_identity_swap(self.source_id, self.event, not self.accepted)


@dataclasses.dataclass
class ClearIdentitySwapsCommand:
    """Undo every accepted flip on one pose source, as one step.

    Carries the events rather than a snapshot of anything: they *are* the
    state, a few integers each, and putting them back is the whole inverse
    (rule 14 -- commands carry inverse operations, never snapshots).
    """

    source_id: str
    events: tuple[Any, ...]
    command_id: str = "tracking.identity_clear"

    @property
    def label(self) -> str:
        return f"Remove {len(self.events)} identity swap(s)"

    def apply(self, target: MutationTarget) -> None:
        for event in self.events:
            target.set_identity_swap(self.source_id, event, False)

    def revert(self, target: MutationTarget) -> None:
        for event in self.events:
            target.set_identity_swap(self.source_id, event, True)


@dataclasses.dataclass
class SetIdentityGroupCommand:
    """Add one declared group; undo removes only that declaration."""

    source_id: str
    group: Any
    command_id: str = "tracking.identity_group"

    @property
    def label(self) -> str:
        return f"Add identity group {self.group.name}"

    def apply(self, target: MutationTarget) -> None:
        target.set_identity_group(self.source_id, self.group, True)

    def revert(self, target: MutationTarget) -> None:
        target.set_identity_group(self.source_id, self.group, False)


@dataclasses.dataclass
class SetCustomMarkerCommand:
    """Add, move, or delete one hand-placed 3D marker on one frame.

    ``before`` and ``after`` are whole markers -- a handful of floats, the
    clicks plus the triangulated point -- so undoing a move restores the 3D
    position it had without triangulating again. ``None`` on either side is
    "no marker": ``before=None`` is an add, ``after=None`` a delete.
    """

    name: str
    frame: int
    before: CustomMarker | None
    after: CustomMarker | None
    command_id: str = "tracking.custom_marker"

    @property
    def label(self) -> str:
        if self.before is None:
            return f"Add 3D marker {self.name} at frame {self.frame}"
        if self.after is None:
            return f"Delete 3D marker {self.name} at frame {self.frame}"
        return f"Move 3D marker {self.name} at frame {self.frame}"

    def apply(self, target: MutationTarget) -> None:
        target.set_custom_marker(self.name, self.frame, self.after)

    def revert(self, target: MutationTarget) -> None:
        target.set_custom_marker(self.name, self.frame, self.before)


def _diameter_only(before: Any, after: Any) -> bool:
    """Whether *after* is *before* with only its bar diameter changed."""
    if before is None or after is None or before == after:
        return False
    return bool(dataclasses.replace(before, bar_diameter=after.bar_diameter) == after)


@dataclasses.dataclass
class SetWheelCommand:
    """Add, re-fit, or remove one wheel (D-113).

    ``before`` and ``after`` are whole wheels -- clicks, fit, and binding, a few
    dozen floats -- so undoing a re-fit restores the geometry it had without
    fitting again. ``None`` on either side is "no wheel".
    """

    name: str
    before: Wheel | None
    after: Wheel | None
    command_id: str = "tracking.wheel"

    @property
    def label(self) -> str:
        if self.before is None:
            return f"Add wheel {self.name}"
        if self.after is None:
            return f"Remove wheel {self.name}"
        return f"Change wheel {self.name}"

    def apply(self, target: MutationTarget) -> None:
        target.set_wheel(self.name, self.after)

    def revert(self, target: MutationTarget) -> None:
        target.set_wheel(self.name, self.before)

    def merge_with(self, other: object) -> SetWheelCommand | None:
        """Coalesce a run of bar-diameter steps into one undo step.

        Only a change of ``bar_diameter`` and nothing else merges, and only when
        it continues from where this one left off: arrow keys held on the
        diameter field are one adjustment, but a re-fit after it is not.
        """
        if not isinstance(other, SetWheelCommand) or other.name != self.name:
            return None
        if other.before != self.after:
            return None
        if not (
            _diameter_only(self.before, self.after) and _diameter_only(other.before, other.after)
        ):
            return None
        return dataclasses.replace(self, after=other.after)


@dataclasses.dataclass
class SetLadderCommand:
    """Accept or remove one ladder; removal's inverse retains its evidence."""

    name: str
    before: Ladder | None
    after: Ladder | None
    label: str
    command_id: str = "props.ladder"

    def apply(self, target: MutationTarget) -> None:
        target.set_ladder(self.name, self.after)

    def revert(self, target: MutationTarget) -> None:
        target.set_ladder(self.name, self.before)


@dataclasses.dataclass
class SetPhysicalPropCommand:
    """Add, edit, or remove one physical prop through the document bus."""

    name: str
    before: PhysicalProp | None
    after: PhysicalProp | None
    label: str
    command_id: str = "props.physical_prop"

    def apply(self, target: MutationTarget) -> None:
        target.set_physical_prop(self.name, self.after)

    def revert(self, target: MutationTarget) -> None:
        target.set_physical_prop(self.name, self.before)


@dataclasses.dataclass
class SetLadderStepCommand:
    """Change one clicked step; other steps are not copied into undo history."""

    ladder_name: str
    step_id: str
    before: LadderStep | None
    after: LadderStep | None
    label: str
    position: int | None = None
    command_id: str = "props.ladder_step"

    def apply(self, target: MutationTarget) -> None:
        target.set_ladder_step(self.ladder_name, self.step_id, self.after, self.position)

    def revert(self, target: MutationTarget) -> None:
        target.set_ladder_step(self.ladder_name, self.step_id, self.before, self.position)


@dataclasses.dataclass
class MoveLadderStepCommand:
    """Reorder one step using only its old and new indices."""

    ladder_name: str
    step_id: str
    before: int
    after: int
    label: str
    command_id: str = "props.ladder_step_move"

    def apply(self, target: MutationTarget) -> None:
        target.move_ladder_step(self.ladder_name, self.step_id, self.after)

    def revert(self, target: MutationTarget) -> None:
        target.move_ladder_step(self.ladder_name, self.step_id, self.before)


@dataclasses.dataclass
class SetLadderLayoutCommand:
    """Change a ladder's support or rung pattern, carrying only the two layouts."""

    ladder_name: str
    before: LadderLayout
    after: LadderLayout
    label: str
    command_id: str = "props.ladder_layout"

    def apply(self, target: MutationTarget) -> None:
        target.set_ladder_layout(self.ladder_name, self.after)

    def revert(self, target: MutationTarget) -> None:
        target.set_ladder_layout(self.ladder_name, self.before)


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
