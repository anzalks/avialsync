"""Finding where a tracker probably lost track of which is which.

Two trajectories that cross are an estimator's hard case, and the signature of
a flip it got wrong is specific: at one frame, each track's own motion predicts
the *other* label's observation better than its own.  That comparison -- keep
against swap, against where each point was heading -- is the whole detector,
and it is the arithmetic the tracker should have done and did not.

**Predicted, not merely previous.**  Comparing against the last seen position
works only while nothing is occluded, and occlusion is exactly where identity
is lost: across five missing frames both animals have moved, both hypotheses
cost roughly that movement, and the difference that matters is buried in it.
Each track is therefore carried forward at its own velocity to the frame in
question, and the two hypotheses are scored on what is left over.

**It proposes; it never applies.**  Alignment works this way for a reason
(BLUEPRINT principle 8) and so does this: a candidate carries the evidence it
was proposed on -- how close the two came, how much cheaper swapping is, how
many frames were missing across the node -- and a person accepts it or does
not.  Silently rewriting an identity because a threshold fired is the failure
this exists to prevent, not a convenience it declines to offer.

**The thresholds scale with the data, not with pixels.**  A default in pixels
is a default for one camera at one working distance.  Everything here is
expressed in multiples of the *median step* -- how far a point moves between
consecutive frames in this recording -- so a proposal means the same thing on a
close-up of a paw and on an arena seen from three metres up.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence

import numpy as np

__all__ = ["Trajectory", "Candidate", "detect", "centroid"]

#: Swapping must leave no more than this share of the residual that keeping
#: leaves before a frame is proposed.  Half: a genuine flip is usually an order
#: of magnitude better, and anything near parity is two points milling about.
DEFAULT_RATIO = 0.5

#: A residual this small is noise, whatever its ratio.  Multiples of the median
#: step, so a resting animal does not produce a proposal every frame.
DEFAULT_MIN_TRAVEL = 3.0

#: The two must come within this many frames' worth of travel of each other
#: *somewhere near the node* before a cheaper swap counts as evidence.  Further
#: apart than that the whole time, it is arithmetic about two unrelated animals
#: rather than evidence about one crossing.
DEFAULT_PROXIMITY = 4.0

#: How far either side of a node to look for that closest approach.  Measuring
#: it *at* the node would fight the cost test rather than support it: a flip is
#: revealed a few frames after the touch that caused it.
DEFAULT_PROXIMITY_FRAMES = 30

#: Proposals nearer than this many frames to a stronger one are suppressed: a
#: crossing produces a burst, and forty rows for one event is a list nobody
#: reads.
DEFAULT_SEPARATION_FRAMES = 15


@dataclasses.dataclass(frozen=True, slots=True)
class Trajectory:
    """One lane's position over the whole recording, in the source's own frames."""

    x: np.ndarray
    y: np.ndarray

    def valid(self) -> np.ndarray:
        """Where this lane has a position at all."""
        return ~(np.isnan(self.x) | np.isnan(self.y))


@dataclasses.dataclass(frozen=True, slots=True, order=True)
class Candidate:
    """One proposed flip, and the evidence it was proposed on."""

    index: int
    lanes: tuple[str, str]
    #: How near the two lanes came within a window of the node, in source
    #: units: the closest approach, which is what makes a flip possible at all.
    separation: float
    #: Residual left by swapping over residual left by keeping.  Below one
    #: means each track's own motion predicted the other label's observation.
    cost_ratio: float
    #: Frames with no position across the node -- an occlusion, which is where
    #: an estimator loses identity in the first place.
    gap: int

    def as_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "lanes": list(self.lanes),
            "separation": self.separation,
            "cost_ratio": self.cost_ratio,
            "gap": self.gap,
        }


def centroid(parts: Sequence[Trajectory]) -> Trajectory:
    """Average the parts a lane carries, ignoring the ones missing per frame.

    What "All parts" is detected on.  A whole-animal flip moves every part at
    once, so the centroid is both the strongest signal and the one least
    disturbed by a single body part the model lost.
    """
    if not parts:
        return Trajectory(np.zeros(0), np.zeros(0))
    xs = np.vstack([part.x for part in parts])
    ys = np.vstack([part.y for part in parts])
    # nanmean warns for a frame where every part is absent. That frame remains
    # missing evidence; it should neither invent a position nor flood the log.
    valid_x = ~np.isnan(xs)
    valid_y = ~np.isnan(ys)
    mean_x = np.full(xs.shape[1], np.nan, dtype=float)
    mean_y = np.full(ys.shape[1], np.nan, dtype=float)
    np.divide(
        np.where(valid_x, xs, 0.0).sum(axis=0),
        valid_x.sum(axis=0),
        out=mean_x,
        where=valid_x.any(axis=0),
    )
    np.divide(
        np.where(valid_y, ys, 0.0).sum(axis=0),
        valid_y.sum(axis=0),
        out=mean_y,
        where=valid_y.any(axis=0),
    )
    return Trajectory(np.asarray(mean_x, dtype=float), np.asarray(mean_y, dtype=float))


def detect(
    lanes: Mapping[str, Trajectory],
    *,
    ratio: float = DEFAULT_RATIO,
    min_travel: float = DEFAULT_MIN_TRAVEL,
    proximity: float = DEFAULT_PROXIMITY,
    proximity_frames: int = DEFAULT_PROXIMITY_FRAMES,
    separation_frames: int = DEFAULT_SEPARATION_FRAMES,
) -> tuple[Candidate, ...]:
    """Propose the frames at which each pair of *lanes* may have exchanged.

    Every pair is examined independently, so three animals produce proposals
    for all three pairs and the person decides which two crossed.
    """
    names = list(lanes)
    proposals: list[Candidate] = []
    for first in range(len(names)):
        for second in range(first + 1, len(names)):
            a, b = names[first], names[second]
            proposals.extend(
                _pair(
                    a,
                    b,
                    lanes[a],
                    lanes[b],
                    ratio=ratio,
                    min_travel=min_travel,
                    proximity=proximity,
                    proximity_frames=proximity_frames,
                    separation_frames=separation_frames,
                )
            )
    return tuple(sorted(proposals))


def _pair(
    first: str,
    second: str,
    a: Trajectory,
    b: Trajectory,
    *,
    ratio: float,
    min_travel: float,
    proximity: float,
    proximity_frames: int,
    separation_frames: int,
) -> list[Candidate]:
    count = min(len(a.x), len(b.x))
    if count < 3:
        return []

    valid = a.valid()[:count] & b.valid()[:count]
    if valid.sum() < 3:
        return []

    previous, earlier = _lookbacks(valid, count)
    live = valid & (previous >= 0) & (earlier >= 0)
    if not live.any():
        return []

    indices = np.arange(count)
    here, there, before = indices[live], previous[live], earlier[live]

    predicted_a = _predict(a, here, there, before)
    predicted_b = _predict(b, here, there, before)
    observed_a = (a.x[here], a.y[here])
    observed_b = (b.x[here], b.y[here])

    keep = _apart(predicted_a, observed_a) + _apart(predicted_b, observed_b)
    swap = _apart(predicted_a, observed_b) + _apart(predicted_b, observed_a)
    gap = here - there - 1

    step = _median_step(a, b, valid)
    if not np.isfinite(step) or step <= 0.0:
        return []

    with np.errstate(divide="ignore", invalid="ignore"):
        ratios = np.where(keep > 0.0, swap / keep, np.inf)

    cheaper = (ratios <= ratio) & (keep >= min_travel * step)
    if not cheaper.any():
        return []

    # Only now, on the handful of frames that survived, is the closest approach
    # worth computing -- it needs a window per candidate rather than a column.
    separation = np.where(valid, _apart((a.x, a.y), (b.x, b.y)), np.inf)
    proposals: list[Candidate] = []
    for position in np.flatnonzero(cheaper):
        index = int(here[position])
        closest = _closest_approach(separation, index, proximity_frames)
        if closest > proximity * step:
            continue
        proposals.append(
            Candidate(
                index=index,
                lanes=(first, second),
                separation=float(closest),
                cost_ratio=float(ratios[position]),
                gap=int(gap[position]),
            )
        )
    return _suppress(proposals, separation_frames)


def _lookbacks(valid: np.ndarray, count: int) -> tuple[np.ndarray, np.ndarray]:
    """The last two frames before each one at which both lanes had a position.

    ``-1`` where there is no such frame.  The second is what gives a velocity,
    and therefore what lets the comparison reach across an occlusion instead of
    stopping at it.
    """
    indices = np.arange(count)
    previous = np.maximum.accumulate(np.where(valid, indices, -1))
    previous = np.concatenate(([-1], previous[:-1]))
    earlier = np.where(previous >= 0, previous[np.maximum(previous, 0)], -1)
    return previous, earlier


def _predict(
    lane: Trajectory, here: np.ndarray, there: np.ndarray, before: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Where *lane* would be at ``here``, carried forward at its own velocity."""
    span = (here - there).astype(float)
    back = (there - before).astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        safe = np.where(back > 0.0, back, 1.0)
        vx = np.where(back > 0.0, (lane.x[there] - lane.x[before]) / safe, 0.0)
        vy = np.where(back > 0.0, (lane.y[there] - lane.y[before]) / safe, 0.0)
    return lane.x[there] + vx * span, lane.y[there] + vy * span


