"""Performance gates for timestamp-mapped multi-video command dispatch."""

from __future__ import annotations

import numpy as np

from avialview.core.timeline import TimeMap
from avialview.engine.seeker import SeekGroup


class _FastPane:
    def __init__(self, mapping: TimeMap) -> None:
        self.mpv = object()
        self.time_map = mapping
        self.targets: list[tuple[float, bool]] = []

    def seek(self, target: float, exact: bool = True) -> None:
        self.targets.clear()
        self.targets.append((target, exact))


def test_bench_four_video_exact_mapping_dispatch(benchmark) -> None:
    """Application-side fanout must be negligible beside the 250 ms decode budget."""
    master = np.linspace(0.0, 3_600.0, 108_001, dtype=np.float64)
    panes = []
    for index in range(4):
        mapping = TimeMap()
        mapping.set_exact_mapping(master, master + index * 0.001)
        panes.append(_FastPane(mapping))
    seeker = SeekGroup(panes)

    benchmark(seeker.seek, 1_800.123, True)

    assert benchmark.stats.stats.mean < 0.002
