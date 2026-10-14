"""Malformed or incomplete clock evidence never becomes an accepted mapping."""

from dataclasses import replace

import numpy as np
import pytest

from avialsync.core import sync, triggers
from avialsync.core.errors import SyncEvidenceError
from avialsync.core.sync import AlignmentMethod, ExactSyncFit, SyncFit, SyncProposal
from avialsync.core.triggers import TriggerKind


@pytest.mark.parametrize("extract", [sync.extract_ttl_edges, triggers.extract_pulses])
@pytest.mark.parametrize(
    "chunks",
    [
        [(np.array([[0.0, 1.0]]), np.zeros(2))],
        [(np.array([0.0, np.nan]), np.zeros(2))],
        [(np.array([1.0, 0.0]), np.zeros(2))],
        [(np.array([0.0, 1.0]), np.zeros(2)), (np.array([1.0, 2.0]), np.zeros(2))],
    ],
)
def test_invalid_chunk_evidence_is_rejected(extract, chunks) -> None:
    kwargs = {"source_id": "clock"}
    if extract is triggers.extract_pulses:
        kwargs["kind"] = TriggerKind.FRAME_STROBE
    with pytest.raises(SyncEvidenceError):
        extract(chunks, **kwargs)


def test_invalid_pulse_configuration_and_gap_shape_are_rejected() -> None:
    for options in ({"source_id": ""}, {"source_id": "clock", "min_interval": -1}):
        with pytest.raises(SyncEvidenceError):
            triggers.extract_pulses([], kind=TriggerKind.FRAME_STROBE, **options)
    with pytest.raises(SyncEvidenceError, match="gap masks"):
        triggers.extract_pulses(
            [(np.arange(2), np.zeros(2), np.zeros(1))],
            source_id="clock",
            kind=TriggerKind.FRAME_STROBE,
        )
    with pytest.raises(SyncEvidenceError):
        sync.extract_ttl_edges([], source_id="clock", min_interval=-1)
    assert triggers.locate_drops(np.array([2.0, 1.0, 0.0])) == ()


def test_empty_and_low_count_fit_summaries_never_claim_evidence() -> None:
    fit = SyncFit(0, 0, 0, 0, 0, 0, reference_count=0)
    assert fit.match_rate == 1
    proposal = SyncProposal("reference", "target", fit, (), 0.01)
    assert not proposal.acceptable and "Only 0" in proposal.refusal
    assert "none left over" in replace(fit, method=AlignmentMethod.UNVALIDATED).describe()
    assert "precision not assessed" in fit.describe()
    residual = replace(fit, matched_count=3, reference_count=3, max_residual=1)
    assert "worst pair" in replace(proposal, fit=residual).refusal
    good = replace(residual, max_residual=0, ambiguity_margin=1)
    assert replace(proposal, fit=good).refusal == ""


def test_exact_fit_without_arrays_retains_only_its_affine_mapping() -> None:
    fit = ExactSyncFit(2, 0, 0, 0, 0, 0)
    assert fit.to_time_map().to_source(3) == 5


@pytest.mark.parametrize("precision", [0, -1, np.nan])
def test_invalid_precision_is_rejected_by_both_public_fit_paths(precision: float) -> None:
    fit = SyncFit(0, 0, 0, 0, 3, 0)
    values = np.array([0.0, 1.2, 2.5])
    with pytest.raises(SyncEvidenceError, match="Precision"):
        sync.with_precision(fit, values, values, (0, 3), precision)
    with pytest.raises(SyncEvidenceError, match="Precision"):
        sync.fit_sync_events(
            values, values, reference_id="a", target_id="b", precision_requirement=precision
        )


def test_cancelled_fit_has_no_proposal_and_empty_candidates_have_no_margin() -> None:
    values = np.array([0.0, 1.2, 2.5])
    with pytest.raises(SyncEvidenceError, match="cancelled"):
        sync.fit_sync_events(
            values, values, reference_id="a", target_id="b", is_cancelled=lambda: True
        )
    assert sync._ambiguity_margin([(np.empty((0, 2), dtype=int), 1, 0, 0)], 0.01) == 0
