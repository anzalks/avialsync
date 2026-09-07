"""Tests for the headless command bus (WP-1, D-087).

Every command is exercised against :class:`FakeTarget` rather than a running
``QApplication``.  That is the point of the ``MutationTarget`` protocol: if
these tests ever need Qt, the boundary has been broken.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from avialsync.core.commands import (
    AcceptSyncCommand,
    AddMarkerCommand,
    AddSourceCommand,
    RelabelMarkerCommand,
    RemoveMarkerCommand,
    RemoveSourceCommand,
    ResetSessionCommand,
    SetChannelVisibleCommand,
    SetOverlayVisibleCommand,
    SetSourceMappingCommand,
    SetSourceVisibleCommand,
)
from avialsync.core.document import (
    MAX_LOG_ENTRIES,
    Document,
    MarkerRecord,
    MutationTarget,
    SourceRecord,
)


class FakeTarget:
    """A dictionary-backed stand-in for the live application."""

    def __init__(self) -> None:
        self.mappings: dict[str, tuple[float, float]] = {}
        self.markers: list[MarkerRecord] = []
        self.source_visible: dict[str, bool] = {}
        self.channel_visible: dict[tuple[str, str], bool] = {}
        self.overlay_visible: dict[tuple[str, str | None], bool] = {}
        self.tracked_points: dict[tuple[str, str, int], tuple[float, float] | None] = {}
        self.sources: dict[str, SourceRecord] = {}
        self.sync_evidence: dict[str, Any] = {}
        self.cleared = 0
        self.captures = 0

    def set_source_mapping(self, source_id: str, offset: float, drift_ppm: float) -> None:
        self.mappings[source_id] = (offset, drift_ppm)

    def source_mapping(self, source_id: str) -> tuple[float, float]:
        return self.mappings.get(source_id, (0.0, 0.0))

    def add_marker(self, marker: MarkerRecord) -> None:
        self.markers.append(marker)

    def remove_marker(self, marker: MarkerRecord) -> None:
        self.markers = [m for m in self.markers if m != marker]

    def set_marker_label(self, index: int, label: str) -> None:
        self.markers[index] = dataclasses.replace(self.markers[index], label=label)

    def set_source_visible(self, source_id: str, visible: bool) -> None:
        self.source_visible[source_id] = visible

    def set_channel_visible(self, source_id: str, channel: str, visible: bool) -> None:
        self.channel_visible[(source_id, channel)] = visible

    def set_overlay_visible(self, overlay_id: str, camera: str | None, visible: bool) -> None:
        self.overlay_visible[(overlay_id, camera)] = visible

    def set_tracked_point(
        self, source_id: str, point: str, index: int, position: tuple[float, float] | None
    ) -> None:
        key = (source_id, point, index)
        if position is None:
            self.tracked_points.pop(key, None)
        else:
            self.tracked_points[key] = position

    def add_source(self, record: SourceRecord) -> None:
        self.sources[record.source_id] = record

    def remove_source(self, source_id: str) -> None:
        self.sources.pop(source_id, None)

    def apply_sync(self, source_id: str, offset: float, drift_ppm: float, evidence: Any) -> None:
        self.mappings[source_id] = (offset, drift_ppm)
        self.sync_evidence[source_id] = evidence

    def capture_workspace(self) -> Any:
        self.captures += 1
        return {
            "mappings": dict(self.mappings),
            "markers": list(self.markers),
            "sources": dict(self.sources),
        }

    def restore_workspace(self, snapshot: Any) -> None:
        self.mappings = dict(snapshot["mappings"])
        self.markers = list(snapshot["markers"])
        self.sources = dict(snapshot["sources"])

    def clear_workspace(self) -> None:
        self.cleared += 1
        self.mappings.clear()
        self.markers.clear()
        self.sources.clear()


@pytest.fixture()
def target() -> FakeTarget:
    return FakeTarget()


def _marker(t: float = 1.0, label: str = "spike", index: int = 0) -> MarkerRecord:
    return MarkerRecord(t_start=t, t_end=None, label=label, index=index)


def _source(source_id: str = "cam1") -> SourceRecord:
    return SourceRecord(source_id=source_id, path=f"/data/{source_id}.mp4", kind="video")


def _all_commands() -> list[Any]:
    """One instance of every command type, for the round-trip sweep."""
    return [
        SetSourceMappingCommand("cam1", before=(0.0, 0.0), after=(1.25, 3.0)),
        AddMarkerCommand(_marker(t=5.0, label="new")),
        RemoveMarkerCommand(_marker()),
        RelabelMarkerCommand(index=0, before="spike", after="burst"),
        SetSourceVisibleCommand("cam1", visible=False),
        SetChannelVisibleCommand("ephys", "ch3", visible=False),
        SetOverlayVisibleCommand("tracking.legend", visible=False),
        AcceptSyncCommand("cam1", before=(0.0, 0.0), after=(0.5, 1.0), evidence={"n": 47}),
        AddSourceCommand(_source("cam9")),
        RemoveSourceCommand(_source()),
        ResetSessionCommand(),
    ]


# ── the protocol boundary ────────────────────────────────────────────
#
# Architecture rule 2 (core/ imports no PySide6) is proved for this module
# by tests/test_headless_core.py, which globs core/*.py and checks both the
# runtime import and the AST. It is not restated here.


def test_fake_target_satisfies_the_protocol(target: FakeTarget) -> None:
    assert isinstance(target, MutationTarget)


# ── round trips ──────────────────────────────────────────────────────


@pytest.mark.parametrize("command", _all_commands(), ids=lambda c: type(c).__name__)
def test_apply_then_revert_restores_state(command: Any, target: FakeTarget) -> None:
    """Every command type round-trips to byte-identical state."""
    # Seed what the *remove* commands act on. The *add* commands must target
    # something disjoint from this seed: FakeTarget.remove_marker filters by
    # equality, so an add whose value already exists would revert by deleting
    # the seeded copy too, and the round trip would fail for the wrong reason.
    target.add_marker(_marker())
    target.add_source(_source())
    target.set_source_mapping("cam1", 0.0, 0.0)
    before = target.capture_workspace()

    doc = Document()
    doc.execute(command, target)
    assert doc.undo(target) is True

    after = target.capture_workspace()
    assert after == before


@pytest.mark.parametrize("command", _all_commands(), ids=lambda c: type(c).__name__)
def test_every_command_has_an_id_and_a_label(command: Any) -> None:
    assert command.command_id
    assert command.label
    assert isinstance(command.label, str)


def test_redo_reapplies(target: FakeTarget) -> None:
    doc = Document()
    doc.execute(SetSourceMappingCommand("cam1", (0.0, 0.0), (2.0, 0.0)), target)
    doc.undo(target)
    assert target.source_mapping("cam1") == (0.0, 0.0)
    assert doc.redo(target) is True
    assert target.source_mapping("cam1") == (2.0, 0.0)


def test_undo_and_redo_on_empty_history_are_noops(target: FakeTarget) -> None:
    doc = Document()
    assert doc.undo(target) is False
    assert doc.redo(target) is False


# ── dirty state ──────────────────────────────────────────────────────


def test_new_document_is_clean() -> None:
    assert Document().is_dirty is False


def test_execute_makes_it_dirty_and_save_makes_it_clean(target: FakeTarget) -> None:
    doc = Document()
    doc.execute(AddMarkerCommand(_marker()), target)
    assert doc.is_dirty is True
    doc.mark_saved()
    assert doc.is_dirty is False


def test_undoing_back_to_the_save_point_is_clean_again(target: FakeTarget) -> None:
    doc = Document()
    doc.mark_saved()
    doc.execute(AddMarkerCommand(_marker()), target)
    assert doc.is_dirty is True
    doc.undo(target)
    assert doc.is_dirty is False


def test_observers_fire_only_on_transitions(target: FakeTarget) -> None:
    doc = Document()
    seen: list[bool] = []
    doc.observe_dirty(seen.append)

    doc.execute(AddMarkerCommand(_marker(1.0)), target)
    doc.execute(AddMarkerCommand(_marker(2.0)), target)
    doc.execute(AddMarkerCommand(_marker(3.0)), target)
    assert seen == [True], "three mutations, one clean->dirty transition"

    doc.mark_saved()
    assert seen == [True, False]


def test_observer_can_be_disposed(target: FakeTarget) -> None:
    doc = Document()
    seen: list[bool] = []
    dispose = doc.observe_dirty(seen.append)
    dispose()
    doc.execute(AddMarkerCommand(_marker()), target)
    assert seen == []


def test_clear_drops_history_and_cleans(target: FakeTarget) -> None:
    doc = Document()
    doc.execute(AddMarkerCommand(_marker()), target)
    doc.clear()
    assert doc.is_dirty is False
    assert doc.can_undo() is False


# ── coalescing (WP-1 step 6) ─────────────────────────────────────────


def test_a_spinbox_drag_is_one_undo_step(target: FakeTarget) -> None:
    """200 valueChanged steps must not become 200 undo entries."""
    doc = Document()
    doc.mark_saved()
    previous = 0.0
    for step in range(200):
        after = (step + 1) * 0.01
        doc.execute(SetSourceMappingCommand("cam1", (previous, 0.0), (after, 0.0)), target)
        previous = after

    assert len(doc) == 1, "a continuous drag is one command"
    assert target.source_mapping("cam1") == pytest.approx((2.0, 0.0))

    doc.undo(target)
    assert target.source_mapping("cam1") == (0.0, 0.0), "undo returns to the drag's start"


def test_a_drag_does_not_merge_across_sources(target: FakeTarget) -> None:
    doc = Document()
    doc.execute(SetSourceMappingCommand("cam1", (0.0, 0.0), (1.0, 0.0)), target)
    doc.execute(SetSourceMappingCommand("cam2", (0.0, 0.0), (1.0, 0.0)), target)
    assert len(doc) == 2


def test_typing_a_label_is_one_undo_step(target: FakeTarget) -> None:
    target.add_marker(_marker(label=""))
    doc = Document()
    for i in range(1, 6):
        doc.execute(RelabelMarkerCommand(0, before="spike"[: i - 1], after="spike"[:i]), target)
    assert len(doc) == 1
    doc.undo(target)
    assert target.markers[0].label == ""


def test_a_drag_does_not_merge_across_a_save_point(target: FakeTarget) -> None:
    """Merging past a save would make the saved state unreachable by undo."""
    doc = Document()
    doc.execute(SetSourceMappingCommand("cam1", (0.0, 0.0), (1.0, 0.0)), target)
    doc.mark_saved()
    doc.execute(SetSourceMappingCommand("cam1", (1.0, 0.0), (2.0, 0.0)), target)
    assert len(doc) == 2
    doc.undo(target)
    assert doc.is_dirty is False


# ── memory bounds (WP-1 step 3) ──────────────────────────────────────


def test_the_log_caps(target: FakeTarget) -> None:
    doc = Document()
    for i in range(MAX_LOG_ENTRIES + 50):
        doc.execute(AddMarkerCommand(_marker(t=float(i))), target)
    assert len(doc) == MAX_LOG_ENTRIES


def test_a_document_whose_save_point_was_evicted_stays_dirty(target: FakeTarget) -> None:
    """Reporting clean after losing the evidence would silently lose work."""
    doc = Document(max_log_entries=5)
    doc.execute(AddMarkerCommand(_marker(0.0)), target)
    doc.mark_saved()
    for i in range(1, 20):
        doc.execute(AddMarkerCommand(_marker(float(i))), target)
    assert doc.is_dirty is True


def test_eviction_releases_the_reset_snapshot(target: FakeTarget) -> None:
    """The one sanctioned bulk snapshot must not outlive its undo entry."""
    doc = Document(max_log_entries=3)
    reset = ResetSessionCommand()
    target.add_source(_source())
    doc.execute(reset, target)
    assert reset.snapshot is not None

    for i in range(5):
        doc.execute(AddMarkerCommand(_marker(float(i))), target)

    assert reset.snapshot is None, "evicted reset must release its workspace"


def test_clear_releases_the_reset_snapshot(target: FakeTarget) -> None:
    doc = Document()
    reset = ResetSessionCommand()
    doc.execute(reset, target)
    assert reset.snapshot is not None
    doc.clear()
    assert reset.snapshot is None


def test_discarded_redo_releases_the_reset_snapshot(target: FakeTarget) -> None:
    doc = Document()
    reset = ResetSessionCommand()
    doc.execute(reset, target)
    doc.undo(target)
    doc.execute(AddMarkerCommand(_marker()), target)  # diverges, discarding redo
    assert reset.snapshot is None


# ── reset session (0.1.6) ────────────────────────────────────────────


def test_reset_session_is_undoable(target: FakeTarget) -> None:
    """One sidebar click clears everything; undo must put it all back."""
    target.add_source(_source("cam1"))
    target.add_source(_source("cam2"))
    target.add_marker(_marker(1.0, "spike"))
    target.add_marker(_marker(2.0, "burst"))
    target.set_source_mapping("cam1", 1.5, 2.0)
    before = target.capture_workspace()

    doc = Document()
    doc.execute(ResetSessionCommand(), target)
    assert target.sources == {}
    assert target.markers == []

    doc.undo(target)
    assert target.capture_workspace() == before


def test_reset_captures_the_workspace_once(target: FakeTarget) -> None:
    """Redoing a reset must not re-capture an already-emptied workspace."""
    target.add_source(_source())
    doc = Document()
    reset = ResetSessionCommand()

    doc.execute(reset, target)
    captured = reset.snapshot
    doc.undo(target)
    doc.redo(target)

    assert reset.snapshot == captured, "the snapshot is the pre-reset state, not the post-reset one"
    doc.undo(target)
    assert target.sources != {}


# ── recovery payload (D-089) ─────────────────────────────────────────


def test_recovery_payload_carries_time_and_path() -> None:
    doc = Document()
    doc.session_path = "/tmp/session.avv"
    payload = doc.recovery_payload({"videos": []})
    assert payload["session_path"] == "/tmp/session.avv"
    assert payload["state"] == {"videos": []}
    assert payload["recovered_at"] > 0


def test_recovery_payload_for_an_untitled_session() -> None:
    payload = Document().recovery_payload({"videos": []})
    assert payload["session_path"] is None
