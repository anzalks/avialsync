"""Recordings made of parts -- trials, recordings, epochs -- on one timeline.

A session scanner whose recording comes in pieces (an experiment's trials, an
acquisition's recordings) declares each piece as a :class:`Part` and lets
:func:`place` put them on the session's timeline. Every plugin uses this one
placement, so a part lands in the same place whichever reader shows it.

**The recorded clock by default.** Each part sits where its own recorded start
puts it, so the time between parts stays on the timeline as a gap: nothing was
recorded there, and the plots, the video and the imaging show nothing there
(D-217). A plugin may ask for :attr:`Placement.BACK_TO_BACK` instead, each part
starting where the previous one ends, when the format itself defines its parts
that way; that is a declaration the plugin makes, never a default.

A part that cannot be placed honestly -- no recorded start on the clock, or a
start inside the previous part -- is left out and reported, never moved.

The gap rule shared with the plots (D-009) lives here too: consecutive frames
or samples further apart than :data:`GAP_FACTOR` times their median spacing
have a gap between them, and :class:`FrameGaps` answers whether an instant is
inside one.

Gaps stay on the clock, but nobody should have to scrub through them.
:func:`common_gaps` finds the stretches where no stream has data, and
:class:`TimeWarp` collapses them for viewing only (D-218): master time, every
timestamp and every readout stay true; only the timeline's drawing and
playback skip the empty stretches.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from avialsync.core.video_timing import frame_index_at

__all__ = [
    "GAP_FACTOR",
    "MIN_COLLAPSED_GAP_S",
    "FrameGaps",
    "TimeWarp",
    "common_gaps",
    "Samples",
    "holes_between",
    "stream_spans",
    "Part",
    "PartPlan",
    "Placement",
    "into_slot",
    "place",
]

#: Spacing beyond this many median intervals is a gap, not a slow sample (D-009).
GAP_FACTOR = 10.0

#: Shorter stretches without data are left as they are when gaps are collapsed:
#: skipping a second saves nothing and would hide where one part meets the next.
MIN_COLLAPSED_GAP_S = 1.0

#: Parts closer than this are touching, not overlapping: float rounding of
#: epoch seconds is about a microsecond at today's Unix times.
_TOUCHING_S = 1e-6


class Placement(enum.Enum):
    """How a session's parts sit on its timeline."""

    #: Each part at its recorded start; the time between parts is a gap.
    CLOCK = "clock"
    #: Each part where the previous one ends. Only when the plugin declares it.
    BACK_TO_BACK = "back_to_back"


@dataclass(frozen=True)
class Part:
    """One piece of a recording: a trial, a recording, an epoch.

    ``length`` is how long the part spans from its start, in seconds.
    ``start`` is its recorded start in Unix-epoch seconds, or ``None`` when
    nothing recorded one.
    """

    name: str
    length: float
    start: float | None = None


@dataclass(frozen=True)
class PartPlan:
    """Where the placed parts sit, and what could not be placed.

    ``kept`` indexes the parts given to :func:`place`; ``starts`` and
    ``lengths`` are those parts', in seconds from the first kept part's start.
    ``epoch`` is that start in Unix-epoch seconds, ``0.0`` when unknown.
    """

    kept: list[int] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    starts: list[float] = field(default_factory=list)
    lengths: list[float] = field(default_factory=list)
    epoch: float = 0.0
    placement: Placement = Placement.CLOCK
    warnings: list[str] = field(default_factory=list)

    def segments(self) -> list[tuple[float, float, str]]:
        """The parts as ``(start, end, name)`` in Unix-epoch seconds; none without an epoch."""
        if self.epoch <= 0.0:
            return []
        return [
            (self.epoch + start, self.epoch + start + length, name)
            for name, start, length in zip(self.names, self.starts, self.lengths, strict=True)
        ]


def _recorded_start(part: Part) -> float | None:
    """The part's start on the clock, or ``None`` when nothing recorded one."""
    if part.start is None or not np.isfinite(part.start) or part.start <= 0.0:
        return None
    return float(part.start)


