"""Identity flips: one transposition, composed in frame order (D-141, D-142).

The property under test throughout is that a flip is a *statement about a span*
rather than an edit to samples: accepting one changes what every consumer reads
from that frame on, accepting its opposite puts it back, and neither ever
rewrites the recording.
"""

from __future__ import annotations

from pathlib import Path

from avialsync.core import identity_sidecar
from avialsync.core.edit_program import build as build_program
from avialsync.core.identity_groups import (
    ANIMALS,
    LEFT,
    RIGHT,
    SIDES,
    groups_for_schema,
    side_of,
)
from avialsync.core.identity_swaps import SwapEvent, SwapStore
from avialsync.core.point_edits import PointEditStore, PointKey
from avialsync.core.pose import PosePoint, PoseSchema

SOURCE = "/data/twomice_DLC.csv"


def _two_mice(parts: tuple[str, ...] = ("snout", "wrist")) -> PoseSchema:
    return PoseSchema(
        points=tuple(
            PosePoint(individual=individual, bodypart=part, axes=("x", "y"), has_likelihood=True)
            for individual in ("testMouse", "conSpecific")
            for part in parts
        ),
        frame_indexed=True,
    )


def _store(schema: PoseSchema | None = None) -> SwapStore:
    store = SwapStore()
    store.set_groups(SOURCE, groups_for_schema(schema if schema is not None else _two_mice()))
    return store


# ── which labels a tracker can confuse ───────────────────────────────


def test_individuals_become_lanes_and_body_parts_become_parts() -> None:
    group = _store().group(SOURCE, ANIMALS)
    assert group is not None
    assert group.lanes == ("testMouse", "conSpecific")
    assert sorted(group.parts) == ["snout", "wrist"]
    assert group.point("testMouse", "snout") == "testMouse_snout"


def test_a_body_part_only_one_animal_carries_is_not_swappable() -> None:
    schema = PoseSchema(
        points=(
            PosePoint("testMouse", "snout", ("x", "y")),
            PosePoint("testMouse", "implant", ("x", "y")),
            PosePoint("conSpecific", "snout", ("x", "y")),
        )
    )
    group = _store(schema).group(SOURCE, ANIMALS)
    assert group is not None
    assert group.parts == ("snout",)
    assert group.point("testMouse", "implant") is None


def test_left_and_right_are_lanes_without_any_individual() -> None:
    schema = PoseSchema(
        points=(
            PosePoint("", "leftwrist", ("x", "y")),
            PosePoint("", "rightwrist", ("x", "y")),
            PosePoint("", "snout", ("x", "y")),
        )
    )
    groups = groups_for_schema(schema)
    assert [group.name for group in groups] == [SIDES]
    assert groups[0].lanes == (LEFT, RIGHT)
    assert groups[0].parts == ("wrist",)
    assert groups[0].point(LEFT, "wrist") == "leftwrist"


def test_a_multi_animal_file_gets_one_sides_group_per_individual() -> None:
    schema = PoseSchema(
        points=tuple(
            PosePoint(individual, part, ("x", "y"))
            for individual in ("testMouse", "conSpecific")
            for part in ("left_paw", "right_paw")
        )
    )
    names = [group.name for group in groups_for_schema(schema)]
    assert f"{SIDES}:testMouse" in names
    assert f"{SIDES}:conSpecific" in names


def test_a_word_that_merely_starts_with_r_names_no_side() -> None:
    # 'rear' is not a right 'ear'. A glued single letter would invent a side
    # that is not in the data, so only whole tokens and left/right are read.
    assert side_of("rear") is None
    assert side_of("r_ear") == (RIGHT, "ear")
    assert side_of("ear_L") == (LEFT, "ear")
    assert side_of("snout") is None


def test_a_group_with_one_lane_is_not_offered() -> None:
    single = PoseSchema(points=(PosePoint("", "snout", ("x", "y")),))
    assert groups_for_schema(single) == ()


# ── the identity in force ────────────────────────────────────────────


def test_nothing_is_routed_before_the_first_flip() -> None:
    store = _store()
    store.add(SOURCE, SwapEvent(index=100, group=ANIMALS, lanes=("testMouse", "conSpecific")))
    assert store.point_sources(SOURCE, 99) == {}


