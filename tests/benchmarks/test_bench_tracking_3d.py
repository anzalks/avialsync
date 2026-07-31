"""Performance guard for the 3D tracking cursor hot path."""

from pathlib import Path

import numpy as np
import pytest

from avialview.ui.tracking_3d_pane import Tracking3DPane

_CURSOR_BUDGET_S = 0.002


class _ArrayReader:
    """Minimal mmap-reader equivalent for isolating per-tick sampling cost."""

    def __init__(
        self,
        cache_dir: Path,
        channel_id: str,
        times: np.ndarray,
        values: np.ndarray,
    ) -> None:
        self.cache_dir = cache_dir
        self.channel_id = channel_id
        self._level = (times, values, values, np.zeros(len(times), dtype=bool))

    def _load_level(self, _level: int):
        return self._level

    def mapped_columns(self):
        return self._level[:3]


def test_bench_tracking_3d_cursor(benchmark, qapp, tmp_path: Path) -> None:
    """Sampling 128 XYZ points must leave room in the existing cursor budget."""
    times = np.linspace(0.0, 10.0, 3_001)
    readers = []
    for point_index in range(128):
        for axis_index, axis in enumerate("xyz"):
            values = np.sin(times + point_index + axis_index)
            readers.append(
                _ArrayReader(
                    tmp_path / "tracking.avialcache",
                    f"point_{point_index}_{axis}",
                    times,
                    values,
                )
            )

    pane = Tracking3DPane()
    pane.set_readers(readers)
    benchmark(pane.set_cursor, 5.0)

    stats = benchmark.stats
    if stats is None:
        pytest.skip("benchmark statistics unavailable (benchmarks disabled)")
    assert stats["mean"] <= _CURSOR_BUDGET_S, (
        f"3D cursor mean {stats['mean'] * 1000:.3f}ms exceeds {_CURSOR_BUDGET_S * 1000:.1f}ms."
    )