def place(parts: Sequence[Part], placement: Placement = Placement.CLOCK) -> PartPlan:
    """Place *parts*, in the order given, on one timeline.

    By :attr:`Placement.CLOCK` a part without a recorded start, or starting
    before the previous kept part ends, is left out with a warning. A single
    part is always kept: it is its own timeline, starting at zero.
    """
    if not parts:
        return PartPlan(placement=placement)
    if len(parts) == 1 or placement is Placement.BACK_TO_BACK:
        return _back_to_back(parts, placement)
    kept: list[int] = []
    names: list[str] = []
    epochs: list[float] = []
    lengths: list[float] = []
    warnings: list[str] = []
    end = -np.inf
    for index, part in enumerate(parts):
        start = _recorded_start(part)
        if start is None:
            warnings.append(
                f"{part.name} has no recorded start, so it cannot be placed on the "
                "recording's clock; open it on its own."
            )
            continue
        if start < end - _TOUCHING_S:
            warnings.append(
                f"{part.name} starts {end - start:.3f} s before {names[-1]} ends, "
                "so the two overlap and it is not joined; open it on its own."
            )
            continue
        kept.append(index)
        names.append(part.name)
        epochs.append(start)
        lengths.append(max(float(part.length), 0.0))
        end = start + lengths[-1]
    epoch = epochs[0] if epochs else 0.0
    return PartPlan(
        kept=kept,
        names=names,
        starts=[start - epoch for start in epochs],
        lengths=lengths,
        epoch=epoch,
        placement=placement,
        warnings=warnings,
    )


def _back_to_back(parts: Sequence[Part], placement: Placement) -> PartPlan:
    starts: list[float] = []
    lengths: list[float] = []
    position = 0.0
    for part in parts:
        starts.append(position)
        lengths.append(max(float(part.length), 0.0))
        position += lengths[-1]
    return PartPlan(
        kept=list(range(len(parts))),
        names=[part.name for part in parts],
        starts=starts,
        lengths=lengths,
        epoch=_recorded_start(parts[0]) or 0.0,
        placement=placement,
    )


def into_slot(
    times: np.ndarray, values: np.ndarray, start: float, length: float
) -> tuple[np.ndarray, np.ndarray] | None:
    """A part's samples moved to its *start*, keeping those inside its *length*.

    *times* are seconds from the part's own start. ``None`` when no sample is
    inside, so a caller yields nothing rather than an empty chunk.
    """
    inside = (times >= 0.0) & (times < length)
    if not inside.any():
        return None
    return start + times[inside], values[inside]


class FrameGaps:
    """Whether an instant falls in a gap between recorded frames (D-009, D-217).

    A frame is shown from its own time until the next frame's, as
    :func:`~avialsync.core.video_timing.frame_index_at` selects it -- except
    across a gap, where the frame lasts one median interval and the rest of
    the gap has no frame. Before the first frame and after the last are not
    gaps; whoever shows the frames bounds those already.
    """

    def __init__(self, frame_times: np.ndarray) -> None:
        self._times = np.asarray(frame_times, dtype=np.float64)
        steps = np.diff(self._times)
        self._period = float(np.median(steps)) if len(steps) else 0.0
        if self._period > 0.0:
            self._gaps = np.flatnonzero(steps > self._period * GAP_FACTOR)
        else:
            self._gaps = np.zeros(0, dtype=np.int64)

    @property
    def has_gaps(self) -> bool:
        return bool(len(self._gaps))

    def in_gap(self, t: float) -> bool:
        """Whether source time *t* lies in a gap, where no frame is shown."""
        if not len(self._gaps):
            return False
        times = self._times
        index = frame_index_at(times, t)
        position = int(np.searchsorted(self._gaps, index))
        if position == len(self._gaps) or int(self._gaps[position]) != index:
            return False
        return bool(times[index] + self._period < t < times[index + 1])


Span = tuple[float, float]


#: What a stream has between two instants: its sample times there, in master
#: seconds, and its usual spacing -- or ``None`` when it cannot tell.
Samples = tuple[np.ndarray, float] | None


def holes_between(
    bounds: Span, parts: Sequence[Span], samples: Callable[[float, float], Samples]
) -> list[Span]:
    """Where between the session's *parts* a stream with *bounds* has no data.

    Only the time between two parts can be a hole: a dropout inside a part is a
    data gap (D-009), shown as one, not as the stream stopping. Between two
    parts, a stream may run on a little past one part's end or start a little
    before the next (a camera stopping a few frames after its capture); those
    samples are data, and the hole is the empty stretch between them -- any
    stretch longer than :data:`GAP_FACTOR` of its spacing, from one spacing
    after a sample. A stream that cannot say has no holes: nothing is hidden on
    a guess.
    """
    first, last = bounds
    ordered = sorted(parts)
    holes: list[Span] = []
    for (_start, end), (start, _end) in zip(ordered, ordered[1:], strict=False):
        a, b = max(end, first), min(start, last)
        if b <= a:
            continue
        found = samples(a, b)
        if found is not None:
            holes += _empty_stretches(a, b, *found)
    return holes


