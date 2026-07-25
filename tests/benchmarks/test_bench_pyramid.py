"""Pyramid and cursor-path benchmarks with CI-enforced budget gates.

Budget-★ items (BLUEPRINT.md / HANDOUT.md):
  - Pyramid build 180 M samples: ≤ 2.5 s  (★ CI-gated)
  - Cursor update per tick:       ≤ 2 ms (★ CI-gated)

CI runners are typically slower than dev machines.  All budgets are
multiplied by CI_BUDGET_MULTIPLIER (defined below) so the assertion
threshold is CI_BUDGET_MULTIPLIER × dev budget.  The multiplier is applied
uniformly — never per-test — to avoid hidden fudge factors.

D-023: benchmarks are CI-gated, budget-assertion pattern established here.
"""

import gc
import os
from pathlib import Path

import numpy as np
import pytest

from avialview.core.pyramid import PyramidBuilder, PyramidReader

# ── CI budget multiplier (D-023) ────────────────────────────────────────────
# CI GitHub Actions runners are significantly slower than developer machines
# (shared CPU, memory pressure, different disk speeds).
# NEVER add per-test multipliers — only adjust this constant, and note the
# change in DECISIONS.md.
CI_BUDGET_MULTIPLIER = 1.5
_ACTUAL_MULTIPLIER = CI_BUDGET_MULTIPLIER if os.environ.get("CI") == "true" else 1.0

# Raw dev-machine budgets (seconds) matching BLUEPRINT.md / HANDOUT.md ★ rows
_PYRAMID_BUILD_BUDGET_S = 2.5  # ≤ 2.5 s (D-024)
_CURSOR_UPDATE_BUDGET_S = 0.002  # ≤ 2 ms


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

    budget = _PYRAMID_BUILD_BUDGET_S * _ACTUAL_MULTIPLIER
    assert benchmark.stats["mean"] <= budget, (
        f"Pyramid build mean {benchmark.stats['mean']:.3f}s exceeds "
        f"budget {budget:.1f}s (dev={_PYRAMID_BUILD_BUDGET_S}s × {_ACTUAL_MULTIPLIER}×). "
        "Fix pyramid.py or adjust CI_BUDGET_MULTIPLIER in test_bench_pyramid.py."
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


def test_bench_cursor_path(benchmark, tmp_path: Path):
    """Full per-tick cursor path: plot set_cursor + transport set_time + readout
    set_cursor + set_camera_states for 4 cams + 4 channels (★ ≤2ms budget).

    Simulates the hot path that runs every 60 Hz tick in the live UI.  All
    I/O-heavy parts (pyramid loads) are pre-warmed so only the signalling and
    rendering-update path is measured.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])

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

    budget = _CURSOR_UPDATE_BUDGET_S * _ACTUAL_MULTIPLIER
    assert benchmark.stats["mean"] <= budget, (
        f"Cursor update mean {benchmark.stats['mean'] * 1000:.3f}ms exceeds "
        f"budget {budget * 1000:.1f}ms"
        f" (dev={_CURSOR_UPDATE_BUDGET_S * 1000:.0f}ms × {_ACTUAL_MULTIPLIER}×)."
        " See BLUEPRINT.md ★ cursor-update budget."
    )