def test_a_flip_holds_from_its_frame_to_the_end() -> None:
    store = _store()
    store.add(SOURCE, SwapEvent(index=100, group=ANIMALS, lanes=("testMouse", "conSpecific")))
    for index in (100, 10_000):
        assert store.point_sources(SOURCE, index) == {
            "testMouse_snout": "conSpecific_snout",
            "conSpecific_snout": "testMouse_snout",
            "testMouse_wrist": "conSpecific_wrist",
            "conSpecific_wrist": "testMouse_wrist",
        }


def test_a_second_flip_puts_the_identities_back() -> None:
    store = _store()
    store.add(SOURCE, SwapEvent(index=100, group=ANIMALS, lanes=("testMouse", "conSpecific")))
    store.add(SOURCE, SwapEvent(index=200, group=ANIMALS, lanes=("conSpecific", "testMouse")))
    assert store.point_sources(SOURCE, 150) != {}
    assert store.point_sources(SOURCE, 200) == {}


def test_one_part_can_flip_without_moving_the_animal() -> None:
    store = _store()
    store.add(
        SOURCE,
        SwapEvent(index=100, group=ANIMALS, lanes=("testMouse", "conSpecific"), parts=("wrist",)),
    )
    assert store.point_sources(SOURCE, 100) == {
        "testMouse_wrist": "conSpecific_wrist",
        "conSpecific_wrist": "testMouse_wrist",
    }


def test_a_drag_in_either_direction_records_the_same_flip() -> None:
    store = _store()
    assert store.add(SOURCE, SwapEvent(100, ANIMALS, ("testMouse", "conSpecific")))
    assert not store.add(SOURCE, SwapEvent(100, ANIMALS, ("conSpecific", "testMouse")))
    assert store.count_for(SOURCE) == 1


def test_undoing_a_flip_leaves_the_others_in_force() -> None:
    store = _store()
    first = SwapEvent(100, ANIMALS, ("testMouse", "conSpecific"))
    second = SwapEvent(400, ANIMALS, ("testMouse", "conSpecific"))
    store.add(SOURCE, first)
    store.add(SOURCE, second)
    assert store.remove(SOURCE, second)
    assert store.point_sources(SOURCE, 500) != {}


def test_a_relinked_file_keeps_its_flips() -> None:
    store = _store()
    store.add(SOURCE, SwapEvent(100, ANIMALS, ("testMouse", "conSpecific")))
    store.remap_source(SOURCE, "/moved/twomice_DLC.csv")
    assert store.count_for(SOURCE) == 0
    assert store.count_for("/moved/twomice_DLC.csv") == 1
    assert store.point_sources("/moved/twomice_DLC.csv", 100) != {}


def test_observers_are_told_which_source_changed() -> None:
    store = _store()
    seen: list[str | None] = []
    store.observe(seen.append)
    store.add(SOURCE, SwapEvent(100, ANIMALS, ("testMouse", "conSpecific")))
    store.load_source(SOURCE, [])
    assert seen == [SOURCE, None]


# ── the sidecar ──────────────────────────────────────────────────────


def test_a_sidecar_round_trips_its_events_and_its_groups(tmp_path: Path) -> None:
    pose = tmp_path / "twomice_DLC.csv"
    pose.write_text("scorer,DLC\n", encoding="utf-8")
    group = groups_for_schema(_two_mice())[0]
    events = [
        SwapEvent(6810, ANIMALS, ("testMouse", "conSpecific")),
        SwapEvent(9000, ANIMALS, ("testMouse", "conSpecific"), parts=("wrist",)),
    ]

    identity_sidecar.write(pose, events, [group])
    held = identity_sidecar.read(pose)

    assert held is not None
    assert held.events == events
    assert held.groups[0].point("conSpecific", "wrist") == "conSpecific_wrist"
    assert held.source_bytes == pose.stat().st_size
    assert held.skipped == 0


