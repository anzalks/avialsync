"""Identity flips in tracking data: what exchanged places, and from when.

A pose estimator loses track of *which* is which.  Two mice cross, and from
that frame on ``testMouse_snout`` follows the other animal; a left and a right
wrist exchange labels behind an occlusion and stay exchanged.  Neither is a
wrong coordinate -- every point is exactly where the model saw something -- so
:mod:`avialsync.core.point_edits` cannot express it.  A correction says "the
nose was really *here*"; this says "these two have been each other since frame
6 810", which is one fact about forty thousand frames.

**A flip is a transposition, and it holds until another one.**  An event names
two lanes and a frame; the identity in force at frame *f* is every event up to
*f* composed in order.  A second flip that puts them back is therefore just
another event, and nothing is ever rewritten or removed to express it.

**A lane is not an animal.**  It is whichever labels are confusable: the
individuals of a multi-animal export, or left against right within one animal.
:class:`SwapGroup` is what ties a lane and a part to the point they name, so
the same model serves both and neither is a special case (D-141).

**The recording is never touched.**  Events live in a sidecar beside the pose
file (:mod:`avialsync.core.identity_sidecar`), the edited data is a derived
cache generation, and the exported copy is a new file.  Deleting the sidecar
restores the model's own output exactly.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any

__all__ = [
    "SwapGroup",
    "SwapEvent",
    "SwapStore",
    "ALL_PARTS",
]

#: An event's ``parts`` when it moves every part of its group at once -- the
#: whole-animal flip, which is one gesture and must stay one event rather than
#: ten that can drift apart.
ALL_PARTS: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class SwapGroup:
    """A set of confusable lanes, and the points each one owns.

    ``members`` is the only place a ``(lane, part)`` becomes a point name, so a
    group can describe two individuals sharing body-part names, two sides of one
    animal, or anything a future format calls interchangeable, without any
    consumer learning a naming convention.
    """

    name: str
    #: Display order, which is also the order lanes are drawn in.
    lanes: tuple[str, ...]
    parts: tuple[str, ...]
    #: ``(lane, part, point)`` triples.  Sparse by design: a body part only one
    #: animal has produces no member, and therefore cannot be swapped.
    members: tuple[tuple[str, str, str], ...]

    _by_lane_part: dict[tuple[str, str], str] = dataclasses.field(
        init=False, compare=False, repr=False, default_factory=dict
    )
    _by_point: dict[str, tuple[str, str]] = dataclasses.field(
        init=False, compare=False, repr=False, default_factory=dict
    )

    def __post_init__(self) -> None:
        by_lane_part = {(lane, part): point for lane, part, point in self.members}
        by_point = {point: (lane, part) for lane, part, point in self.members}
        object.__setattr__(self, "_by_lane_part", by_lane_part)
        object.__setattr__(self, "_by_point", by_point)

    def __bool__(self) -> bool:
        """A group with fewer than two lanes has nothing to exchange."""
        return len(self.lanes) >= 2 and bool(self.members)

    def point(self, lane: str, part: str) -> str | None:
        """The point *lane* owns for *part*, or ``None`` when it has none."""
        return self._by_lane_part.get((lane, part))

    def locate(self, point: str) -> tuple[str, str] | None:
        """The ``(lane, part)`` *point* belongs to, or ``None``."""
        return self._by_point.get(point)

    def parts_of(self, lane: str) -> tuple[str, ...]:
        """Every part *lane* actually carries, in group order."""
        return tuple(part for part in self.parts if (lane, part) in self._by_lane_part)

    def points(self) -> tuple[str, ...]:
        """Every point in the group, in member order."""
        return tuple(point for _, _, point in self.members)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "lanes": list(self.lanes),
            "parts": list(self.parts),
            "members": [list(member) for member in self.members],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SwapGroup:
        members = tuple(
            (str(entry[0]), str(entry[1]), str(entry[2]))
            for entry in data.get("members", ())
            if len(entry) >= 3
        )
        return cls(
            name=str(data.get("name", "")),
            lanes=tuple(str(lane) for lane in data.get("lanes", ())),
            parts=tuple(str(part) for part in data.get("parts", ())),
            members=members,
        )


@dataclasses.dataclass(frozen=True, order=True)
class SwapEvent:
    """One accepted flip: two lanes exchanging from *index* onward.

    ``index`` is the sample index within the pose source, for the same reason
    :class:`~avialsync.core.point_edits.PointKey` uses one: an offset or an
    accepted ``TimeMap`` changes *when* a sample is shown without changing
    which sample it is, and an accepted flip must survive that.

    ``lanes`` is stored sorted, because a transposition has no direction --
    dragging A onto B and B onto A are the same fact, and storing the gesture's
    order would let the same flip be recorded twice.
    """

    index: int
    group: str
    lanes: tuple[str, str]
    #: The parts this event moves, or :data:`ALL_PARTS` for every part in the
    #: group.  Stored sorted so two identical events compare equal.
    parts: tuple[str, ...] = ALL_PARTS

    def __post_init__(self) -> None:
        object.__setattr__(self, "lanes", tuple(sorted(self.lanes)))
        object.__setattr__(self, "parts", tuple(sorted(self.parts)))
        if len(self.lanes) != 2 or self.lanes[0] == self.lanes[1]:
            raise ValueError("a swap exchanges two distinct lanes")

    def moves(self, part: str) -> bool:
        """Whether this event moves *part*."""
        return not self.parts or part in self.parts

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "group": self.group,
            "lanes": list(self.lanes),
            "parts": list(self.parts),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SwapEvent:
        lanes = tuple(str(lane) for lane in data.get("lanes", ()))
        if len(lanes) != 2:
            raise ValueError("a swap exchanges two lanes")
        return cls(
            index=int(data["index"]),
            group=str(data.get("group", "")),
            lanes=(lanes[0], lanes[1]),
            parts=tuple(str(part) for part in data.get("parts", ())),
        )


class SwapStore:
    """Every accepted flip in the session, and the groups they are stated in.

    Observers are plain callables so ``core/`` stays importable without PySide6
    (architecture rule 2).  They fire after a change, with the source that
    changed or ``None`` for a bulk replacement -- the same contract as
    :class:`~avialsync.core.point_edits.PointEditStore`, and load-bearing for
    the same reason: the writer must not persist what it has just read.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[SwapEvent]] = {}
        self._groups: dict[str, tuple[SwapGroup, ...]] = {}
        self._observers: list[Callable[[str | None], None]] = []

    # ── groups ───────────────────────────────────────────────────────

    def set_groups(self, source_id: str, groups: Iterable[SwapGroup]) -> None:
        """Declare which lanes *source_id* has.  Does not notify: no edit happened."""
        self._groups[source_id] = tuple(group for group in groups if group)

    def adopt_groups(self, source_id: str, groups: Iterable[SwapGroup]) -> None:
        """Merge in group definitions a sidecar carried, keeping what is known.

        A sidecar states the groups its own events are written in, so an event
        stays interpretable even if the file it names is later imported by a
        loader that derives different groups.
        """
        known = {group.name: group for group in self._groups.get(source_id, ())}
        for group in groups:
            known.setdefault(group.name, group)
        self._groups[source_id] = tuple(known.values())

    def groups_for(self, source_id: str) -> tuple[SwapGroup, ...]:
        """Every group declared for one pose source, in declaration order."""
        return self._groups.get(source_id, ())

    def group(self, source_id: str, name: str) -> SwapGroup | None:
        return next((g for g in self.groups_for(source_id) if g.name == name), None)

    # ── reading ──────────────────────────────────────────────────────

    def events_for(self, source_id: str) -> tuple[SwapEvent, ...]:
        """Every accepted flip on one source, in frame order."""
        return tuple(self._events.get(source_id, ()))

    def count_for(self, source_id: str) -> int:
        return len(self._events.get(source_id, ()))

    def __len__(self) -> int:
        return sum(len(events) for events in self._events.values())

    def source_ids(self) -> set[str]:
        """Every pose source that currently has at least one accepted flip."""
        return {source for source, events in self._events.items() if events}

    def __iter__(self) -> Iterator[tuple[str, SwapEvent]]:
        for source, events in self._events.items():
            for event in events:
                yield source, event

    # ── writing ──────────────────────────────────────────────────────

    def add(self, source_id: str, event: SwapEvent) -> bool:
        """Accept *event*, or return False when it is already recorded."""
        events = self._events.setdefault(source_id, [])
        if event in events:
            return False
        events.append(event)
        events.sort()
        self._notify(source_id)
        return True

    def remove(self, source_id: str, event: SwapEvent) -> bool:
        """Undo one accepted flip, leaving every other one in force."""
        events = self._events.get(source_id)
        if not events or event not in events:
            return False
        events.remove(event)
        if not events:
            del self._events[source_id]
        self._notify(source_id)
        return True

    def clear(self) -> None:
        """Drop every flip.  Used when the workspace is reset."""
        if not self._events:
            return
        self._events.clear()
        self._notify(None)

    def clear_source(self, source_id: str) -> bool:
        if source_id not in self._events:
            return False
        del self._events[source_id]
        self._notify(None)
        return True

    def load_source(self, source_id: str, events: Sequence[SwapEvent]) -> None:
        """Replace one source's flips, leaving every other source alone.

        The read path -- adopting a sidecar -- so it notifies as a bulk change
        and the writer does not echo it straight back to disk.
        """
        ordered = sorted(set(events))
        if ordered:
            self._events[source_id] = ordered
        else:
            self._events.pop(source_id, None)
        self._notify(None)

    def remap_source(self, old_id: str, new_id: str) -> None:
        """Follow a relinked pose file to its new path."""
        if old_id == new_id or old_id not in self._events:
            return
        self._events[new_id] = self._events.pop(old_id)
        if old_id in self._groups:
            self._groups[new_id] = self._groups.pop(old_id)
        self._notify(None)

    # ── observation ──────────────────────────────────────────────────

    def observe(self, callback: Callable[[str | None], None]) -> Callable[[], None]:
        """Register *callback*, called with the changed source after any change."""
        self._observers.append(callback)

        def _dispose() -> None:
            if callback in self._observers:
                self._observers.remove(callback)

        return _dispose

    def _notify(self, source_id: str | None) -> None:
        for callback in list(self._observers):
            callback(source_id)

    # ── the identity in force ────────────────────────────────────────

    def lane_map(self, source_id: str, group: str, part: str, index: int) -> dict[str, str]:
        """Which lane's data each lane *displays* at *index*, for one part.

        Identity for a group nothing has flipped.  The composition runs in
        frame order because transpositions do not commute: A↔B then B↔C is not
        B↔C then A↔B, and three animals is the case where that is visible.
        """
        declared = self.group(source_id, group)
        lanes = declared.lanes if declared is not None else ()
        mapping = {lane: lane for lane in lanes}
        for event in self._events.get(source_id, ()):
            if event.index > index or event.group != group or not event.moves(part):
                continue
            first, second = event.lanes
            if first in mapping and second in mapping:
                mapping[first], mapping[second] = mapping[second], mapping[first]
        return mapping

    def point_sources(self, source_id: str, index: int) -> dict[str, str]:
        """Which point's data each point *displays* at *index*.

        Only the points that actually moved are listed; a caller reading a point
        that is not in the mapping is reading its own data, which is what the
        overwhelming majority of frames and points do.

        Groups compose in declaration order.  A point can belong to two groups
        at once -- ``testMouse_leftwrist`` is an animal's point and a side's --
        and the order has to be stated somewhere rather than emerge from a dict.
        """
        composed: dict[str, str] = {}
        for group in self.groups_for(source_id):
            if not self._touches(source_id, group.name, index):
                continue
            step: dict[str, str] = {}
            for part in group.parts:
                mapping = self.lane_map(source_id, group.name, part, index)
                for lane, source_lane in mapping.items():
                    if lane == source_lane:
                        continue
                    display = group.point(lane, part)
                    data = group.point(source_lane, part)
                    if display is not None and data is not None:
                        step[display] = data
            # One group at a time, against what the previous groups already
            # decided -- never against the half-built map of this one, or the
            # second half of a transposition reads the first half's answer and
            # both points end up displaying the same data.
            composed = {
                **composed,
                **{display: composed.get(data, data) for display, data in step.items()},
            }
        return {display: data for display, data in composed.items() if display != data}

    def boundaries(self, source_id: str) -> tuple[int, ...]:
        """Every index at which the identity changes, ascending and unique.

        What the materialiser and the exporter both cut their segments on, so
        neither has to know what a transposition is.
        """
        return tuple(sorted({event.index for event in self._events.get(source_id, ())}))

    def _touches(self, source_id: str, group: str, index: int) -> bool:
        return any(
            event.group == group and event.index <= index
            for event in self._events.get(source_id, ())
        )

    # ── session persistence ──────────────────────────────────────────

    def to_list(self, source_id: str | None = None) -> list[dict[str, Any]]:
        """Serialise to a JSON-compatible list, ordered so saves are stable."""
        return [
            {"source": source, **event.as_dict()}
            for source in sorted(self._events)
            if source_id is None or source == source_id
            for event in sorted(self._events[source])
        ]

    def load(self, entries: list[dict[str, Any]] | None) -> None:
        """Replace the contents from a serialised list."""
        self._events.clear()
        self._load_entries(entries)
        self._notify(None)

    def adopt(self, entries: list[dict[str, Any]] | None) -> None:
        """Merge serialised *entries* in without dropping what is already held."""
        self._load_entries(entries)
        self._notify(None)

    def _load_entries(self, entries: list[dict[str, Any]] | None) -> None:
        for entry in entries or []:
            try:
                source = str(entry["source"])
                event = SwapEvent.from_dict(entry)
            except (KeyError, TypeError, ValueError):
                # Law 1: a session that has lost one flip still opens showing
                # everything else, and the caller reports the count it expected.
                continue
            events = self._events.setdefault(source, [])
            if event not in events:
                events.append(event)
                events.sort()