def _apart(
    first: tuple[np.ndarray, np.ndarray], second: tuple[np.ndarray, np.ndarray]
) -> np.ndarray:
    return np.asarray(np.hypot(first[0] - second[0], first[1] - second[1]), dtype=float)


def _median_step(a: Trajectory, b: Trajectory, valid: np.ndarray) -> float:
    """How far a point moves between consecutive frames, typically.

    The unit every threshold is stated in.  Taken across both lanes and over
    the frames where both were seen, so one lane the model mostly lost cannot
    set the scale for the recording.
    """
    steps: list[np.ndarray] = []
    for lane in (a, b):
        x = lane.x[: len(valid)][valid]
        y = lane.y[: len(valid)][valid]
        if len(x) >= 2:
            steps.append(np.hypot(np.diff(x), np.diff(y)))
    if not steps:
        return float("nan")
    joined = np.concatenate(steps)
    joined = joined[np.isfinite(joined)]
    if joined.size == 0:
        return float("nan")
    return float(np.median(joined))


def _closest_approach(separation: np.ndarray, index: int, window: int) -> float:
    """How near the two lanes ever came within *window* frames of *index*."""
    first = max(0, index - window)
    last = min(len(separation), index + window + 1)
    if last <= first:
        return float("inf")
    return float(np.min(separation[first:last]))


def _suppress(candidates: list[Candidate], window: int) -> list[Candidate]:
    """Keep the strongest proposal in each burst, in frame order."""
    if window <= 0:
        return candidates
    kept: list[Candidate] = []
    for candidate in sorted(candidates, key=lambda item: item.cost_ratio):
        if all(abs(candidate.index - other.index) > window for other in kept):
            kept.append(candidate)
    return sorted(kept)
