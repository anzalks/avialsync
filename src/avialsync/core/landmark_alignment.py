"""Fit explicitly paired visual landmarks without inventing correspondence."""

from __future__ import annotations

import dataclasses

import numpy as np

from avialsync.core.drift import drift_from_rate
from avialsync.core.errors import SyncEvidenceError
from avialsync.core.sync import (
    MAX_PLAUSIBLE_DRIFT_MS_PER_HOUR,
    AlignmentMethod,
    SyncFit,
    SyncMatch,
    SyncProposal,
    with_precision,
)


def fit_landmarks(
    reference: np.ndarray,
    target: np.ndarray,
    *,
    reference_id: str,
    target_id: str,
    precision_requirement: float = 0.001,
    observation_resolution: float = 0.033333,
    target_span: tuple[float, float] | None = None,
) -> SyncProposal:
    """Measure a shift or rate from correspondences a person explicitly supplied.

    One pair sets a shift. Two determine a rate with no independent check.
    Three or more leave residuals to inspect; observation resolution remains
    a bound on what those residuals can establish about physical timing.
    """
    master = np.asarray(reference, dtype=np.float64)
    source = np.asarray(target, dtype=np.float64)
    _validate(master, source, reference_id, target_id, observation_resolution)
    scale, offset, drift = _parameters(master, source, observation_resolution)
    count = len(master)
    residuals = source - (master * scale + offset)
    rms = float(np.sqrt(np.mean(residuals**2)))
    fit = SyncFit(
        offset,
        drift,
        rms,
        float(np.max(np.abs(residuals))),
        count,
        0,
        reference_count=count,
        target_count=count,
        offset_stderr=rms / np.sqrt(count),
        method=AlignmentMethod.UNVALIDATED if count < 3 else AlignmentMethod.LANDMARKS,
        measurement_resolution=observation_resolution,
    )
    fit = with_precision(
        fit,
        master,
        source,
        target_span or (float(source[0]), float(source[-1])),
        precision_requirement,
    )
    if count < 3:
        fit = dataclasses.replace(
            fit,
            precision_verified=False,
            precision_shortfall=fit.precision_shortfall
            or f"only {count} visual {'pair' if count == 1 else 'pairs'}, "
            "too few to check the fit against",
        )
    return SyncProposal(
        reference_id,
        target_id,
        fit,
        tuple(
            SyncMatch(float(m), float(s), float(r))
            for m, s, r in zip(master, source, residuals, strict=True)
        ),
        max(observation_resolution, precision_requirement),
        reference_clock_id=reference_id,
    )


def _validate(
    master: np.ndarray,
    source: np.ndarray,
    reference_id: str,
    target_id: str,
    observation_resolution: float,
) -> None:
    if master.ndim != 1 or source.ndim != 1 or not len(master) or len(master) != len(source):
        raise SyncEvidenceError("Add at least one corresponding event on each recording.")
    if not np.all(np.isfinite(master)) or not np.all(np.isfinite(source)):
        raise SyncEvidenceError("Landmark times must be finite.")
    if np.any(np.diff(master) <= 0) or np.any(np.diff(source) <= 0):
        raise SyncEvidenceError("Add pairs in chronological order on both recordings.")
    if reference_id == target_id:
        raise SyncEvidenceError("Choose recordings on different clocks.")
    if not np.isfinite(observation_resolution) or observation_resolution <= 0:
        raise SyncEvidenceError("Observation resolution must be finite and positive.")


def _parameters(
    master: np.ndarray, source: np.ndarray, observation_resolution: float
) -> tuple[float, float, float]:
    count = len(master)
    scale = 1.0
    if count > 1:
        x = master - master[0]
        y = source - source[0]
        scale = float(np.polyfit(x, y, 1)[0])
    drift = drift_from_rate(scale - 1.0)
    span = float(master[-1] - master[0])
    if scale <= 0 or (
        abs(drift) > MAX_PLAUSIBLE_DRIFT_MS_PER_HOUR
        and abs(scale - 1.0) * span > 3.0 * observation_resolution
    ):
        raise SyncEvidenceError(
            "These landmark pairs imply an implausible clock rate; "
            "check the corresponding events and time units."
        )
    offset = float(np.mean(source - scale * master))
    return scale, offset, drift
