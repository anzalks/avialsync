"""Pyramid and cursor-path benchmarks with local engineering budget gates.

Budget-★ items (BLUEPRINT.md / HANDOUT.md):
  - Pyramid build 180 M samples: ≤ 2.5 s
  - Cursor update per tick:       ≤ 2 ms

These are local engineering checks. GitHub Actions verifies the same workload's
correctness but does not claim shared hosted machines can certify runtime speed.

D-029: raw timing is certified locally; hosted CI verifies workload correctness.
"""

import gc
from pathlib import Path

import numpy as np
import pytest

from avialview.core.pyramid import PyramidBuilder, PyramidReader

# Raw dev-machine budgets (seconds) matching BLUEPRINT.md / HANDOUT.md ★ rows
_PYRAMID_BUILD_BUDGET_S = 2.5  # ≤ 2.5 s (D-024)
_PYRAMID_QUERY_BUDGET_S = 0.005  # ≤ 5 ms
_CURSOR_UPDATE_BUDGET_S = 0.002  # ≤ 2 ms
_WINDOW_REFRESH_BUDGET_S = 0.030  # UI work must stay below worker threshold


@pytest.fixture(scope="session")
def large_dataset():
    """Generate 180M samples once per session to save time and memory."""
    N = 180_000_000
    t = np.linspace(0.0, 3600.0, N, dtype=np.float64)
    v = np.sin(t * 10.0)

    # Inject some NaNs and gaps
    v[1000:2000] = np.nan
    t[50000000:50000050] += 10.0

    return t, v


def test_bench_pyramid_build(benchmark, tmp_path: Path, large_dataset):
    """Pyramid build for 180M samples must complete within the ★ budget."""
    t, v = large_dataset

    def setup():
        gc.collect()
        cache_dir = tmp_path / "bench.avialcache"
        cache_dir.mkdir(exist_ok=True)
        builder = PyramidBuilder(cache_dir, "ch0")
        return (builder, t, v), {}

    def do_build(builder, t_arr, v_arr):
        builder.build_and_save(t_arr, v_arr)

    benchmark.pedantic(do_build, setup=setup, rounds=5)

    budget = _PYRAMID_BUILD_BUDGET_S
    stats = benchmark.stats
    if stats is None:
        pytest.skip("benchmark statistics unavailable (benchmarks disabled)")
    assert stats["mean"] <= budget, (
        f"Pyramid build mean {stats['mean']:.3f}s exceeds "
        f"budget {budget:.1f}s. Fix pyramid.py; do not relax the engineering mark."
    )


def test_bench_pyramid_query(benchmark, tmp_path: Path, large_dataset):
    t, v = large_dataset

    cache_dir = tmp_path / "bench_q.avialcache"
    cache_dir.mkdir(exist_ok=True)
    builder = PyramidBuilder(cache_dir, "ch0")
    builder.build_and_save(t, v)

    reader = PyramidReader(cache_dir, "ch0")

    # Query 1 hour of data, but max_points 1000 (so it should pick 4096 decimation level)
    def do_query():
        reader.query(100.0, 3500.0, max_points=1000)

    benchmark(do_query)

    budget = _PYRAMID_QUERY_BUDGET_S
    stats = benchmark.stats
    if stats is None:
        pytest.skip("benchmark statistics unavailable (benchmarks disabled)")
    assert stats["mean"] <= budget, (
        f"Pyramid query mean {stats['mean'] * 1000:.3f}ms exceeds budget {budget * 1000:.1f}ms."
    )


