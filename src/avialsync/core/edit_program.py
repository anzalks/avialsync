"""What the tracker should say, computed once and rendered twice.

Two things have to agree about a pose source that a person has edited: the data
the application draws, and the file it exports.  They are produced by different
code -- one writes pyramid arrays into the cache, the other streams a CSV row by
row -- and if each worked out the edits for itself, the picture on screen and
the file handed to an analysis could disagree without either being obviously
wrong.  That is the defect to design out rather than test for later, so both
render *this*: one program, computed from the sidecars, with no opinion about
arrays or CSV columns (D-142).

A program is two things, in this order:

1. **corrections**, keyed by the point they were made on in the *file's own*
   columns, because a hand-placed coordinate is a fact about that trajectory
   (D-143);
2. **routes**, which say whose data each point displays over which span of
   frames -- the composed effect of every accepted identity flip.

Order matters and is fixed here: a correction lands in the raw column, and the
routing then carries it wherever that column is displayed.  Reverse the two and
a correction made before a flip would stay on screen while the animal it
belongs to walked away with the other label.

The program carries a ``fingerprint``.  It names the derived cache generation,
so a rebuild is skipped when nothing about the edits changed, and a stale
generation can never be mistaken for a current one.
"""

from __future__ import annotations

import bisect
import dataclasses
import json
from collections.abc import Iterable, Mapping, Sequence

import xxhash

from avialsync.core.identity_swaps import SwapStore
from avialsync.core.point_edits import PointEditStore

__all__ = ["Segment", "EditProgram", "build"]

#: Stands for "to the end of the recording" in a segment that nothing closes.
END = -1


@dataclasses.dataclass(frozen=True, slots=True)
class Segment:
    """A span of samples over which one point displays another's data.

    ``stop`` is exclusive, or :data:`END` when the span runs to the end of the
    recording -- which is the ordinary case, because a flip holds until another
    flip changes it.
    """

    start: int
    stop: int
    source: str

    def bounded(self, sample_count: int) -> tuple[int, int]:
        """Return ``(start, stop)`` clamped into a recording of *sample_count*."""
        stop = sample_count if self.stop == END else min(self.stop, sample_count)
        return max(0, min(self.start, sample_count)), max(0, stop)


@dataclasses.dataclass(frozen=True)
class EditProgram:
    """Every edit that stands between a pose recording and what is shown."""

    source_id: str
    #: Ascending sample indices at which the routing changes.
    boundaries: tuple[int, ...]
    #: ``maps[i]`` is in force from ``boundaries[i]`` until ``boundaries[i+1]``.
    #: Each holds only the points that read somebody else's data.
    maps: tuple[Mapping[str, str], ...]
    #: ``(point, index) -> (x, y)`` in the file's own columns.
    corrections: Mapping[tuple[str, int], tuple[float, float]]
    fingerprint: str

    def __bool__(self) -> bool:
        """Whether anything at all has been edited."""
        return bool(self.maps) or bool(self.corrections)

    # ── what a renderer asks ─────────────────────────────────────────

    def route_at(self, index: int) -> Mapping[str, str]:
        """Which point each point displays at *index*; empty before any flip."""
        if not self.boundaries or index < self.boundaries[0]:
            return {}
        position = bisect.bisect_right(self.boundaries, index) - 1
        return self.maps[position]

    def source_of(self, point: str, index: int) -> str:
        """The point whose data *point* displays at *index* -- itself, usually."""
        return self.route_at(index).get(point, point)

    def correction(self, point: str, index: int) -> tuple[float, float] | None:
        """The hand correction on *point* at *index*, in the file's own columns."""
        return self.corrections.get((point, index))

    def segments_for(self, point: str) -> tuple[Segment, ...]:
        """Where *point* displays another point's data, in frame order.

        Only the spans that differ from the recording: a point nobody flipped
        produces nothing, which is what lets the cache leave it alone.
        """
        segments: list[Segment] = []
        for position, mapping in enumerate(self.maps):
            source = mapping.get(point)
            if source is None or source == point:
                continue
            start = self.boundaries[position]
            stop = self.boundaries[position + 1] if position + 1 < len(self.boundaries) else END
            if segments and segments[-1].source == source and segments[-1].stop == start:
                segments[-1] = dataclasses.replace(segments[-1], stop=stop)
            else:
                segments.append(Segment(start=start, stop=stop, source=source))
        return tuple(segments)

    def reads(self, point: str) -> frozenset[str]:
        """Every point whose data *point* ever displays, including itself.

        What the materialiser needs to decide whether a correction elsewhere
        changes this point's values.
        """
        sources = {point}
        for mapping in self.maps:
            sources.add(mapping.get(point, point))
        return frozenset(sources)

    def affected(self, points: Iterable[str]) -> tuple[str, ...]:
        """The points whose displayed values differ from the recording's.

        A point is affected when it is routed anywhere, or when any point it
        ever reads carries a correction.  Everything else can go on being read
        straight out of the original cache, which is why an edit costs two
        channels rather than a re-import.
        """
        corrected = {point for point, _ in self.corrections}
        return tuple(
            point for point in points if self.segments_for(point) or (self.reads(point) & corrected)
        )


def build(
    source_id: str,
    swaps: SwapStore,
    corrections: PointEditStore,
    *,
    points: Sequence[str] = (),
) -> EditProgram:
    """Compute the program for one pose source from the two stores.

    *points* is the source's full point list, used only to keep the fingerprint
    stable when a group's membership changes without any edit changing.
    """
    boundaries = swaps.boundaries(source_id)
    maps = tuple(swaps.point_sources(source_id, boundary) for boundary in boundaries)
    edits = {(point, index): (x, y) for index, point, x, y in corrections.for_source(source_id)}
    return EditProgram(
        source_id=source_id,
        boundaries=boundaries,
        maps=maps,
        corrections=edits,
        fingerprint=_fingerprint(boundaries, maps, edits, points),
    )


def _fingerprint(
    boundaries: tuple[int, ...],
    maps: tuple[Mapping[str, str], ...],
    corrections: Mapping[tuple[str, int], tuple[float, float]],
    points: Sequence[str],
) -> str:
    """A stable name for exactly this set of edits.

    Sorted at every level: two sessions that made the same edits in a different
    order must name the same cache generation, or every reopen rebuilds.
    """
    payload = json.dumps(
        {
            "boundaries": list(boundaries),
            "maps": [sorted(mapping.items()) for mapping in maps],
            "corrections": sorted(
                (point, index, value[0], value[1]) for (point, index), value in corrections.items()
            ),
            "points": sorted(points),
        },
        separators=(",", ":"),
    )
    return str(xxhash.xxh3_64_hexdigest(payload))
