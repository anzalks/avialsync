"""Ground truth for explicitly paired visual events and their precision limits."""

from typing import Any

import numpy as np
import pytest

from avialsync.core.errors import SyncEvidenceError
from avialsync.core.landmark_alignment import fit_landmarks
from avialsync.core.sync import AlignmentMethod, SyncProposal


def fit(master: list[float], source: list[float], **kwargs: Any) -> SyncProposal:
    return fit_landmarks(
        np.array(master), np.array(source), reference_id="camera", target_id="sensor", **kwargs
    )


def test_one_pair_places_a_recording_without_claiming_validation() -> None:
    proposal = fit([10.0], [12.5])
    assert proposal.fit.offset == 2.5
    assert proposal.applicable and not proposal.acceptable
    assert proposal.fit.method == AlignmentMethod.UNVALIDATED
    assert not proposal.fit.precision_verified


def test_two_separated_pairs_recover_known_rate_but_remain_unverified() -> None:
    proposal = fit([0.0, 600.0], [1.25, 601.28])
    assert proposal.fit.offset == pytest.approx(1.25)
    assert proposal.fit.drift_ms_per_hour == pytest.approx(180.0)
    assert not proposal.fit.precision_verified


def test_extra_pairs_expose_observation_resolution_even_with_perfect_residuals() -> None:
    proposal = fit([0.0, 10.0, 20.0, 30.0], [1.0, 11.0, 21.0, 31.0], observation_resolution=0.01)
    assert proposal.fit.method == AlignmentMethod.LANDMARKS
    assert proposal.acceptable
    assert not proposal.fit.precision_verified


def test_reversed_correspondences_are_refused() -> None:
    with pytest.raises(SyncEvidenceError, match="chronological"):
        fit([1.0, 2.0], [2.0, 1.0])
