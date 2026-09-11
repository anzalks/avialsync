"""Choosing the alignment model the evidence can actually support.

The model is not a preference. It is decided by what was recorded and by how
long the recording ran, and offering it as a dropdown asks the user to certify
something only the data knows. The ladder, strongest first:

1. **Exact** -- a frame strobe whose count agrees with the container. One pulse
   per exposure that happened, paired one to one. No parameters, so no
   residuals: its confidence is the count agreement.
2. **Piecewise** -- a shared sync train, linearly interpolated between
   consecutive matched edges. This is SpikeGLX's TPrime model and it is the
   answer to unpredictable drift: whatever the clocks do between two edges,
   the mapping follows them at every edge.
3. **Affine** -- offset and rate fitted from matched events, where the span is
   long enough for a rate to mean anything.
4. **Shift** -- offset alone. Either the span cannot support a rate or the
   residuals show no trend worth a second parameter.
5. **Unvalidated** -- two events. The offset is determined and there is nothing
   left over to check it with, which is a different state from a good fit and
   is recorded as one.

Escalation is residual-driven and upward only. Fit the cheapest model, read
the *structure* of what is left, and add a parameter only when the structure
says the current model did not absorb something. A drift fitted over a span too
short to show it is not a clock measurement; it is noise in a parameter, and
:func:`drift_is_identifiable` is what keeps it out.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from avialsync.core.errors import SyncEvidenceError
from avialsync.core.sync import (
    AlignmentMethod,
    ExactSyncFit,
    SyncFit,
    SyncMatch,
    SyncProposal,
    fit_sync_events,
)
from avialsync.core.triggers import Reconciliation, TriggerKind

__all__ = [
    "MIN_PIECEWISE_KNOTS",
    "choose_method",
    "demote_to_shift",
    "drift_is_identifiable",
    "fit_piecewise",
    "residual_trend",
]

#: No rate is called real on a divergence below this, whatever the residuals
#: say. A fit whose scatter is numerically zero -- synthetic data, or an exact
#: mapping -- would otherwise make any rate at all "identifiable", including one
#: that is the last few bits of a float.
_IDENTIFIABILITY_FLOOR_S = 1e-6

#: Below this many matched edges, interpolating between them is a straight line
#: with extra steps -- and a straight line is what the affine model already is,
#: fitted with every point instead of two.
MIN_PIECEWISE_KNOTS = 4


def drift_is_identifiable(drift_ppm: float, span: float, noise: float) -> bool:
    """Whether a rate difference is large enough, over this span, to be measured.

    Two things decide it. The span, because 7,200 ppm across one second is
    seven milliseconds while across four hundred seconds it is three; and the
    scatter it has to stand out from, because a divergence smaller than the
    fit's own residuals is not a measurement of anything.

    *noise* is the fit's RMS residual where one exists, and the matching
    tolerance only where no fit has happened yet. Judging against the tolerance
    is the weaker test and was the wrong one here: that number is a quarter of
    the pulse interval, so a 1 Hz sync train sets it to 250 ms and would bury a
    genuine 60 ppm over twenty minutes -- forty-eight milliseconds of real
    divergence, against residuals measured in picoseconds.

    Three times the scatter, which is the usual bar for calling a term real
    rather than a fluctuation.
    """
    if span <= 0:
        return False
    divergence = abs(drift_ppm) * 1e-6 * span
    return divergence > max(3.0 * noise, _IDENTIFIABILITY_FLOOR_S)


def residual_trend(times: np.ndarray, residuals: np.ndarray) -> float:
    """Total drift in the residuals across the evidence, in the residual's units.

    What a mean hides. A model that has absorbed everything leaves residuals
    with no slope; one that has not leaves a ramp, and the ramp is the argument
    for the next parameter up.
    """
    values = np.asarray(times, dtype=np.float64)
    left = np.asarray(residuals, dtype=np.float64)
    if len(values) < 3 or len(values) != len(left):
        return 0.0
    span = float(values[-1] - values[0])
    if span <= 0:
        return 0.0
    slope = float(np.polyfit(values - values[0], left, 1)[0])
    return abs(slope) * span


def choose_method(
    kind: TriggerKind,
    *,
    reconciliation: Reconciliation | None,
    matched_count: int,
    span: float,
    drift_ppm: float,
    noise: float,
) -> AlignmentMethod:
    """The strongest model this evidence supports, never a stronger one.

    Args:
        kind: What the reference train is evidence of.
        reconciliation: Pulse and frame counts, where both are known.
        matched_count: Events paired between the two sources.
        span: Seconds covered by the evidence.
        drift_ppm: Rate difference a free fit would report.
        noise: Scatter the rate must stand out from -- the fit's RMS residual.
    """
    if matched_count < 2:
        raise SyncEvidenceError("An alignment needs at least two matched events.")
    if matched_count == 2:
        # Two points determine a line and leave no residual. That is not a
        # perfect fit, it is an unchecked one, and the difference matters.
        return AlignmentMethod.UNVALIDATED

    if reconciliation is not None and reconciliation.exact_mapping_is_safe:
        return AlignmentMethod.EXACT

    if kind is TriggerKind.SYNC_TRAIN and matched_count >= MIN_PIECEWISE_KNOTS:
        # Whatever the clocks did between two edges, the mapping followed them
        # at every edge. No single rate has to be true for the whole recording.
        return AlignmentMethod.PIECEWISE

    if drift_is_identifiable(drift_ppm, span, noise):
        return AlignmentMethod.AFFINE
    return AlignmentMethod.SHIFT


def fit_piecewise(
    reference_times: np.ndarray,
    target_times: np.ndarray,
    *,
    reference_id: str,
    target_id: str,
    tolerance: float | None = None,
) -> SyncProposal:
    """Interpolate linearly between matched sync edges, TPrime's model.

    The affine fit asks one rate to be true for the whole recording. Two
    independent oscillators in a room that warms up do not oblige: they wander,
    and the wander is not a line. Between consecutive matched edges a line is
    all that is needed, and across the recording the mapping is whatever the
    edges say it was.

    The matching itself is delegated to the affine search, so every guard there
    -- match rate, ambiguity margin, plausible rate -- applies before any
    interpolation happens. What changes is what is done with the pairs once
    they are trusted.
    """
    affine = fit_sync_events(
        reference_times,
        target_times,
        reference_id=reference_id,
        target_id=target_id,
        max_residual=tolerance,
    )
    if len(affine.matches) < MIN_PIECEWISE_KNOTS:
        raise SyncEvidenceError(
            f"A piecewise mapping needs at least {MIN_PIECEWISE_KNOTS} matched edges to "
            f"interpolate between; this evidence matched {len(affine.matches)}. Below that "
            "it is a straight line with extra steps, and the affine fit is that line "
            "computed from every point."
        )

    master = np.asarray([match.reference_time for match in affine.matches], dtype=np.float64)
    source = np.asarray([match.target_time for match in affine.matches], dtype=np.float64)
    if np.any(np.diff(master) <= 0) or np.any(np.diff(source) <= 0):
        raise SyncEvidenceError(
            "Matched sync edges must be strictly increasing on both sides to interpolate "
            "between them."
        )

    # Residuals are zero at every knot by construction -- that is what
    # interpolation means -- so the quality of this mapping is not in its
    # residuals. It is in how far apart the knots are, which `coverage` and the
    # match rate carried over from the affine search both speak to.
    fit = ExactSyncFit(
        offset=float(source[0] - master[0]),
        drift_ppm=affine.fit.drift_ppm,
        rms_residual=0.0,
        max_residual=0.0,
        matched_count=len(affine.matches),
        rejected_count=affine.fit.rejected_count,
        reference_count=affine.fit.reference_count,
        target_count=affine.fit.target_count,
        offset_stderr=affine.fit.offset_stderr,
        ambiguity_margin=affine.fit.ambiguity_margin,
        method=AlignmentMethod.PIECEWISE,
        exact_master=master,
        exact_source=source,
    )
    matches = tuple(SyncMatch(float(m), float(s), 0.0) for m, s in zip(master, source, strict=True))
    return SyncProposal(
        reference_id=reference_id,
        target_id=target_id,
        fit=fit,
        matches=matches,
        tolerance=affine.tolerance,
        unmatched_references=affine.unmatched_references,
    )


def demote_to_shift(fit: SyncFit) -> SyncFit:
    """Drop a rate the span could not resolve, rather than reporting it.

    Called when :func:`choose_method` settles on SHIFT after an affine search
    has already produced a number. The offset is kept -- it is measured -- and
    the rate is set aside rather than quoted to three decimal places from a
    span that cannot support one digit.
    """
    return dataclasses.replace(fit, drift_ppm=0.0, method=AlignmentMethod.SHIFT)
