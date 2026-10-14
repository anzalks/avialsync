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

from avialsync.core.pyramid import PyramidBuilder, PyramidReader

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
    # A gap moves the remaining timeline forward; shifting only one bucket
    # would introduce a backward jump and invalidate searchsorted queries.
    t[50_000_000:] += 10.0
    assert t[50_000_000] - t[49_999_999] > 10.0
    assert t[50_000_050] > t[50_000_049]

    return t, v


def test_bench_pyramid_build(benchmark, tmp_path: Path, large_dataset):
    """Pyramid build for 180M samples must complete within the ★ budget."""
    t, v = large_dataset

    def setup():
        gc.collect()
        cache_dir = tmp_path / "bench_cache"
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

    cache_dir = tmp_path / "bench_q_cache"
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


def test_bench_cursor_path(benchmark, qtbot, tmp_path: Path):
    """Measure populated plots, transport, four readouts and four camera rows."""
    from avialsync.ui.readout_panel import ReadoutPanel
    from avialsync.ui.transport import Transport
    from tests.benchmarks.test_bench_plot_pane import _populated_pane, _settled_page

    plot_pane = _populated_pane(qtbot, tmp_path, 4)
    plot_pane.set_timeline_bounds(0.0, 60.0)
    plot_pane.set_window_duration(10.0)
    _settled_page(qtbot, plot_pane)
    transport = Transport()
    transport.set_bounds(0.0, 60.0)
    readout = ReadoutPanel()
    for widget in (transport, readout):
        qtbot.addWidget(widget)
        widget.show()
    readout.update_sources([channel.reader for channel in plot_pane.channels])
    readout.set_cursor(0.5)
    readout.set_camera_frame_records([(f"cam{i}", 15, 0.5) for i in range(4)])
    assert len(readout._rows) == len(plot_pane.channels) == 4
    assert len(readout._cam_rows) == 4
    assert readout.textual_summary().count("(sample ") == 4
    counter = 0

    def tick():
        nonlocal counter
        counter += 1
        t_cursor = 0.1 + (counter % 980) / 100
        plot_pane._last_cursor_repaint = float("-inf")
        plot_pane.set_cursor(t_cursor)
        transport.set_time(t_cursor)
        readout.set_cursor(t_cursor)
        readout.set_camera_frame_records(
            [(f"cam{i}", int(t_cursor * 30), t_cursor) for i in range(4)]
        )

    benchmark(tick)
    expected = 0.1 + (counter % 980) / 100
    assert plot_pane.channels[0].cursor_line.value() == pytest.approx(expected)
    assert readout.textual_summary().count("(sample ") == 4

    budget = _CURSOR_UPDATE_BUDGET_S
    stats = benchmark.stats
    if stats is None:
        pytest.skip("benchmark statistics unavailable (benchmarks disabled)")
    assert stats["mean"] <= budget, (
        f"Cursor update mean {stats['mean'] * 1000:.3f}ms exceeds "
        f"budget {budget * 1000:.1f}ms."
        " See BLUEPRINT.md ★ cursor-update budget."
    )
    plot_pane.shutdown()


def test_bench_four_channel_window_refresh(benchmark, tmp_path: Path):
    """A committed shared-window change stays below the 30 ms UI budget."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    from avialsync.ui.plot_pane import PlotPane

    sample_count = 50_000
    pane = PlotPane()
    pane.resize(1000, 600)
    pane.set_timeline_bounds(0.0, 1.0)
    for channel_index in range(4):
        cache_dir = tmp_path / f"window_ch{channel_index}_cache"
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
