"""Performance gate for deterministic TTL/event alignment previews."""

import numpy as np
import pytest

from avialview.core.sync import fit_sync_events

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
