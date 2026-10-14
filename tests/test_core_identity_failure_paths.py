"""Missing tracking evidence, history eviction and sparse routing preserve identity."""

import numpy as np

from avialsync.core import identity_detect, identity_groups
from avialsync.core.commands import (
    AddMarkerCommand,
    RelabelMarkerCommand,
    SetImagingLayoutCommand,
    SetVideoLevelsCommand,
)
from avialsync.core.document import Document
from avialsync.core.edit_program import EditProgram
from avialsync.core.identity_detect import Candidate, Trajectory
from avialsync.core.pose import PoseSchema
from tests.test_document import FakeTarget, _marker


def test_missing_short_and_stationary_trajectories_do_not_propose_swaps() -> None:
    assert len(identity_detect.centroid([]).x) == 0
    for values in ([], [1, 2], [np.nan] * 4, [0] * 4):
        lane = Trajectory(np.asarray(values), np.asarray(values))
        assert identity_detect.detect({"a": lane, "b": lane}) == ()
    empty = Trajectory(np.array([]), np.array([]))
    assert np.isnan(identity_detect._median_step(empty, empty, np.array([], dtype=bool)))
    invalid = Trajectory(np.array([0.0, np.inf]), np.zeros(2))
    assert np.isnan(identity_detect._median_step(invalid, invalid, np.ones(2, dtype=bool)))
    assert identity_detect._proximity_limit(np.array([np.inf]), 2, 4) == 8
    assert identity_detect._closest_approach(np.ones(2), 10, 1) == np.inf


def test_candidate_serialization_and_zero_window_preserve_all_evidence() -> None:
    first = Candidate(10, ("a", "b"), 2, 0.1, 3)
    second = Candidate(11, ("a", "b"), 1, 0.2, 0)
    assert first.as_dict() == {
        "index": 10,
        "lanes": ["a", "b"],
        "separation": 2,
        "cost_ratio": 0.1,
        "gap": 3,
    }
    assert identity_detect._suppress([first, second], 0) == [first, second]
    assert identity_detect._suppress([first, second], 2) == [first]
    assert identity_groups.side_of(" ") is None
    assert identity_groups.side_of("wristleft") == ("left", "wrist")
    assert PoseSchema.from_channels(["head_likelihood"]).points == ()


def test_contiguous_routing_spans_coalesce_and_expose_point_corrections() -> None:
    program = EditProgram("source", (2, 4), ({"a": "b"}, {"a": "b"}), {("a", 3): (1, 2)}, "fixture")
    spans = program.segments_for("a")
    assert len(spans) == 1 and spans[0].start == 2
    assert program.correction("a", 3) == (1, 2)
    assert program.segments_for("untouched") == ()


def test_document_public_state_and_idempotent_observer_disposal() -> None:
    document = Document()
    document.session_path = "session.avv"
    assert document.session_path == "session.avv" and document.last_change_time == 0
    log, dirty = [], []
    dispose_log = document.observe_log(lambda: log.append(True))
    dispose_dirty = document.observe_dirty(dirty.append)
    document.mark_dirty()
    assert log and dirty == [True]
    dispose_log()
    dispose_log()
    dispose_dirty()
    dispose_dirty()
    document.mark_saved()
    assert dirty == [True]


def test_unrelated_commands_do_not_merge_and_imaging_identity_is_named() -> None:
    levels = SetVideoLevelsCommand("source", {}, {}, "gamma")
    assert levels.merge_with(object()) is None
    label = RelabelMarkerCommand(0, "old", "new")
    assert label.merge_with(object()) is None
    assert "source" in SetImagingLayoutCommand("source", {}, {}).label


def test_undoing_retained_history_cannot_recover_an_evicted_save_point() -> None:
    document = Document(max_log_entries=2)
    target = FakeTarget()
    for index in range(3):
        document.execute(AddMarkerCommand(_marker(float(index))), target)
    while document.can_undo():
        document.undo(target)
    assert target.markers and document.is_dirty
    document.mark_saved()
    assert not document.is_dirty
