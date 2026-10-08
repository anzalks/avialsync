"""What a TTL train is evidence *of*, which depends on which way the wire ran.

Two topologies produce a pulse per frame and they are not interchangeable.

An **external trigger** runs from a pulse generator into the camera.  The DAQ
knows when it *asked* for frame N; it does not know whether frame N happened.
A dropped exposure shifts every later frame by one and the residuals stay
beautiful, because the wrong pairs still fit a line.  The only cheap check is
count agreement -- pulses recorded against frames in the container -- and when
those disagree you know drops occurred but not where.

A **frame strobe** runs from the camera into the DAQ: one pulse per exposure
that actually happened.  Pulse count is frame count by construction, a drop is
an interval outlier in the train, and the mapping is exact with no model at
all.  This is strictly better evidence and is what the field prefers when the
hardware offers it.

Both edges are kept.  Rising is exposure start and falling is exposure end, so
a strobe gives exposure *duration* for free and lets a frame be timestamped at
its midpoint -- the correct instant for a moving subject, and standard practice
in high-speed behaviour work.  Extracting one edge direction throws that away.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from enum import StrEnum

import numpy as np

from avialsync.core.errors import SyncEvidenceError

__all__ = [
    "DROP_INTERVAL_TOLERANCE",
    "Reconciliation",
    "TriggerKind",
    "TriggerTrain",
    "extract_pulses",
    "locate_drops",
    "reconcile_with_frames",
]


class TriggerKind(StrEnum):
    """What a train of pulses is evidence of, and therefore what it licenses."""

    #: Camera to DAQ, one pulse per exposure that happened. Pulse count is
    #: frame count; a drop is visible in the train itself.
    FRAME_STROBE = "frame_strobe"
    #: DAQ to camera, one pulse per exposure that was *requested*. Says nothing
    #: about whether the frame arrived.
    FRAME_TRIGGER = "frame_trigger"
    #: A shared square wave recorded by both systems, far sparser than the
    #: frame rate. Enough to track a clock, not to identify a frame.
    SYNC_TRAIN = "sync_train"
    #: A handful of landmarks -- a start pulse, a stop pulse, a hand-thrown
    #: switch. Enough to place a recording, rarely enough to check the placing.
    SPARSE_EVENTS = "sparse_events"

    @property
    def identifies_frames(self) -> bool:
        """Whether one pulse corresponds to one frame of video."""
        return self in (TriggerKind.FRAME_STROBE, TriggerKind.FRAME_TRIGGER)

    @property
    def confirms_frames(self) -> bool:
        """Whether the pulses are evidence that the frames actually happened.

        Only a strobe is. A trigger train records an intention, and an
        intention that was not honoured looks exactly like one that was.
        """
        return self is TriggerKind.FRAME_STROBE


#: An interval this far past a whole multiple of the modal interval is not a
#: drop, it is jitter or a genuinely irregular train. Half an interval either
#: way, so the classification is never a close call.
DROP_INTERVAL_TOLERANCE = 0.25


@dataclasses.dataclass(frozen=True)
class TriggerTrain:
    """Pulses from one source, with what their shape says about them."""

    kind: TriggerKind
    source_id: str
    #: One timestamp per pulse. For a strobe this is the exposure midpoint;
    #: for everything else it is the rising edge.
    times: np.ndarray
    #: Exposure duration per pulse, where both edges were recorded.
    durations: np.ndarray | None = None
    #: Indices in :attr:`times` *after* which the train skips a beat. Empty for
    #: an irregular train, where the idea does not apply.
    drops: tuple[int, ...] = ()
    #: Pulses whose start or end crossed unavailable samples. These cannot
    #: establish a frame index, even when the visible pulse count agrees.
    incomplete_count: int = 0
    incomplete_indices: tuple[int, ...] = ()

    @property
    def count(self) -> int:
        return int(len(self.times))

    @property
    def span(self) -> float:
        """Seconds from the first pulse to the last."""
        if len(self.times) < 2:
            return 0.0
        return float(self.times[-1] - self.times[0])

    @property
    def mean_exposure(self) -> float | None:
        """Mean exposure duration, when both edges were recorded."""
        if self.durations is None or not len(self.durations):
            return None
        return float(np.mean(self.durations))


@dataclasses.dataclass(frozen=True)
class Reconciliation:
    """Whether a train and a container agree about how many frames there are."""

    pulses: int
    frames: int
    kind: TriggerKind

    @property
    def agrees(self) -> bool:
        return self.pulses == self.frames

    @property
    def exact_mapping_is_safe(self) -> bool:
        """Whether the counts license pairing pulse *i* with frame *i*.

        A strobe that agrees is the one case where it is. A trigger train that
        agrees only means nothing *visibly* went wrong: the camera may have
        dropped a frame and duplicated another, and the counts would still
        match. Agreement on a trigger train is the absence of evidence, and is
        treated as such.
        """
        return self.agrees and self.kind.confirms_frames

    def explain(self) -> str:
        """What these counts do and do not permit, in a sentence."""
        if self.agrees and self.kind.confirms_frames:
            return (
                f"{self.pulses} exposures recorded and {self.frames} frames stored: "
                "each frame can be given the time its own exposure was measured at."
            )
        if self.agrees:
            return (
                f"{self.pulses} triggers sent and {self.frames} frames stored. The counts "
                "agree, which is not the same as evidence that each frame is the one its "
                "trigger asked for -- a drop and a duplicate would also agree."
            )
        missing = self.frames - self.pulses
        if missing < 0:
            return (
                f"{self.pulses} triggers sent but only {self.frames} frames stored: "
                f"{-missing} exposures did not reach the file. Pairing by index would "
                "shift every frame after the first loss."
            )
        return (
            f"{self.pulses} triggers recorded against {self.frames} frames: {missing} "
            "frames have no trigger, so the recordings do not cover the same interval."
        )


def extract_pulses(
    chunks: Iterable[tuple[np.ndarray, np.ndarray] | tuple[np.ndarray, np.ndarray, np.ndarray]],
    *,
    source_id: str,
    kind: TriggerKind,
    threshold: float = 0.5,
    min_interval: float = 0.0,
) -> TriggerTrain:
    """Extract complete pulses -- both edges -- from chronological chunks.

    Missing data is unknown, never low. A pulse with an edge inside a gap, a
    non-finite (or loader-masked sentinel) run, or before the first sample is
    left out and counted in ``incomplete_count``: treating the hole as low
    would split one pulse into two. A final pulse still high when the
    recording stops keeps its rise and is listed in ``incomplete_indices``.

    Args:
        chunks: One-dimensional ``(time, value[, gap_after])`` chunks in strict
            time order. A true gap marks the interval after that sample unknown.
        source_id: Stable identifier of the evidence source.
        kind: What this train is evidence of.
        threshold: Values at or above this level are logical high.
        min_interval: Suppress bounce transitions closer together than this.

    Raises:
        SyncEvidenceError: If chunk shape or chronology makes the evidence unsafe.
    """
    if not source_id:
        raise SyncEvidenceError("Trigger evidence needs a source identifier.")
    if min_interval < 0:
        raise SyncEvidenceError("min_interval must be non-negative.")

    rising: list[float] = []
    falling: list[float] = []
    previous_high: bool | None = None
    previous_time: float | None = None
    gap_after_previous = False
    # Before the first sample the line's state is unknown, exactly as after a
    # gap: a recording that opens mid-pulse has lost that pulse's rise.
    unknown = True
    unknown_counted = False
    last_rise = -np.inf
    incomplete = 0

    for chunk in chunks:
        times, values = chunk[:2]
        gaps = chunk[2] if len(chunk) == 3 else np.zeros(len(times), dtype=bool)
        times_arr = np.asarray(times, dtype=np.float64)
        values_arr = np.asarray(values)
        gaps_arr = np.asarray(gaps, dtype=bool)
        if times_arr.ndim != 1 or values_arr.ndim != 1 or len(times_arr) != len(values_arr):
            raise SyncEvidenceError("Trigger chunks must be equally sized one-dimensional arrays.")
        if gaps_arr.shape != times_arr.shape:
            raise SyncEvidenceError("Trigger gap masks must match their chunks.")
        if not np.all(np.isfinite(times_arr)):
            raise SyncEvidenceError("Trigger timestamps must be finite.")
        if len(times_arr) and np.any(np.diff(times_arr) <= 0):
            raise SyncEvidenceError("Trigger timestamps must be strictly increasing.")
        if previous_time is not None and len(times_arr) and times_arr[0] <= previous_time:
            raise SyncEvidenceError("Trigger timestamps must be strictly increasing across chunks.")

        for time, value, gap_after in zip(times_arr, values_arr, gaps_arr, strict=True):
            sample_unknown = (gap_after_previous and bool(gap_after)) or not np.isfinite(value)
            if gap_after_previous or sample_unknown:
                if previous_high:
                    incomplete += 1
                    unknown_counted = True
                    if len(rising) > len(falling):
                        rising.pop()
                previous_high = None
                unknown = True
            if sample_unknown:
                gap_after_previous = bool(gap_after)
                previous_time = float(time)
                continue
            high = bool(value >= threshold)
            if previous_high is None and high and unknown and not unknown_counted:
                # A high after missing data may be the tail of an earlier
                # pulse. Wait for a known low before accepting a new rise.
                incomplete += 1
                unknown_counted = True
            if not high:
                unknown = False
                unknown_counted = False
            if previous_high is not None:
                if not previous_high and high and time - last_rise >= min_interval:
                    if not unknown:
                        rising.append(float(time))
                        last_rise = float(time)
                elif previous_high and not high and len(rising) > len(falling):
                    falling.append(float(time))
            previous_high = bool(high)
            previous_time = float(time)
            gap_after_previous = bool(gap_after)

    train = _train_from_edges(rising, falling, source_id=source_id, kind=kind)
    incomplete_indices: tuple[int, ...] = ()
    if len(rising) > len(falling):
        incomplete += 1
        incomplete_indices = (len(train.times) - 1,)
    return dataclasses.replace(
        train, incomplete_count=incomplete, incomplete_indices=incomplete_indices
    )


def _train_from_edges(
    rising: list[float], falling: list[float], *, source_id: str, kind: TriggerKind
) -> TriggerTrain:
    """Pair edges into pulses, timestamping a strobe at its exposure midpoint.

    A trailing rise with no matching fall is a pulse still high when the
    recording stopped. Its start is known and its end is not, so it keeps its
    rising edge and contributes no duration rather than being dropped -- losing
    the last frame of a recording to a missing edge would be worse than
    admitting its exposure length is unknown.
    """
    paired = min(len(rising), len(falling))
    starts = np.asarray(rising, dtype=np.float64)
    if paired == 0:
        return TriggerTrain(kind=kind, source_id=source_id, times=starts, durations=None)

    ends = np.asarray(falling[:paired], dtype=np.float64)
    durations = ends - starts[:paired]
    if kind is TriggerKind.FRAME_STROBE:
        # The instant the frame represents. A subject moving through a 5 ms
        # exposure is at the midpoint's position, not the opening shutter's.
        times = starts.copy()
        times[:paired] = starts[:paired] + durations / 2.0
    else:
        times = starts

    return TriggerTrain(
        kind=kind,
        source_id=source_id,
        times=times,
        durations=durations,
        drops=locate_drops(times),
    )


def locate_drops(times: np.ndarray) -> tuple[int, ...]:
    """Indices after which a regular train skips one or more beats.

    Only meaningful for a train that is regular to begin with: an interval that
    is a clean multiple of the modal one is a gap, while on an irregular train
    every interval is its own length and nothing can be inferred. Returns
    nothing rather than guessing when the train is not regular.
    """
    values = np.asarray(times, dtype=np.float64)
    if len(values) < 3:
        return ()
    intervals = np.diff(values)
    modal = float(np.median(intervals))
    if modal <= 0:
        return ()

    ratios = intervals / modal
    # Regular enough to reason about: most intervals sit on the modal one.
    near_modal = np.abs(ratios - 1.0) <= DROP_INTERVAL_TOLERANCE
    if np.count_nonzero(near_modal) < 0.5 * len(intervals):
        return ()

    whole = np.rint(ratios)
    is_gap = (whole >= 2.0) & (np.abs(ratios - whole) <= DROP_INTERVAL_TOLERANCE)
    return tuple(int(index) for index in np.flatnonzero(is_gap))


def reconcile_with_frames(train: TriggerTrain, frame_count: int) -> Reconciliation:
    """Compare a train against the frames a container actually holds."""
    if frame_count < 0:
        raise SyncEvidenceError("A frame count cannot be negative.")
    return Reconciliation(pulses=train.count, frames=int(frame_count), kind=train.kind)
