"""Performance gates for timestamp-mapped multi-video command dispatch."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import numpy as np
import pytest

from avialsync.core.timeline import TimeMap
from avialsync.engine.seeker import SeekGroup
from avialsync.ui.video_pane import VideoPane


class _FastPane:
    def __init__(self, mapping: TimeMap) -> None:
        self.has_media = True
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

    if benchmark.stats is None:
        pytest.skip("benchmark statistics unavailable (benchmarks disabled)")
    assert benchmark.stats.stats.mean < 0.002


def test_bench_four_video_callback_bursts_are_coalesced(benchmark) -> None:
    """Four 120-frame callback bursts must stay far below one UI tick."""
    signal = SimpleNamespace(emit=lambda: None)
    panes = [
        SimpleNamespace(
            _osd_lock=threading.Lock(),
            _pending_osd=(0.0, 0.0),
            _osd_event_pending=False,
            _osd_update=signal,
        )
        for _ in range(4)
    ]

    def callback_burst() -> None:
        for pane in panes:
            pane._osd_event_pending = False
            for frame in range(120):
                VideoPane._queue_osd_update(pane, frame / 60.0, 60.0)

    benchmark(callback_burst)

    if benchmark.stats is None:
        pytest.skip("benchmark statistics unavailable (benchmarks disabled)")
    assert benchmark.stats.stats.mean < 0.002


def test_bench_frame_step_target_across_four_aligned_camera_clocks(benchmark) -> None:
    """Choosing an exact neighbouring frame stays within the 2 ms command budget."""
    from avialsync.engine.player import Player
    from avialsync.ui.video_timing import VideoTimingMixin

    class TimedPane(VideoTimingMixin):
        def __init__(self, rate: int, shift: float) -> None:
            self._frame_times = np.arange(3600 * rate + 1, dtype=np.float64) / rate
            self.time_map = TimeMap()
            self.time_map.set_exact_mapping(self._frame_times + shift, self._frame_times)

    panes = [TimedPane(rate, index * 0.001) for index, rate in enumerate((30, 60, 120, 230))]
    state = SimpleNamespace(t=1800.0)
    player = SimpleNamespace(clock=SimpleNamespace(state=state), step_reference=None)
    expected = min(pane.frame_step_master_target(state.t, 1) for pane in panes)

    target = benchmark(Player._frame_step_target, player, panes, 1)

    assert target == pytest.approx(expected) and target > state.t
    if benchmark.stats is None:
        pytest.skip("benchmark statistics unavailable (benchmarks disabled)")
    assert benchmark.stats.stats.mean < 0.002
