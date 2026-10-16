"""Performance gate for deterministic TTL/event alignment previews."""

import numpy as np
import pytest

from avialsync.core.sync import fit_sync_events

_FIT_PREVIEW_BUDGET_S = 0.25


def test_bench_sync_fit_preview(benchmark) -> None:
    """A 10,000-event preview must remain interactive and deterministic."""
    reference = np.arange(0.0, 5_000.0, 0.5)
    target = reference + 1.25 + 3.5e-6 * reference

    benchmark(
        fit_sync_events,
        reference,
        target,
        reference_id="sensor:ttl",
        target_id="video:camera",
    )

    budget = _FIT_PREVIEW_BUDGET_S
    stats = benchmark.stats
    if stats is None:
        pytest.skip("benchmark statistics unavailable (benchmarks disabled)")
    assert stats["mean"] <= budget, (
        f"Sync fit preview mean {stats['mean']:.3f}s exceeds budget {budget:.3f}s."
    )


def test_bench_landmark_preview(benchmark) -> None:
    """Explicit correspondences stay within the existing preview budget."""
    from avialsync.core.landmark_alignment import fit_landmarks

    master = np.linspace(0.0, 3600.0, 1000)
    proposal = benchmark(
        fit_landmarks, master, 1.25 + master * 1.000015, reference_id="camera", target_id="sensor"
    )
    assert proposal.fit.matched_count == 1000
    assert benchmark.stats is not None
    assert benchmark.stats["mean"] <= _FIT_PREVIEW_BUDGET_S


def test_bench_adjusted_exact_lookup(benchmark) -> None:
    """A manual correction performs a binary search, independent of array length."""
    from avialsync.core.timeline import TimeMap

    master = np.arange(1_000_000, dtype=np.float64) / 100.0
    mapping = TimeMap()
    mapping.set_exact_mapping(master, master + 0.001 * np.sin(master))
    mapping.adjust_mapping(0.02, 54.0)
    benchmark(mapping.to_source, 1234.5)
    assert benchmark.stats is not None
    assert benchmark.stats["mean"] <= 0.00002
