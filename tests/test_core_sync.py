"""Ground-truth tests for headless TTL/event synchronization."""

import numpy as np
import pytest

from kinochronix.core.errors import SyncAmbiguityError, SyncEvidenceError
from kinochronix.core.sync import extract_ttl_edges, fit_sync_events


def test_extract_ttl_edges_preserves_chunk_boundaries() -> None:
    """A rising edge split between chunks is emitted exactly once at its raw time."""
    chunks = iter(
        [
            (np.array([0.0, 0.1, 0.2]), np.array([0.0, 0.0, 0.0])),
            (np.array([0.3, 0.4, 0.5]), np.array([1.0, 1.0, 0.0])),
        ]
    )

    events = extract_ttl_edges(chunks, source_id="sensor", threshold=0.5)

    assert [event.time for event in events] == [0.3]
    assert events[0].source_id == "sensor"
    assert events[0].edge == "rising"


def test_extract_ttl_edges_rejects_non_monotonic_chunk_stream() -> None:
    """Unsound event evidence must never be silently reordered."""
    chunks = iter(
        [
            (np.array([0.0, 0.2]), np.array([0.0, 1.0])),
            (np.array([0.15, 0.3]), np.array([0.0, 1.0])),
        ]
    )

    with pytest.raises(SyncEvidenceError, match="strictly increasing"):
        extract_ttl_edges(chunks, source_id="sensor")


def test_fit_recovers_known_offset_and_drift_with_missing_pulses() -> None:
    """Periodic TTLs recover the known mapping despite dropped target pulses."""
    master = np.arange(0.0, 300.0, 0.5)
    source = master + 1.25 + 3.5e-6 * master
    source = np.delete(source, [10, 11, 250, 475])

    proposal = fit_sync_events(master, source, reference_id="camera", target_id="ephys")

    assert proposal.acceptable
    assert proposal.fit.offset == pytest.approx(1.25, abs=1e-6)
    assert proposal.fit.drift_ppm == pytest.approx(3.5, abs=1e-5)
    assert proposal.fit.matched_count == len(source)
    assert proposal.fit.rejected_count == 4


def test_fit_rejects_spurious_target_edge() -> None:
    """A single implausible edge is excluded and recorded as rejected evidence."""
    master = np.arange(0.0, 30.0, 1.0)
    source = master + 0.75
    source = np.insert(source, 12, 12.12)

    proposal = fit_sync_events(master, source, reference_id="camera", target_id="sensor")

    assert proposal.acceptable
    assert proposal.fit.offset == pytest.approx(0.75, abs=1e-9)
    assert proposal.fit.matched_count == len(master)
    assert proposal.fit.rejected_count == 1


def test_fit_refuses_ambiguous_periodic_alignment() -> None:
    """Equal-quality periodic shifts require a user constraint, never auto-acceptance."""
    with pytest.raises(SyncAmbiguityError, match="ambiguous"):
        fit_sync_events(
            np.array([0.0, 1.0, 2.0]),
            np.array([0.0, 1.0, 2.0, 3.0]),
            reference_id="camera",
            target_id="sensor",
        )
