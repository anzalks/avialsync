"""Worker-side provenance costs for a shared million-frame exact mapping."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from avialsync.core.timeline import TimeMap
from avialsync.engine.export import _time_maps


def test_bench_exact_mapping_record(benchmark) -> None:
    """Many channels serialize their shared clock once, without changing it."""
    times = np.arange(1_000_000, dtype=np.float64) / 230.0
    mapping = TimeMap()
    mapping.set_exact_mapping(times, times + 0.125)
    readers = [SimpleNamespace(source_id="source.csv", time_map=mapping) for _ in range(128)]

    payload = benchmark.pedantic(_time_maps, args=(readers,), rounds=5, iterations=1)

    assert len(payload) == 1
    saved = payload["source.csv"]
    assert len(saved["master_seconds"]) == len(times)
    restored = TimeMap.from_record(saved)
    assert restored.to_source(1000.0) == mapping.to_source(1000.0)