def test_bench_cursor_path(benchmark, tmp_path: Path):
    """Full per-tick cursor path: plot set_cursor + transport set_time + readout
    set_cursor + set_camera_states for 4 cams + 4 channels (★ ≤2ms budget).

    Simulates the hot path that runs every 60 Hz tick in the live UI.  All
    I/O-heavy parts (pyramid loads) are pre-warmed so only the signalling and
    rendering-update path is measured.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    from avialview.ui.plot_pane import PlotPane
    from avialview.ui.readout_panel import ReadoutPanel
    from avialview.ui.transport import Transport

    N = 50_000  # 1 s of 50 kHz data — small enough to build instantly
    N_CAMS = 4
    N_CHANNELS = 4

    # Build N_CHANNELS worth of pyramid data
    readers = []
    for ch_idx in range(N_CHANNELS):
        cache_dir = tmp_path / f"ch{ch_idx}.avialcache"
        cache_dir.mkdir(exist_ok=True)
        t = np.linspace(0.0, 1.0, N, dtype=np.float64)
        v = np.random.default_rng(ch_idx).standard_normal(N)
        PyramidBuilder(cache_dir, f"ch{ch_idx}").build_and_save(t, v)
        r = PyramidReader(cache_dir, f"ch{ch_idx}")
        # Pre-warm mmap
        r._load_level(1)
        r._load_level(4096)
        readers.append(r)

    plot_pane = PlotPane()
    plot_pane.set_timeline_bounds(0.0, 1.0)
    for ch_idx in range(N_CHANNELS):
        plot_pane.load_channels(tmp_path / f"ch{ch_idx}.avialcache", [f"ch{ch_idx}"])
    plot_pane.set_cursor(0.25)
    transport = Transport()
    transport.set_bounds(0.0, 1.0)
    readout = ReadoutPanel()

    # Fake camera states (label, t_pos, fps) for N_CAMS cameras
    camera_states = [(f"cam{i}", 0.5, 30.0) for i in range(N_CAMS)]

    t_cursor = 0.5

    def tick():
        plot_pane.set_cursor(t_cursor)
        transport.set_time(t_cursor)
        readout.set_cursor(t_cursor)
        # show_delta path exercises the camera-states loop
        readout.show_delta(0.3, 0.7, camera_states)

    benchmark(tick)

    budget = _CURSOR_UPDATE_BUDGET_S
    stats = benchmark.stats
    if stats is None:
        pytest.skip("benchmark statistics unavailable (benchmarks disabled)")
    assert stats["mean"] <= budget, (
        f"Cursor update mean {stats['mean'] * 1000:.3f}ms exceeds "
        f"budget {budget * 1000:.1f}ms."
        " See BLUEPRINT.md ★ cursor-update budget."
    )
    plot_pane.close()
    transport.close()
    readout.close()
    plot_pane.deleteLater()
    transport.deleteLater()
    readout.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_bench_four_channel_window_refresh(benchmark, tmp_path: Path):
    """A committed shared-window change stays below the 30 ms UI budget."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    from avialview.ui.plot_pane import PlotPane

    sample_count = 50_000
    pane = PlotPane()
    pane.resize(1000, 600)
    pane.set_timeline_bounds(0.0, 1.0)
    for channel_index in range(4):
        cache_dir = tmp_path / f"window_ch{channel_index}.avialcache"
        cache_dir.mkdir(exist_ok=True)
        times = np.linspace(0.0, 1.0, sample_count, dtype=np.float64)
        values = np.sin(times * (channel_index + 1))
        PyramidBuilder(cache_dir, f"window_ch{channel_index}").build_and_save(times, values)
        pane.load_channels(cache_dir, [f"window_ch{channel_index}"])

    duration = 0.20

    def refresh_window() -> None:
        nonlocal duration
        duration = 0.25 if duration == 0.20 else 0.20
        pane.set_window_duration(duration)

    benchmark(refresh_window)

    stats = benchmark.stats
    if stats is None:
        pytest.skip("benchmark statistics unavailable (benchmarks disabled)")
    assert stats["mean"] <= _WINDOW_REFRESH_BUDGET_S, (
        f"Four-channel window refresh mean {stats['mean'] * 1000:.3f}ms "
        f"exceeds UI budget {_WINDOW_REFRESH_BUDGET_S * 1000:.1f}ms."
    )
    pane.close()
    pane.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
