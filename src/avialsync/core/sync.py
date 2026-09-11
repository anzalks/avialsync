"""Headless evidence-based synchronization primitives.

The functions in this module preserve source timestamps.  They only propose an
affine mapping from master/reference time to a target source; the UI is
responsible for showing the evidence and obtaining user acceptance.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

import numpy as np

from avialsync.core.errors import SyncAmbiguityError, SyncEvidenceError
from avialsync.core.timeline import TimeMap

Edge = Literal["rising", "falling"]
_MAX_PRESENTED_EVIDENCE = 500


class AlignmentMethod(StrEnum):
    """How a mapping was arrived at, which is not recoverable from its numbers.

    A hand-typed offset and a three-event fit with perfect residuals are the
    same six floats. Without this field the session had no way to tell them
    apart, and the reader printed the typed one as "± 0.0 ms from 3 events" --
    the highest confidence a record could express -- because the wizard had
    filled a count of 3 in to clear an acceptance gate.

    A string enum so it survives a JSON round trip as itself.
    """

    #: Per-frame evidence paired one to one. Residuals are zero by
    #: construction, so its confidence comes from count agreement, not scatter.
    EXACT = "exact"
    #: Offset and rate fitted from matched events.
    AFFINE = "affine"
    #: Offset alone, either because the span cannot support a rate or because
    #: the evidence was too sparse to fit one.
    SHIFT = "shift"
    #: Determined but unchecked: enough evidence to place the source, none left
    #: over to test the placement with.
    UNVALIDATED = "unvalidated"
    #: Typed or dragged by a person. Carries no evidence and never claims any.
    MANUAL = "manual"

    @property
    def is_evidence_based(self) -> bool:
        """Whether residuals and counts mean anything for this method."""
        return self in (AlignmentMethod.EXACT, AlignmentMethod.AFFINE, AlignmentMethod.SHIFT)


#: A free-running crystal is specified at ±20-100 ppm and a TCXO at ±2; 200 is
#: already generous for anything that has not been baked or frozen. A fit that
#: comes back outside this has not measured a clock difference -- it has paired
#: the wrong events, or been handed two quantities that are not both seconds.
#: Reported rather than clamped: the number names the diagnosis.
MAX_PLAUSIBLE_DRIFT_PPM = 200.0

#: Below this fraction of the reference events finding a partner, a fit is not
#: a noisy alignment, it is a different hypothesis. Uniform grids commensurate
#: at wrong rates and land a minority of points exactly, which is why a low
#: match rate and a tiny residual arrive together rather than trading off.
MIN_MATCH_RATE = 0.5

#: How much better the winning sequence offset must be than the best rival at a
#: materially different lag. A uniform pulse train is ambiguous at every
#: multiple of its period and no residual will ever say so.
MIN_AMBIGUITY_MARGIN = 0.25

#: The share of the matching tolerance by which two candidates' residuals must
#: differ before one is judged better than the other.
_MATERIAL_RMS_FRACTION = 0.01


@dataclass(frozen=True)
class SyncEvent:
    """One raw synchronization event in a source time domain."""

    time: float
    source_id: str
    edge: Edge = "rising"
    label: str = "ttl"


@dataclass(frozen=True)
class SyncFit:
    """Affine target-time fit with auditable quality metrics."""

    offset: float
    drift_ppm: float
    rms_residual: float
    max_residual: float
    matched_count: int
    rejected_count: int
    #: Events offered on each side, so a match *rate* can be stated. The counts
    #: are not recoverable from ``rejected_count``, which sums both sides.
    reference_count: int = 0
    target_count: int = 0
    #: Uncertainty on the offset, not a worst case: ``rms / sqrt(n)``. The
    #: maximum residual is a bound on the worst pair and reads like a ± when it
    #: is printed as one, which is how a hand-typed number came to be reported
    #: as the most confident record in a session.
    offset_stderr: float = 0.0
    #: How much better the winning lag was than the best rival at a materially
    #: different one. 1.0 means nothing else came close; 0.0 means a coin toss.
    ambiguity_margin: float = 1.0
    #: How this mapping was arrived at. Defaults to the affine fit because that
    #: is what every constructor in this module produces; everything that is
    #: not a fit has to say so.
    method: AlignmentMethod = AlignmentMethod.AFFINE

    @property
    def match_rate(self) -> float:
        """Fraction of the reference events that found a partner."""
        if self.reference_count <= 0:
            return 1.0
        return self.matched_count / self.reference_count

    def describe(self) -> str:
        """One line a person can judge, in the terms its method supports.

        Each method gets the numbers that mean something for it. A manual
        mapping is told as a manual mapping rather than dressed in an interval
        it never measured.
        """
        if self.method is AlignmentMethod.MANUAL:
            return f"set by hand: offset {self.offset:+.6f} s, drift {self.drift_ppm:+.3f} ppm"
        if self.method is AlignmentMethod.EXACT:
            return (
                f"exact per-frame mapping over {self.matched_count} frames "
                f"({self.match_rate * 100:.0f}% of the reference paired)"
            )
        if self.method is AlignmentMethod.UNVALIDATED:
            return f"placed by {self.matched_count} events, with none left over to check it against"
        if self.method is AlignmentMethod.SHIFT:
            return (
                f"offset {self.offset:+.6f} s ± {self.offset_stderr * 1000:.3f} ms from "
                f"{self.matched_count} of {self.reference_count} events, no rate fitted"
            )
        return (
            f"offset {self.offset:+.6f} s ± {self.offset_stderr * 1000:.3f} ms and "
            f"{self.drift_ppm:+.3f} ppm, fitted from {self.matched_count} of "
            f"{self.reference_count} events, worst residual "
            f"{self.max_residual * 1000:.3f} ms"
        )

    def to_time_map(self) -> TimeMap:
        """Return the equivalent master-to-target mapping."""
        return TimeMap(offset=self.offset, drift_ppm=self.drift_ppm)


@dataclass(frozen=True)
class ExactSyncFit(SyncFit):
    """Piecewise exact target-time fit that honors nonlinear gaps/drops."""

    exact_master: np.ndarray | None = None
    exact_source: np.ndarray | None = None

    def to_time_map(self) -> TimeMap:
        tm = super().to_time_map()
        if self.exact_master is not None and self.exact_source is not None:
            tm.set_exact_mapping(self.exact_master, self.exact_source)
        return tm


@dataclass(frozen=True)
class SyncMatch:
    """A matched reference and target event, preserving both raw timestamps."""

    reference_time: float
    target_time: float
    residual: float


@dataclass(frozen=True)
class SyncProposal:
    """A deterministic synchronization proposal with bounded display evidence."""

    reference_id: str
    target_id: str
    fit: SyncFit
    matches: tuple[SyncMatch, ...]
    tolerance: float
    unmatched_references: tuple[float, ...] = ()

    @property
    def acceptable(self) -> bool:
        """Whether this proposal is unambiguous and within its fit tolerance.

        Residuals alone cannot answer this. They describe the pairs that were
        matched and are silent about whether those are the right pairs, so a
        degenerate match reports a *smaller* residual than a correct one. The
        match rate and the ambiguity margin are the tests that can fail while
        the residual looks perfect.
        """
        return (
            self.fit.method.is_evidence_based
            and self.fit.matched_count >= 3
            and self.fit.max_residual <= self.tolerance
            and self.fit.match_rate >= MIN_MATCH_RATE
            and self.fit.ambiguity_margin >= MIN_AMBIGUITY_MARGIN
        )

    @property
    def applicable(self) -> bool:
        """Whether the user may apply this, which is not whether it is good.

        A mapping a person typed is applicable and will never be acceptable:
        it has no evidence to be acceptable on. Keeping the two apart is what
        stops a typed number being recorded as a measurement -- collapsing
        them is exactly how `matched_count=3` came to be written by a dialog
        with no events in it at all.
        """
        return self.acceptable or self.fit.method is AlignmentMethod.MANUAL

    @property
    def refusal(self) -> str:
        """Why this proposal cannot be accepted, or "" when it can.

        Said in the terms the user can act on -- which evidence to change --
        rather than as a greyed button with no reason attached.
        """
        fit = self.fit
        if fit.method is AlignmentMethod.MANUAL:
            return ""
        if fit.matched_count < 3:
            return (
                f"Only {fit.matched_count} events matched. Three is the minimum for an "
                "offset and a drift, and it leaves nothing over to check them against."
            )
        if fit.max_residual > self.tolerance:
            return (
                f"The worst pair is {fit.max_residual * 1000:.3f} ms out, past the "
                f"{self.tolerance * 1000:.3f} ms tolerance this fit was judged by."
            )
        if fit.match_rate < MIN_MATCH_RATE:
            return (
                f"Only {fit.match_rate * 100:.0f}% of the reference events found a partner. "
                "A minority matching exactly is the signature of two regular grids meeting "
                "at a wrong rate, not of a noisy alignment."
            )
        if fit.ambiguity_margin < MIN_AMBIGUITY_MARGIN:
            return (
                "Another lag fits almost as well. A uniform pulse train is ambiguous at "
                "every multiple of its period; pick a distinguishable landmark, or give "
                "the fit a manual constraint."
            )
        return ""


def extract_ttl_edges(
    chunks: Iterable[tuple[np.ndarray, np.ndarray]],
    *,
    source_id: str,
    threshold: float = 0.5,
    edge: Edge = "rising",
    min_interval: float = 0.0,
) -> tuple[SyncEvent, ...]:
    """Extract raw TTL transitions from chronological signal chunks.

    Args:
        chunks: One-dimensional ``(time, value)`` chunks in strict time order.
        source_id: Stable identifier of the evidence source.
        threshold: Values at or above this level are logical high.
        edge: Transition direction to emit.
        min_interval: Suppress same-direction bounce transitions closer than this.

    Raises:
        SyncEvidenceError: If chunk shape or chronology makes the evidence unsafe.
    """
    if not source_id:
        raise SyncEvidenceError("Synchronization evidence needs a source identifier.")
    if min_interval < 0:
        raise SyncEvidenceError("min_interval must be non-negative.")

    events: list[SyncEvent] = []
    previous_high: bool | None = None
    previous_time: float | None = None
    last_event_time = -np.inf

    for times, values in chunks:
        times_arr = np.asarray(times, dtype=np.float64)
        values_arr = np.asarray(values)
        if times_arr.ndim != 1 or values_arr.ndim != 1 or len(times_arr) != len(values_arr):
            raise SyncEvidenceError("TTL chunks must be equally sized one-dimensional arrays.")
        if not np.all(np.isfinite(times_arr)):
            raise SyncEvidenceError("TTL event timestamps must be finite.")
        if len(times_arr) and np.any(np.diff(times_arr) <= 0):
            raise SyncEvidenceError("TTL timestamps must be strictly increasing.")
        if previous_time is not None and len(times_arr) and times_arr[0] <= previous_time:
            raise SyncEvidenceError("TTL timestamps must be strictly increasing across chunks.")

        highs = np.asarray(values_arr >= threshold, dtype=bool)
        for time, high in zip(times_arr, highs, strict=True):
            if previous_high is not None:
                is_edge = (edge == "rising" and not previous_high and high) or (
                    edge == "falling" and previous_high and not high
                )
                if is_edge and time - last_event_time >= min_interval:
                    events.append(SyncEvent(float(time), source_id, edge))
                    last_event_time = float(time)
            previous_high = bool(high)
            previous_time = float(time)

    return tuple(events)


def fit_exact_index_mapping(
    reference_times: np.ndarray,
    target_times: np.ndarray,
    *,
    reference_id: str,
    target_id: str,
    index_offset: int = 0,
) -> SyncProposal:
    """Create a deterministic exact index mapping, overriding affine limits.

    Frames are paired exactly 1-to-1 based on index_offset.
    """
    reference = _validated_times(reference_times, "reference")
    target = _validated_times(target_times, "target")

    if reference_id == target_id:
        raise SyncEvidenceError("Reference and target synchronization sources must differ.")

    reference_start = max(index_offset, 0)
    target_start = max(-index_offset, 0)
    length = min(len(reference) - reference_start, len(target) - target_start)
    if length < 2:
        raise SyncEvidenceError("Not enough overlapping frames for an exact index mapping.")

    matched_ref = reference[reference_start : reference_start + length]
    matched_tgt = target[target_start : target_start + length]
    rate_scale = float((matched_tgt[-1] - matched_tgt[0]) / (matched_ref[-1] - matched_ref[0]))
    if not 0.5 <= rate_scale <= 2.0:
        raise SyncEvidenceError(
            "Exact index evidence spans incompatible time ranges; select actual "
            "per-frame trigger timestamps rather than dense signal samples."
        )

    evidence_indices = _evidence_indices(length)
    matches = tuple(
        SyncMatch(float(matched_ref[index]), float(matched_tgt[index]), 0.0)
        for index in evidence_indices
    )

    fit = ExactSyncFit(
        offset=0.0,
        drift_ppm=0.0,
        rms_residual=0.0,
        max_residual=0.0,
        matched_count=length,
        rejected_count=len(reference_times) + len(target_times) - 2 * length,
        reference_count=len(reference),
        target_count=len(target),
        method=AlignmentMethod.EXACT,
        exact_master=matched_ref,
        exact_source=matched_tgt,
    )

    unmatched_values = np.concatenate(
        (reference[:reference_start], reference[reference_start + length :])
    )
    unmatched_references = tuple(
        float(value) for value in unmatched_values[_evidence_indices(len(unmatched_values))]
    )

    return SyncProposal(
        reference_id=reference_id,
        target_id=target_id,
        fit=fit,
        matches=matches,
        tolerance=0.0,
        unmatched_references=unmatched_references,
    )


def _evidence_indices(length: int) -> np.ndarray:
    """Return every small evidence set or an evenly distributed bounded sample."""
    if length <= _MAX_PRESENTED_EVIDENCE:
        return np.arange(length, dtype=np.intp)
    return np.unique(np.linspace(0, length - 1, _MAX_PRESENTED_EVIDENCE, dtype=np.intp))


def fit_sync_events(
    reference_times: np.ndarray,
    target_times: np.ndarray,
    *,
    reference_id: str,
    target_id: str,
    min_pairs: int = 3,
    max_residual: float | None = None,
) -> SyncProposal:
    """Fit a deterministic affine target-time mapping from event timestamps.

    A bounded set of sequence offsets is evaluated, then each candidate is
    refined with least squares.  This handles missing pulses and a modest number
    of spurious edges without reordering either source.  Equal-quality sequence
    offsets are rejected as ambiguous instead of guessed.
    """
    reference = _validated_times(reference_times, "reference")
    target = _validated_times(target_times, "target")
    if reference_id == target_id:
        raise SyncEvidenceError("Reference and target synchronization sources must differ.")
    if min_pairs < 3:
        raise SyncEvidenceError("At least three matched events are required for drift fitting.")
    if len(reference) < min_pairs or len(target) < min_pairs:
        raise SyncEvidenceError(f"At least {min_pairs} events are required in both sources.")

    scale = _initial_scale(reference, target)
    tolerance = max_residual if max_residual is not None else _default_tolerance(reference, target)
    if tolerance <= 0 or not np.isfinite(tolerance):
        raise SyncEvidenceError("Synchronization residual tolerance must be finite and positive.")

    evidence_span = float(reference[-1] - reference[0])
    candidates: list[tuple[np.ndarray, float, float, float]] = []
    implausible: list[tuple[int, float]] = []
    for seed_scale in _seed_scales(scale):
        for ref_index, target_index in _candidate_indices(len(reference), len(target)):
            offset = target[target_index] - seed_scale * reference[ref_index]
            pairs = _match_pairs(reference, target, seed_scale, offset, tolerance)
            if len(pairs) < min_pairs:
                continue
            fitted_scale, fitted_offset = _fit_affine(reference[pairs[:, 0]], target[pairs[:, 1]])
            pairs = _match_pairs(reference, target, fitted_scale, fitted_offset, tolerance)
            if len(pairs) < min_pairs:
                continue
            fitted_scale, fitted_offset = _fit_affine(reference[pairs[:, 0]], target[pairs[:, 1]])
            # The plausible-rate bound is a search constraint, not only a check
            # on the winner. A wrong-scale local optimum can match a *longer*
            # run of events than the truth -- 27 pairs at 0.93 against 40 at
            # 1.0, in the case that found this -- and would otherwise out-vote
            # it on count before anything looked at the rate at all.
            if _rate_is_implausible(fitted_scale, evidence_span, tolerance):
                implausible.append((len(pairs), fitted_scale))
                continue
            residuals = target[pairs[:, 1]] - (
                fitted_scale * reference[pairs[:, 0]] + fitted_offset
            )
            rms = float(np.sqrt(np.mean(np.square(residuals))))
            candidates.append((pairs, fitted_scale, fitted_offset, rms))

    best_plausible = max((len(item[0]) for item in candidates), default=0)
    if _rate_is_the_diagnosis(implausible, best_plausible):
        worst = max(implausible, key=lambda item: item[0])[1]
        # Not a threshold on quality -- a diagnosis. Clocks do not do this, so
        # the two sides are not both seconds, or the events are not the same
        # events. Saying which is more use than refusing.
        raise SyncEvidenceError(
            f"The alignment that best fits this evidence implies a rate difference of "
            f"{(worst - 1.0) * 1_000_000.0:,.0f} ppm, a factor of {worst:.4g}. Real "
            f"clocks stay within about {MAX_PLAUSIBLE_DRIFT_PPM:.0f} ppm of each "
            "other, so this is a unit or sample-index mismatch, or dense signal "
            "samples being used where per-event timestamps are needed -- not a "
            "clock difference."
        )

    if not candidates:
        raise SyncEvidenceError("No event alignment satisfies the residual tolerance.")

    candidates.sort(key=lambda item: (-len(item[0]), item[3], item[2]))
    best_pairs, best_scale, best_offset, best_rms = candidates[0]

    margin = _ambiguity_margin(candidates, tolerance)
    if margin < MIN_AMBIGUITY_MARGIN:
        raise SyncAmbiguityError(
            "This alignment is ambiguous: another sequence offset matches as many "
            f"events almost as well (margin {margin:.2f}). A uniform pulse train "
            "fits at every multiple of its period, and no residual can tell them "
            "apart; choose a manual constraint or a distinguishable landmark."
        )

    drift_ppm = (best_scale - 1.0) * 1_000_000.0
    residuals = target[best_pairs[:, 1]] - (best_scale * reference[best_pairs[:, 0]] + best_offset)
    matches = tuple(
        SyncMatch(
            reference_time=float(reference[ref_idx]),
            target_time=float(target[target_idx]),
            residual=float(residual),
        )
        for (ref_idx, target_idx), residual in zip(best_pairs, residuals, strict=True)
    )
    rms = float(np.sqrt(np.mean(np.square(residuals))))
    fit = SyncFit(
        offset=float(best_offset),
        drift_ppm=float(drift_ppm),
        rms_residual=rms,
        max_residual=float(np.max(np.abs(residuals))),
        matched_count=len(matches),
        rejected_count=len(reference) + len(target) - 2 * len(matches),
        reference_count=len(reference),
        target_count=len(target),
        offset_stderr=rms / np.sqrt(len(matches)) if len(matches) else 0.0,
        ambiguity_margin=margin,
    )
    matched_indices = set(best_pairs[:, 0])
    unmatched_references = tuple(
        float(reference[i]) for i in range(len(reference)) if i not in matched_indices
    )
    return SyncProposal(
        reference_id, target_id, fit, matches, float(tolerance), unmatched_references
    )


def _validated_times(times: np.ndarray, name: str) -> np.ndarray:
    values = np.asarray(times, dtype=np.float64)
    if values.ndim != 1 or not np.all(np.isfinite(values)):
        raise SyncEvidenceError(
            f"{name.capitalize()} events must be a finite one-dimensional array."
        )
    if np.any(np.diff(values) <= 0):
        raise SyncEvidenceError(
            f"{name.capitalize()} event timestamps must be strictly increasing."
        )
    return values


def _rate_is_implausible(scale: float, span: float, tolerance: float) -> bool:
    """Whether a fitted rate is both outside physics and actually measurable.

    Both halves are needed. A rate is only *identifiable* when the divergence
    it implies across the evidence exceeds the tolerance that judged the
    matching: 7,200 ppm over one second is seven milliseconds, which no amount
    of arithmetic distinguishes from jitter, and refusing it would reject an
    ordinary short recording on the strength of a parameter its span cannot
    support. Over four hundred seconds the same ppm is three seconds, and then
    it means something.

    The consequence is worth stating plainly: a drift fitted over a span too
    short to show it is not evidence of a clock, it is the fit absorbing noise
    into a parameter. This gate stops such a fit being *refused*; it does not
    make the number trustworthy, and the model ladder is what should stop it
    being reported at all.
    """
    if abs(scale - 1.0) * 1_000_000.0 <= MAX_PLAUSIBLE_DRIFT_PPM:
        return False
    return abs(scale - 1.0) * span > tolerance


def _rate_is_the_diagnosis(implausible: list[tuple[int, float]], best_plausible: int) -> bool:
    """Whether an impossible rate explains this evidence better than any real one.

    Refusing on the winner's rate alone is not enough: a search seeded at unity
    will usually turn up *some* coincidental handful of pairs at a believable
    rate, and returning that as the answer buries the finding. When a far
    larger set of events lines up at a rate no crystal can produce, that larger
    set is the finding -- the inputs are not two recordings of the same events
    in the same units -- and saying so beats reporting that 1% matched.
    """
    if not implausible:
        return False
    return max(count for count, _ in implausible) > max(best_plausible * 2, 3)


def _seed_scales(estimated: float) -> tuple[float, ...]:
    """Rate seeds to start the search from, most likely first.

    Unity comes first and is always tried. Two recordings of the same events
    differ by a crystal's error, so the truth is within 200 ppm of 1.0 in every
    case this module will accept -- while the median-interval estimate is only
    right when both trains carry the *same* pulses. Hand it a target that
    covers part of the session and the estimate lands percent-wrong, the search
    converges on a local optimum matching a fraction of the events, and that
    fit used to be returned and accepted.
    """
    if abs(estimated - 1.0) <= 1e-9:
        return (1.0,)
    return (1.0, estimated)


def _initial_scale(reference: np.ndarray, target: np.ndarray) -> float:
    reference_dt = np.median(np.diff(reference))
    target_dt = np.median(np.diff(target))
    # Unreachable through the public entry points: `_validated_times` requires
    # strictly increasing timestamps, so every interval is positive and so is
    # their median. Kept as a guard for any future caller that does not
    # validate first, since the alternative is a division by zero.
    if reference_dt <= 0 or target_dt <= 0:  # pragma: no cover
        raise SyncEvidenceError("Synchronization events need positive timestamp intervals.")
    return float(target_dt / reference_dt)


def _default_tolerance(reference: np.ndarray, target: np.ndarray) -> float:
    return float(min(np.median(np.diff(reference)), np.median(np.diff(target))) * 0.25)


def _candidate_indices(reference_count: int, target_count: int) -> Iterator[tuple[int, int]]:
    # A small deterministic lattice finds sequence offsets without turning a
    # long acquisition into an O(n²) UI wait. Refinement uses every event.
    reference_indices = np.linspace(0, reference_count - 1, min(reference_count, 12), dtype=int)
    target_indices = np.linspace(0, target_count - 1, min(target_count, 12), dtype=int)
    for ref_index in reference_indices:
        for target_index in target_indices:
            yield int(ref_index), int(target_index)


def _match_pairs(
    reference: np.ndarray, target: np.ndarray, scale: float, offset: float, tolerance: float
) -> np.ndarray:
    predicted = scale * reference + offset
    right = np.searchsorted(target, predicted)
    left = np.clip(right - 1, 0, len(target) - 1)
    right = np.clip(right, 0, len(target) - 1)
    nearest = np.where(
        np.abs(target[left] - predicted) <= np.abs(target[right] - predicted), left, right
    )
    matched = np.abs(target[nearest] - predicted) <= tolerance
    reference_indices = np.flatnonzero(matched)
    target_indices = nearest[matched]
    if not len(target_indices):
        return np.empty((0, 2), dtype=int)
    unique = np.concatenate(([True], np.diff(target_indices) > 0))
    return np.column_stack((reference_indices[unique], target_indices[unique]))


def _fit_affine(reference: np.ndarray, target: np.ndarray) -> tuple[float, float]:
    slope, offset = np.polyfit(reference, target, 1)
    return float(slope), float(offset)


def _ambiguity_margin(
    candidates: list[tuple[np.ndarray, float, float, float]], tolerance: float
) -> float:
    """How decisively the winning lag beat the best rival at a different lag.

    The guard this replaces asked whether a rival had an identical pair count
    *and* an RMS at or below 1e-9 -- a bit-exact fit. Any real jitter puts the
    RMS above that, so on measured data it never fired, which left the one
    failure mode a residual plot structurally cannot show with no guard at all.

    Two rivals are discounted. One within *tolerance* of the winner's offset is
    the same alignment reached from a different seed. One matching strictly
    fewer events lost on overlap, which is the principled tiebreak every
    implementation of this uses: a lag shifted by one period always leaves an
    event stranded at each end.

    What is left is a rival that matched *as many* events at a materially
    different lag, where only the residual separates the two -- and two regular
    grids meeting at a wrong rate separate by nothing at all. So the margin is
    the winner's fractional advantage in RMS, and 0.0 when it has none.

    This is deliberately a tie detector rather than a full ambiguity analysis.
    The wider failure it used to be asked to catch -- a fit that matched a
    minority of its evidence exactly -- is now :data:`MIN_MATCH_RATE`'s job,
    which measures it directly instead of inferring it from the runners-up.
    """
    best_pairs, _, best_offset, best_rms = candidates[0]
    best_count = len(best_pairs)
    if best_count == 0:
        return 0.0

    for pairs, _, offset, rms in candidates[1:]:
        if abs(offset - best_offset) <= max(tolerance, 1e-9):
            continue
        if len(pairs) < best_count:
            continue
        # Materiality is measured against the tolerance that judged the
        # matching, not against zero. Two exact alignments differ only by
        # float noise -- 1e-17 against 2e-17 is a doubling, and comparing them
        # as a ratio calls that a decisive win.
        if (rms - best_rms) <= tolerance * _MATERIAL_RMS_FRACTION:
            return 0.0
        return float(min(1.0, (rms - best_rms) / rms))
    return 1.0
