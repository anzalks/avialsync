"""Large rejected trains never reach pyqtgraph as unbounded scatter arrays."""

from __future__ import annotations

import time

import numpy as np
import pytest

from avialsync.core.sync import SyncFit, SyncMatch, SyncProposal, prepare_display_summary
from avialsync.ui.sync_evidence_view import SyncEvidenceView


@pytest.mark.parametrize("rejected_count", [10_000, 100_000])
def test_rejected_event_display_is_bounded_and_fast(qtbot, rejected_count: int) -> None:
    matched = tuple(
        SyncMatch(float(index * 100), float(index * 100 + 1), 0.0002 * (-1) ** index)
        for index in range(1000)
    )
    rejected = tuple(np.linspace(0.0, 100_000.0, rejected_count).tolist())
    proposal = SyncProposal(
        "DAQ",
        "camera",
        SyncFit(1.0, 0.0, 0.0002, 0.0002, 1000, rejected_count),
        matched,
        0.01,
        rejected,
    )
    prepared = prepare_display_summary(proposal)
    proposal = SyncProposal(
        proposal.reference_id,
        proposal.target_id,
        proposal.fit,
        proposal.matches,
        proposal.tolerance,
        proposal.unmatched_references,
        display=prepared,
    )
    assert len(prepared.rejected_times) <= 800
    assert len(prepared.reference_times) <= 800
    assert np.max(np.abs(prepared.residual_ms)) == pytest.approx(0.2)

    view = SyncEvidenceView()
    qtbot.addWidget(view)
    start = time.perf_counter()
    view.show_proposal(proposal)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.25, f"bounded evidence callback took {elapsed * 1000:.1f} ms"
    assert len(view._plotted_times) <= 800
    assert view._proposal is proposal  # Complete evidence remains inspectable.


def test_the_worst_pair_and_the_whole_span_survive_the_summary(qtbot) -> None:
    """Bounded drawing must not hide the one bad pair, or the evidence's ends."""
    count = 50_000
    times = np.linspace(10.0, 5000.0, count)
    residuals = np.full(count, 0.0001)
    residuals[31_337] = -0.009  # one pair 9 ms out, among fifty thousand clean ones
    matched = tuple(
        SyncMatch(float(t), float(t) + 1.0, float(r)) for t, r in zip(times, residuals, strict=True)
    )
    proposal = SyncProposal(
        "DAQ", "camera", SyncFit(1.0, 0.0, 0.0002, 0.009, count, 0), matched, 0.01, ()
    )
    summary = prepare_display_summary(proposal)

    assert len(summary.reference_times) <= 800
    assert np.min(summary.residual_ms) == pytest.approx(-9.0)
    assert 31_337 in summary.match_indices
    assert summary.span == pytest.approx((0.0, 4990.0))

    view = SyncEvidenceView()
    qtbot.addWidget(view)
    view.show_proposal(
        SyncProposal(
            proposal.reference_id,
            proposal.target_id,
            proposal.fit,
            proposal.matches,
            proposal.tolerance,
            display=summary,
        )
    )
    assert view._nav._home_x == pytest.approx((0.0, 4990.0))
