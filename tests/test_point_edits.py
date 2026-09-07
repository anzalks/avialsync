"""Hand corrections to tracked points: the store, the command, the session (D-099).

The property under test throughout is that a correction is an *overlay*, never
a rewrite: nothing here may write to a pose file or its sidecar cache, and
removing the correction must leave exactly what the model predicted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avialsync.core.commands import SetTrackedPointCommand
from avialsync.core.document import Document
from avialsync.core.point_edits import PointEditStore, PointKey, PointMove
from avialsync.core.session import SessionState

NOSE = PointKey("/data/eks.csv", "nose", 120)
TAIL = PointKey("/data/eks.csv", "tail", 120)


class _StoreTarget:
    """The slice of :class:`MutationTarget` a point command actually uses."""

    def __init__(self, store: PointEditStore) -> None:
        self.store = store

    def set_tracked_point(
        self, source_id: str, point: str, index: int, position: tuple[float, float] | None
    ) -> None:
        self.store.set(PointKey(source_id, point, index), position)


# ── the store ────────────────────────────────────────────────────────


def test_a_correction_touches_one_frame_of_one_point() -> None:
    """Sparse is the semantics, not an optimisation.

    A user correcting a dropped detection annotates a handful of frames out of
    a hundred thousand; every frame they did not touch must keep saying what
    the model said.
    """
    store = PointEditStore()
    store.set(NOSE, (12.0, 34.0))

    assert store.get(NOSE) == (12.0, 34.0)
    assert store.get(TAIL) is None
    assert store.get(PointKey(NOSE.source_id, "nose", 121)) is None
    assert len(store) == 1


def test_writing_the_same_position_reports_no_change() -> None:
    """A click that puts a point back where it was must not push an undo step."""
    store = PointEditStore()
    assert store.set(NOSE, (12.0, 34.0)) is True
    assert store.set(NOSE, (12.0, 34.0)) is False


def test_clearing_a_correction_is_not_writing_a_coordinate_back() -> None:
    """Undoing the first correction restores the prediction, not a pinned copy."""
    store = PointEditStore()
    store.set(NOSE, (12.0, 34.0))
    store.set(NOSE, None)

    assert store.get(NOSE) is None
    assert NOSE not in store
    assert len(store) == 0


def test_observers_hear_every_change() -> None:
    store = PointEditStore()
    seen: list[int] = []
    dispose = store.observe(lambda: seen.append(len(store)))

    store.set(NOSE, (1.0, 2.0))
    store.set(NOSE, None)
    dispose()
    store.set(TAIL, (3.0, 4.0))

    assert seen == [1, 0], "the disposed observer must not hear the third change"


def test_a_relinked_pose_file_carries_its_corrections() -> None:
    """A session whose CSV moved must not open with every correction orphaned."""
    store = PointEditStore()
    store.set(NOSE, (12.0, 34.0))

    store.remap_source("/data/eks.csv", "/archive/eks.csv")

    assert store.get(NOSE) is None
    assert store.get(PointKey("/archive/eks.csv", "nose", 120)) == (12.0, 34.0)
    assert store.count_for("/archive/eks.csv") == 1


# ── the command ──────────────────────────────────────────────────────


def test_undoing_the_first_correction_restores_the_prediction() -> None:
    store = PointEditStore()
    target = _StoreTarget(store)
    document = Document()

    document.execute(
        SetTrackedPointCommand(
            source_id=NOSE.source_id,
            point=NOSE.point,
            index=NOSE.index,
            before=None,
            after=(12.0, 34.0),
        ),
        target,
    )
    assert store.get(NOSE) == (12.0, 34.0)

    document.undo(target)
    assert store.get(NOSE) is None, "undo must remove the override, not pin the old value"

    document.redo(target)
    assert store.get(NOSE) == (12.0, 34.0)


def test_undoing_a_second_correction_returns_to_the_first() -> None:
    """Corrections do not coalesce: each drag is a separate judgement."""
    store = PointEditStore()
    target = _StoreTarget(store)
    document = Document()

    for before, after in (((None), (10.0, 10.0)), ((10.0, 10.0), (20.0, 20.0))):
        document.execute(
            SetTrackedPointCommand(
                source_id=NOSE.source_id,
                point=NOSE.point,
                index=NOSE.index,
                before=before,
                after=after,
            ),
            target,
        )

    assert len(document) == 2
    document.undo(target)
    assert store.get(NOSE) == (10.0, 10.0)


def test_a_correction_makes_the_document_dirty() -> None:
    store = PointEditStore()
    document = Document()
    assert document.is_dirty is False

    document.execute(
        SetTrackedPointCommand(
            source_id=NOSE.source_id, point="nose", index=7, before=None, after=(1.0, 2.0)
        ),
        _StoreTarget(store),
    )

    assert document.is_dirty is True


def test_the_command_reads_as_prose() -> None:
    """Labels appear verbatim in the Edit menu, so they are written for a reader."""
    moved = SetTrackedPointCommand(
        source_id="/data/eks.csv", point="nose", index=120, before=None, after=(12.4, 34.6)
    )
    restored = SetTrackedPointCommand(
        source_id="/data/eks.csv", point="nose", index=120, before=(12.4, 34.6), after=None
    )

    assert moved.label == "Move nose to (12.4, 34.6) px at frame 120"
    assert restored.label == "Restore predicted nose at frame 120"


# ── the payload the canvas emits ─────────────────────────────────────


def test_a_move_carries_what_it_takes_to_reverse_it() -> None:
    move = PointMove(key=NOSE, before=(1.0, 2.0), after=(3.0, 4.0))
    assert move.before == (1.0, 2.0)
    assert move.after == (3.0, 4.0)


# ── the session file ─────────────────────────────────────────────────


def test_corrections_survive_a_save_and_load(tmp_path: Path) -> None:
    """Without this the dirty flag would promise work the save silently drops."""
    store = PointEditStore()
    store.set(NOSE, (12.0, 34.0))
    store.set(TAIL, (56.0, 78.0))

    path = tmp_path / "session.avv"
    SessionState(point_edits=store.to_list()).save(path)
    restored = PointEditStore()
    restored.load(SessionState.load(path).point_edits)

    assert restored.get(NOSE) == (12.0, 34.0)
    assert restored.get(TAIL) == (56.0, 78.0)
    assert len(restored) == 2


def test_the_saved_file_writes_version_8(tmp_path: Path) -> None:
    path = tmp_path / "session.avv"
    SessionState().save(path)
    assert json.loads(path.read_text())["version"] == 8


def test_a_version_7_session_loads_with_no_corrections(tmp_path: Path) -> None:
    """The migration test is an equivalence, not an aspiration."""
    path = tmp_path / "old.avv"
    path.write_text(json.dumps({"version": 7, "videos": [], "sensors": [], "markers": []}))

    state = SessionState.load(path)

    assert state.point_edits == []


def test_a_malformed_correction_is_skipped_rather_than_refusing_the_session() -> None:
    """Law 1: a damaged file loads as far as it can rather than blocking."""
    store = PointEditStore()
    store.load(
        [
            {"source": "/data/eks.csv", "point": "nose", "index": 120, "x": 1.0, "y": 2.0},
            {"source": "/data/eks.csv", "point": "tail"},  # no index or coordinates
            {"source": "/data/eks.csv", "point": "ear", "index": "later", "x": 1.0, "y": 2.0},
        ]
    )

    assert len(store) == 1
    assert store.get(NOSE) == (1.0, 2.0)


def test_saving_is_ordered_so_a_session_file_does_not_churn() -> None:
    first = PointEditStore()
    first.set(TAIL, (1.0, 1.0))
    first.set(NOSE, (2.0, 2.0))
    second = PointEditStore()
    second.set(NOSE, (2.0, 2.0))
    second.set(TAIL, (1.0, 1.0))

    assert first.to_list() == second.to_list()


# ── the boundary core/ must not cross ────────────────────────────────


def test_the_store_needs_no_qt() -> None:
    """``core/`` is headless (architecture rule 2); the store is part of it."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import avialsync.core.point_edits; "
            "sys.exit(1 if 'PySide6' in sys.modules else 0)",
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
