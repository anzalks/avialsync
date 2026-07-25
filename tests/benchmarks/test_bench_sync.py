"""Performance gate for deterministic TTL/event alignment previews."""

import os

import numpy as np

from kinochronix.core.sync import fit_sync_events

CI_BUDGET_MULTIPLIER = 1.5
_ACTUAL_MULTIPLIER = CI_BUDGET_MULTIPLIER if os.environ.get("CI") == "true" else 1.0
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

    budget = _FIT_PREVIEW_BUDGET_S * _ACTUAL_MULTIPLIER
    assert benchmark.stats["mean"] <= budget, (
        f"Sync fit preview mean {benchmark.stats['mean']:.3f}s exceeds "
        f"budget {budget:.3f}s (dev={_FIT_PREVIEW_BUDGET_S:.3f}s × {_ACTUAL_MULTIPLIER}×)."
    )