def test_the_recording_is_not_touched_by_writing_a_sidecar(tmp_path: Path) -> None:
    pose = tmp_path / "twomice_DLC.csv"
    pose.write_text("scorer,DLC\nbodyparts,snout\n", encoding="utf-8")
    before = pose.read_bytes()
    identity_sidecar.write(pose, [SwapEvent(10, ANIMALS, ("a", "b"))], [])
    assert pose.read_bytes() == before


def test_the_last_flip_undone_leaves_a_file_that_says_so(tmp_path: Path) -> None:
    pose = tmp_path / "pose.csv"
    pose.write_text("scorer,DLC\n", encoding="utf-8")
    path = identity_sidecar.write(pose, [], [])
    assert path.exists()
    held = identity_sidecar.read(pose)
    assert held is not None and held.events == []


def test_a_damaged_row_is_counted_rather_than_raised(tmp_path: Path) -> None:
    pose = tmp_path / "pose.csv"
    pose.write_text("scorer,DLC\n", encoding="utf-8")
    identity_sidecar.sidecar_path(pose).write_text(
        "frame,group,lane_a,lane_b,parts\n"
        "100,animals,testMouse,conSpecific,*\n"
        "notaframe,animals,testMouse,conSpecific,*\n",
        encoding="utf-8",
    )
    held = identity_sidecar.read(pose)
    assert held is not None
    assert len(held.events) == 1
    assert held.skipped == 1


def test_our_own_sidecar_is_recognisable(tmp_path: Path) -> None:
    assert identity_sidecar.is_swap_path(identity_sidecar.sidecar_path("pose.csv"))
    assert not identity_sidecar.is_swap_path("pose.csv")


# ── the program both renderers read ──────────────────────────────────


def test_the_program_routes_a_point_from_the_flip_to_the_end() -> None:
    store = _store()
    store.add(SOURCE, SwapEvent(100, ANIMALS, ("testMouse", "conSpecific")))
    program = build_program(SOURCE, store, PointEditStore())

    assert program.source_of("testMouse_snout", 99) == "testMouse_snout"
    assert program.source_of("testMouse_snout", 100) == "conSpecific_snout"
    segments = program.segments_for("testMouse_snout")
    assert (segments[0].start, segments[0].stop) == (100, -1)


def test_two_flips_leave_one_bounded_segment_and_nothing_after() -> None:
    store = _store()
    store.add(SOURCE, SwapEvent(100, ANIMALS, ("testMouse", "conSpecific")))
    store.add(SOURCE, SwapEvent(200, ANIMALS, ("testMouse", "conSpecific")))
    program = build_program(SOURCE, store, PointEditStore())

    segments = program.segments_for("testMouse_snout")
    assert [(s.start, s.stop, s.source) for s in segments] == [(100, 200, "conSpecific_snout")]


def test_only_the_points_a_change_reaches_are_affected() -> None:
    store = _store()
    store.add(
        SOURCE,
        SwapEvent(100, ANIMALS, ("testMouse", "conSpecific"), parts=("wrist",)),
    )
    edits = PointEditStore()
    edits.set(PointKey(SOURCE, "testMouse_snout", 12), (4.0, 5.0))
    program = build_program(SOURCE, store, edits)

    assert set(program.affected(p.name for p in _two_mice().points)) == {
        "testMouse_wrist",
        "conSpecific_wrist",
        "testMouse_snout",
    }


def test_the_same_edits_made_in_either_order_name_one_generation() -> None:
    first, second = _store(), _store()
    a = SwapEvent(100, ANIMALS, ("testMouse", "conSpecific"))
    b = SwapEvent(300, ANIMALS, ("testMouse", "conSpecific"), parts=("wrist",))
    first.add(SOURCE, a)
    first.add(SOURCE, b)
    second.add(SOURCE, b)
    second.add(SOURCE, a)

    edits = PointEditStore()
    edits.set(PointKey(SOURCE, "testMouse_snout", 12), (4.0, 5.0))
    assert (
        build_program(SOURCE, first, edits).fingerprint
        == build_program(SOURCE, second, edits).fingerprint
    )


def test_an_unedited_source_has_an_empty_program() -> None:
    assert not build_program(SOURCE, _store(), PointEditStore())