def _empty_stretches(a: float, b: float, inside: np.ndarray, period: float) -> list[Span]:
    """The stretches of ``(a, b)`` without samples, longer than the gap rule."""
    times = np.asarray(inside, dtype=np.float64)
    times = times[(times > a) & (times < b)]
    if not len(times):
        return [(a, b)]
    if period <= 0.0 and len(times) > 1:
        period = float(np.median(np.diff(times)))
    tolerance = period * GAP_FACTOR
    edges = np.concatenate(([a], times, [b]))
    steps = np.diff(edges)
    stretches: list[Span] = []
    for index in np.flatnonzero(steps > tolerance):
        # From one spacing after a sample: the last one shows for its own period.
        left = float(edges[index]) + (period if index > 0 else 0.0)
        right = float(edges[index + 1])
        if right > left:
            stretches.append((left, right))
    return stretches


def stream_spans(bounds: Span, holes: Sequence[Span]) -> list[Span]:
    """A stream's stretches of data: its bounds less its holes."""
    spans: list[Span] = []
    position = bounds[0]
    for a, b in sorted(holes):
        if a > position:
            spans.append((position, a))
        position = max(position, b)
    if bounds[1] > position or not spans:
        spans.append((position, bounds[1]))
    return spans


def common_gaps(
    streams: Sequence[Sequence[Span]], minimum: float = MIN_COLLAPSED_GAP_S
) -> list[Span]:
    """Where no stream has data, between the first data and the last.

    Collapsing only these hides nothing: the stream with the fewest gaps
    decides, and wherever any stream recorded, the time is kept. Stretches
    shorter than *minimum* are kept too.
    """
    merged: list[Span] = []
    for start, end in sorted(span for spans in streams for span in spans if span[1] >= span[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return [
        (a[1], b[0]) for a, b in zip(merged, merged[1:], strict=False) if b[0] - a[1] >= minimum
    ]


class TimeWarp:
    """Master time drawn with the gaps between data collapsed (D-218).

    Each collapsed gap is drawn as a break of no width: view time runs on
    from the last data before it to the first data after it. Master time is
    untouched -- this only says where to draw an instant, and which instant a
    position on the timeline means. A position on a break means the data
    after it.
    """

    def __init__(self, gaps: Sequence[Span] = ()) -> None:
        self.gaps: tuple[Span, ...] = tuple(sorted((float(a), float(b)) for a, b in gaps if b > a))
        self._starts = np.asarray([a for a, _b in self.gaps], dtype=np.float64)
        self._removed = np.cumsum([b - a for a, b in self.gaps], dtype=np.float64)
        # A gap's start in view time: where the break is drawn.
        self._breaks = self._starts - np.concatenate(([0.0], self._removed[:-1]))

    def __bool__(self) -> bool:
        return bool(self.gaps)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TimeWarp) and other.gaps == self.gaps

    def __hash__(self) -> int:
        return hash(self.gaps)

    @property
    def breaks(self) -> np.ndarray:
        """Where each collapsed gap sits, in view time."""
        return self._breaks

    def to_view(self, t: float) -> float:
        """Where master time *t* is drawn; inside a gap, at its break."""
        if not self.gaps:
            return float(t)
        index = int(np.searchsorted(self._starts, t, side="right")) - 1
        if index < 0:
            return float(t)
        a, b = self.gaps[index]
        before = float(self._removed[index - 1]) if index else 0.0
        if t < b:
            return a - before
        return float(t) - float(self._removed[index])

    def to_master(self, v: float, snap: float = 0.0) -> float:
        """The master time drawn at view time *v*; a break means the data after it.

        A *v* within *snap* before a break is on it: a click lands on a pixel,
        and the break's pixel is the one a person aims at to cross it.
        """
        if not self.gaps:
            return float(v)
        ahead = int(np.searchsorted(self._breaks, v, side="right"))
        if ahead < len(self._breaks) and self._breaks[ahead] - v <= snap:
            return self.gaps[ahead][1]
        index = ahead - 1
        if index < 0:
            return float(v)
        return float(v) + float(self._removed[index])

    def to_view_array(self, times: np.ndarray) -> np.ndarray:
        """:meth:`to_view` for many master times at once (a plot page's samples)."""
        times = np.asarray(times, dtype=np.float64)
        if not self.gaps:
            return times
        index = np.searchsorted(self._starts, times, side="right") - 1
        safe = np.maximum(index, 0)
        ends = np.asarray([b for _a, b in self.gaps], dtype=np.float64)[safe]
        removed = self._removed[safe]
        view = np.where(times < ends, self._breaks[safe], times - removed)
        return np.where(index < 0, times, view)

    def gap_at(self, t: float) -> Span | None:
        """The collapsed gap *t* lies in, if any (its start counts, its end does not)."""
        index = int(np.searchsorted(self._starts, t, side="right")) - 1
        if index < 0:
            return None
        a, b = self.gaps[index]
        return (a, b) if a <= t < b else None
