"""Hand corrections to tracked points: the store, the command, the session (D-099).

The property under test throughout is that a correction is an *overlay*, never
a rewrite: nothing here may write to a pose file or its sidecar cache, and
removing the correction must leave exactly what the model predicted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avialsync.core import point_edit_sidecar as sidecar
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


def test_observers_are_told_which_source_changed() -> None:
    """The writer persists a user's edit and must not echo back what it read.

    A single-point change names its source; a bulk replacement -- adopting a
    sidecar, restoring a session -- reports ``None``, which is how the two are
    told apart.
    """
    store = PointEditStore()
    seen: list[str | None] = []
    dispose = store.observe(seen.append)

    store.set(NOSE, (1.0, 2.0))
    store.load_source(NOSE.source_id, [(120, "nose", 1.0, 2.0)])
    dispose()
    store.set(TAIL, (3.0, 4.0))

    assert seen == [NOSE.source_id, None]
    assert TAIL.source_id not in seen[2:], "the disposed observer must hear nothing"


def test_loading_one_source_leaves_the_others_alone() -> None:
    """Pose files import one at a time; each adopts only its own corrections."""
    store = PointEditStore()
    store.set(NOSE, (1.0, 2.0))
    other = PointKey("/data/side.csv", "paw", 5)
    store.set(other, (7.0, 8.0))

    store.load_source(NOSE.source_id, [(3, "ear", 9.0, 9.0)])

    assert store.get(other) == (7.0, 8.0)
    assert store.get(NOSE) is None
    assert store.get(PointKey(NOSE.source_id, "ear", 3)) == (9.0, 9.0)


def test_one_source_serialises_without_dragging_in_the_rest() -> None:
    store = PointEditStore()
    store.set(NOSE, (1.0, 2.0))
    store.set(PointKey("/data/side.csv", "paw", 5), (7.0, 8.0))

    assert [entry["source"] for entry in store.to_list(NOSE.source_id)] == [NOSE.source_id]
    assert len(store.to_list()) == 2


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


# ── the sidecar, which is where corrections actually live ────────────


def _pose_file(tmp_path: Path) -> Path:
    path = tmp_path / "eks.csv"
    path.write_text("scorer,a,b\nbodyparts,nose,nose\ncoords,x,y\n0,1.0,2.0\n")
    return path


def test_the_sidecar_sits_beside_the_pose_file(tmp_path: Path) -> None:
    """Named off the full file name, so `a.csv` and `a.h5` cannot collide."""
    pose = _pose_file(tmp_path)
    assert sidecar.sidecar_path(pose) == tmp_path / "eks.csv.avialfix.csv"
    assert sidecar.is_correction_path(sidecar.sidecar_path(pose))
    assert not sidecar.is_correction_path(pose)


def test_writing_corrections_never_touches_the_pose_file(tmp_path: Path) -> None:
    """The recording cannot be regenerated; nothing here may write to it."""
    pose = _pose_file(tmp_path)
    before = pose.read_bytes()

    sidecar.write(pose, [sidecar.Correction(frame=120, bodypart="nose", x=12.5, y=34.5)])

    assert pose.read_bytes() == before


def test_a_correction_round_trips_exactly(tmp_path: Path) -> None:
    """A coordinate that changes in the sixth decimal is a coordinate that moved."""
    pose = _pose_file(tmp_path)
    written = [
        sidecar.Correction(frame=120, bodypart="nose", x=12.123456789, y=34.987654321),
        sidecar.Correction(frame=7, bodypart="tail_base", x=0.1 + 0.2, y=-3.5),
    ]

    sidecar.write(pose, written)
    read_back = sidecar.read(pose)

    assert read_back is not None
    assert sorted(read_back.entries, key=lambda e: e.frame) == sorted(
        written, key=lambda e: e.frame
    )


def test_the_sidecar_reads_as_a_csv_with_a_commented_header(tmp_path: Path) -> None:
    """A scientist must be able to check the file without a parser of ours."""
    import polars as pl

    pose = _pose_file(tmp_path)
    path = sidecar.write(pose, [sidecar.Correction(frame=120, bodypart="nose", x=1.0, y=2.0)])

    frame = pl.read_csv(path, comment_prefix="#")

    assert frame.columns == ["frame", "bodypart", "x", "y"]
    assert frame.to_dicts() == [{"frame": 120, "bodypart": "nose", "x": 1.0, "y": 2.0}]
    assert "source: eks.csv" in path.read_text()


def test_removing_the_last_correction_empties_the_file_rather_than_deleting_it(
    tmp_path: Path,
) -> None:
    """Never delete in a data directory. An empty file says the same thing."""
    pose = _pose_file(tmp_path)
    sidecar.write(pose, [sidecar.Correction(frame=1, bodypart="nose", x=1.0, y=2.0)])

    path = sidecar.write(pose, [])

    assert path.exists()
    read_back = sidecar.read(pose)
    assert read_back is not None and read_back.entries == []


def test_a_damaged_row_is_skipped_and_counted(tmp_path: Path) -> None:
    """Law 1: yield what can be read and say how much was lost."""
    pose = _pose_file(tmp_path)
    path = sidecar.sidecar_path(pose)
    path.write_text(
        "# AvialSync tracking corrections\n"
        "frame,bodypart,x,y\n"
        "120,nose,1.0,2.0\n"
        "later,tail,3.0,4.0\n"
        "7,ear,,\n"
    )

    read_back = sidecar.read(pose)

    assert read_back is not None
    assert [entry.bodypart for entry in read_back.entries] == ["nose"]
    assert read_back.skipped == 2


def test_no_sidecar_reads_as_nothing_rather_than_as_empty(tmp_path: Path) -> None:
    """ "Never corrected" and "corrections were cleared" are different facts."""
    assert sidecar.read(_pose_file(tmp_path)) is None


def test_the_sidecar_records_the_size_of_what_it_corrects(tmp_path: Path) -> None:
    """Evidence for the caller's warning, never a gate on loading the work."""
    pose = _pose_file(tmp_path)
    sidecar.write(pose, [sidecar.Correction(frame=1, bodypart="nose", x=1.0, y=2.0)])

    read_back = sidecar.read(pose)

    assert read_back is not None
    assert read_back.source_bytes == pose.stat().st_size


