"""Ground-truth tests for exact index synchronization."""

import numpy as np
import pytest

from avialview.core.errors import SyncEvidenceError
from avialview.core.sync import fit_exact_index_mapping


def test_exact_index_mapping_preserves_raw_pairs_and_nonlinear_timestamps() -> None:
    reference = np.array([10.0, 11.0, 12.0, 14.0])
    target = np.array([0.0, 1.1, 2.4, 3.0])

    proposal = fit_exact_index_mapping(
        reference,
        target,
        reference_id="trigger",
        target_id="camera",
    )
    mapping = proposal.fit.to_time_map()

    assert proposal.acceptable
    assert [match.reference_time for match in proposal.matches] == pytest.approx(reference)
    assert [match.target_time for match in proposal.matches] == pytest.approx(target)
    assert mapping.to_source(12.0) == pytest.approx(2.4)
    assert mapping.to_master(2.4) == pytest.approx(12.0)


@pytest.mark.parametrize(
    ("index_offset", "expected_reference", "expected_target", "unmatched"),
    [
        (1, [1.0, 2.0, 3.0], [10.0, 11.0, 12.0], (0.0,)),
        (-1, [0.0, 1.0, 2.0], [11.0, 12.0, 13.0], (3.0,)),
    ],
)
def test_exact_index_offset_records_unmatched_reference_evidence(
    index_offset: int,
    expected_reference: list[float],
    expected_target: list[float],
    unmatched: tuple[float, ...],
) -> None:
    proposal = fit_exact_index_mapping(
        np.arange(4.0),
        np.arange(10.0, 14.0),
        reference_id="trigger",
        target_id="camera",
        index_offset=index_offset,
    )

    assert [match.reference_time for match in proposal.matches] == expected_reference
    assert [match.target_time for match in proposal.matches] == expected_target
    assert proposal.unmatched_references == unmatched


def test_exact_index_rejects_dense_samples_mistaken_for_frame_triggers() -> None:
    with pytest.raises(SyncEvidenceError, match="per-frame trigger timestamps"):
        fit_exact_index_mapping(
            np.linspace(0.0, 0.01, 100),
            np.linspace(0.0, 10.0, 100),
            reference_id="dense signal",
            target_id="camera",
        )


def test_exact_index_mapping_bounds_display_evidence_but_keeps_full_mapping() -> None:
    reference = np.arange(100_000, dtype=np.float64)
    target = reference + 0.002

    proposal = fit_exact_index_mapping(
        reference,
        target,
        reference_id="trigger",
        target_id="camera",
    )

    assert proposal.fit.matched_count == len(reference)
    assert len(proposal.matches) == 500
    assert proposal.matches[0].reference_time == 0.0
    assert proposal.matches[-1].reference_time == 99_999.0
    assert proposal.fit.exact_master is not None
    assert len(proposal.fit.exact_master) == len(reference)
