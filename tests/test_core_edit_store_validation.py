"""Correction and identity stores keep source isolation, bulk-load semantics and disposal."""

from __future__ import annotations

import pytest

from avialsync.core.identity_swaps import SwapEvent, SwapGroup, SwapStore
from avialsync.core.point_edits import PointEditStore, PointKey

GROUP = SwapGroup(
    "animals",
    ("a", "b"),
    ("head", "tail"),
    (("a", "head", "a_head"), ("b", "head", "b_head"), ("b", "tail", "b_tail")),
)
EVENT = SwapEvent(2, "animals", ("b", "a"))


def test_group_lookup_preserves_sparse_members_and_order() -> None:
    assert GROUP.locate("a_head") == ("a", "head")
    assert GROUP.locate("unknown") is None
    assert GROUP.parts_of("a") == ("head",)
    assert GROUP.parts_of("b") == ("head", "tail")
    assert GROUP.points() == ("a_head", "b_head", "b_tail")
    assert SwapGroup.from_dict(GROUP.as_dict()) == GROUP
    record = GROUP.as_dict()
    record["members"].append(["too", "short"])
    assert SwapGroup.from_dict(record) == GROUP


@pytest.mark.parametrize("lanes", [("a",), ("a", "a"), ("a", "b", "c")])
def test_malformed_swaps_never_enter_a_store(lanes: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        SwapEvent(0, "animals", lanes)
    with pytest.raises(ValueError):
        SwapEvent.from_dict({"index": 0, "lanes": lanes})


def test_swap_roundtrip_and_group_removal_protect_accepted_events() -> None:
    assert SwapEvent.from_dict(EVENT.as_dict()) == EVENT
    store = SwapStore()
    assert store.add_group("old", GROUP)
    assert not store.add_group("old", GROUP)
    assert not store.add_group("old", SwapGroup("empty", (), (), ()))
    assert not store.remove_group("old", "unknown")
    assert store.remove_group("old", GROUP.name)
    store.add_group("old", GROUP)
    store.add("old", EVENT)
    assert len(store) == 1
    assert not store.remove_group("old", GROUP.name)
    assert not store.remove("old", SwapEvent(99, "animals", ("a", "b")))
    store.remap_source("old", "new")
    assert store.group("new", "animals") == GROUP
    assert store.events_for("new") == (EVENT,)
    store.remap_source("new", "new")
    store.remap_source("missing", "new")
    assert store.clear_source("new")
    assert not store.clear_source("new")
    store.load_source("new", [EVENT])
    store.load_source("new", [])
    assert store.count_for("new") == 0


def test_swap_load_skips_damaged_records_and_deduplicates_valid_events() -> None:
    store = SwapStore()
    record = {"source": "source", **EVENT.as_dict()}
    store.load([{}, {"source": "bad", "index": "bad"}, record, record])
    assert store.events_for("source") == (EVENT,)
    assert store.source_ids() == {"source"}
    store.adopt([record])
    assert len(store) == 1
    store.load(None)
    assert len(store) == 0


def test_swap_disposer_can_be_called_twice_without_later_notifications() -> None:
    store = SwapStore()
    seen: list = []
    dispose = store.observe(seen.append)
    dispose()
    dispose()
    store.add("source", EVENT)
    assert seen == []


def test_point_removal_bulk_clear_and_relink_preserve_other_sources() -> None:
    store = PointEditStore()
    first = PointKey("old", "point", 2)
    second = PointKey("other", "point", 3)
    assert not store.set(first, None)
    store.set(first, (1.0, 2.0), shown_as="display_name")
    store.set(second, (3.0, 4.0))
    assert len(list(store)) == 2
    store.remap_source("old", "old")
    store.remap_source("missing", "new")
    store.remap_source("old", "new")
    assert store.shown_as(PointKey("new", "point", 2)) == "display_name"
    assert not store.clear_source("absent")
    assert store.clear_source("new")
    assert store.get(second) == (3.0, 4.0)
    store.clear()
    store.clear()
    assert len(list(store)) == 0


def test_point_bulk_reload_removes_old_display_alias_without_echoing_single_edits() -> None:
    store = PointEditStore()
    key = PointKey("source", "point", 2)
    store.set(key, (1.0, 2.0), shown_as="old_label")
    seen: list = []
    dispose = store.observe(seen.append)
    store.load_source("source", [(2, "point", 4.0, 5.0, "new_label")])
    assert store.get(key) == (4.0, 5.0) and store.shown_as(key) == "new_label"
    assert seen == [None]
    dispose()
    dispose()