def test_a_corrections_file_is_never_offered_as_an_importable_source(tmp_path: Path) -> None:
    """It is a well-formed CSV, so the generic CSV loader claims it on sight."""
    from avialsync.core.registry import LoaderRegistry

    pose = _pose_file(tmp_path)
    path = sidecar.write(pose, [sidecar.Correction(frame=1, bodypart="nose", x=1.0, y=2.0)])
    registry = LoaderRegistry()

    assert registry.find_best_loader(pose) is not None, "the pose file itself still loads"
    assert registry.find_best_loader(path) is None


# ── the session file ─────────────────────────────────────────────────


def test_session_stored_corrections_survive_a_save_and_load(tmp_path: Path) -> None:
    """The fallback path, for a pose folder that could not be written.

    Corrections normally live in the sidecar and the session carries only a
    count; when the recording sits on read-only media the session carries the
    coordinates instead, and losing them is not one of the options.
    """
    store = PointEditStore()
    store.set(NOSE, (12.0, 34.0))
    store.set(TAIL, (56.0, 78.0))

    path = tmp_path / "session.avv"
    SessionState(
        point_edits=[
            {
                "source": NOSE.source_id,
                "count": 2,
                "storage": "session",
                "edits": store.to_list(NOSE.source_id),
            }
        ]
    ).save(path)
    record = SessionState.load(path).point_edits[0]
    restored = PointEditStore()
    restored.adopt(record["edits"])

    assert record["storage"] == "session"
    assert restored.get(NOSE) == (12.0, 34.0)
    assert restored.get(TAIL) == (56.0, 78.0)


def test_adopting_does_not_discard_what_another_source_already_loaded() -> None:
    """Session fallback entries and freshly-read sidecars arrive interleaved."""
    store = PointEditStore()
    store.set(PointKey("/data/side.csv", "paw", 5), (7.0, 8.0))

    store.adopt([{"source": NOSE.source_id, "point": "nose", "index": 120, "x": 1.0, "y": 2.0}])

    assert store.get(PointKey("/data/side.csv", "paw", 5)) == (7.0, 8.0)
    assert store.get(NOSE) == (1.0, 2.0)


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
            "import sys; import avialsync.core.point_edits, "
            "avialsync.core.point_edit_sidecar; "
            "sys.exit(1 if 'PySide6' in sys.modules else 0)",
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
