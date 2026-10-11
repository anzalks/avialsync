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
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from avialsync.core.video_timing import frame_index_at

__all__ = [
    "GAP_FACTOR",
    "FrameGaps",
    "Part",
    "PartPlan",
    "Placement",
    "into_slot",
    "place",
]

#: Spacing beyond this many median intervals is a gap, not a slow sample (D-009).
GAP_FACTOR = 10.0

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
