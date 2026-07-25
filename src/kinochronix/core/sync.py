"""Headless evidence-based synchronization primitives.

The functions in this module preserve source timestamps.  They only propose an
affine mapping from master/reference time to a target source; the UI is
responsible for showing the evidence and obtaining user acceptance.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Literal

import numpy as np

from kinochronix.core.errors import SyncAmbiguityError, SyncEvidenceError
from kinochronix.core.timeline import TimeMap

Edge = Literal["rising", "falling"]


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

    def to_time_map(self) -> TimeMap:
        """Return the equivalent master-to-target mapping."""
        return TimeMap(offset=self.offset, drift_ppm=self.drift_ppm)


@dataclass(frozen=True)
class SyncMatch:
    """A matched reference and target event, preserving both raw timestamps."""

    reference_time: float
    target_time: float
    residual: float


@dataclass(frozen=True)
class SyncProposal:
    """A deterministic, inspectable synchronization proposal."""

    reference_id: str
    target_id: str
    fit: SyncFit
    matches: tuple[SyncMatch, ...]
    tolerance: float

    @property
    def acceptable(self) -> bool:
        """Whether this proposal is unambiguous and within its fit tolerance."""
        return self.fit.matched_count >= 3 and self.fit.max_residual <= self.tolerance


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

    candidates: list[tuple[np.ndarray, float, float, float]] = []
    for ref_index, target_index in _candidate_indices(len(reference), len(target)):
        offset = target[target_index] - scale * reference[ref_index]
        pairs = _match_pairs(reference, target, scale, offset, tolerance)
        if len(pairs) < min_pairs:
            continue
        fitted_scale, fitted_offset = _fit_affine(reference[pairs[:, 0]], target[pairs[:, 1]])
        pairs = _match_pairs(reference, target, fitted_scale, fitted_offset, tolerance)
        if len(pairs) < min_pairs:
            continue
        fitted_scale, fitted_offset = _fit_affine(reference[pairs[:, 0]], target[pairs[:, 1]])
        residuals = target[pairs[:, 1]] - (fitted_scale * reference[pairs[:, 0]] + fitted_offset)
        rms = float(np.sqrt(np.mean(np.square(residuals))))
        candidates.append((pairs, fitted_scale, fitted_offset, rms))

    if not candidates:
        raise SyncEvidenceError("No event alignment satisfies the residual tolerance.")

    candidates.sort(key=lambda item: (-len(item[0]), item[3], item[2]))
    best_pairs, best_scale, best_offset, _ = candidates[0]
    if _is_ambiguous(candidates, best_pairs, best_offset):
        raise SyncAmbiguityError(
            "Synchronization alignment is ambiguous; choose a manual constraint."
        )

    residuals = target[best_pairs[:, 1]] - (best_scale * reference[best_pairs[:, 0]] + best_offset)
    matches = tuple(
        SyncMatch(
            reference_time=float(reference[ref_idx]),
            target_time=float(target[target_idx]),
            residual=float(residual),
        )
        for (ref_idx, target_idx), residual in zip(best_pairs, residuals, strict=True)
    )
    fit = SyncFit(
        offset=float(best_offset),
        drift_ppm=float((best_scale - 1.0) * 1_000_000.0),
        rms_residual=float(np.sqrt(np.mean(np.square(residuals)))),
        max_residual=float(np.max(np.abs(residuals))),
        matched_count=len(matches),
        rejected_count=len(reference) + len(target) - 2 * len(matches),
    )
    return SyncProposal(reference_id, target_id, fit, matches, float(tolerance))


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


def _initial_scale(reference: np.ndarray, target: np.ndarray) -> float:
    reference_dt = np.median(np.diff(reference))
    target_dt = np.median(np.diff(target))
    if reference_dt <= 0 or target_dt <= 0:
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


def _is_ambiguous(
    candidates: list[tuple[np.ndarray, float, float, float]],
    best_pairs: np.ndarray,
    best_offset: float,
) -> bool:
    for pairs, _, offset, rms in candidates[1:]:
        if len(pairs) != len(best_pairs):
            return False
        if abs(offset - best_offset) > 1e-9 and rms <= 1e-9:
            return True
    return False
