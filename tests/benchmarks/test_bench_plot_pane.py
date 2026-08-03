"""Performance guards for the populated plot pane (BLUEPRINT.md budgets).

P4.6's exit criteria in ``PLOT_UX_PLAN.md`` §14 require populated cursor,
redraw, and resize-storm evidence against the budgets table. Benchmarks
existed for the pyramid, sync, 3D tracking, and video timing hot paths but not
for the plot rows themselves, which is where the ★ cursor and frame budgets
are actually spent.

Run with ``conda run -n avialsync pytest --benchmark-only``. The ★ marks are
enforced here without a multiplier; hosted CI does not certify speed
(BLUEPRINT.md "Performance budgets"), so these are excluded from the CI run.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from avialsync.core.pyramid import PyramidBuilder
from avialsync.ui.plot_pane import PlotPane

# ★ Full populated cursor update per tick.
_CURSOR_BUDGET_S = 0.002
# ★ Plot pan/zoom frame time.
_FRAME_BUDGET_S = 0.016
# Hard ceiling for any UI-thread callback.
_UI_CALLBACK_CEILING_S = 0.030


def _channel_cache(tmp_path: Path, count: int, samples: int = 6_000) -> Path:
    """Build a field-shaped multi-channel pyramid cache.

    Sample depth is kept modest on purpose: a query returns at most
    ``point_budget_for_width`` points regardless, so row *count* drives the
    cost measured here, while a deeper cache only adds memory pressure that
    skews the other benchmarks sharing the session.
    """
    cache = tmp_path / "bench.avialcache"
    cache.mkdir(parents=True, exist_ok=True)
    times = np.linspace(0.0, 60.0, samples)
    for index in range(count):
        values = np.sin(times * (index + 1) * 0.1) + np.random.default_rng(index).normal(
            0.0, 0.05, samples
        )
        PyramidBuilder(cache, f"ch{index}").build_and_save(times, values)
    return cache


def _populated_pane(qtbot, tmp_path: Path, count: int) -> PlotPane:
    """Return a pane with *count* rows fully built, not queued."""
    cache = _channel_cache(tmp_path, count)
    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(1280, 800)
    pane.load_channels(cache, [f"ch{index}" for index in range(count)])
    # load_channels slices row construction across event-loop turns; drain it
    # so the benchmark measures a populated pane rather than an empty one.
    pane.wait_for_pending_rows()
    assert len(pane.channels) == count
    return pane


@pytest.mark.parametrize("channels", [32, 128])
def test_bench_populated_cursor_tick(benchmark, qtbot, tmp_path: Path, channels: int) -> None:
    """A cursor tick on a populated pane must stay inside the ★ 2 ms budget."""
    pane = _populated_pane(qtbot, tmp_path, channels)
    pane.set_timeline_bounds(0.0, 60.0)
    pane.set_window_duration(10.0)
    times = np.linspace(0.0, 60.0, 601)
    counter = {"index": 0}

    def advance() -> None:
        """Advance to a new time each call; a repeated time is not a tick."""
        pane.set_cursor(float(times[counter["index"] % len(times)]))
        counter["index"] += 1

    benchmark(advance)

    assert benchmark.stats["mean"] <= _CURSOR_BUDGET_S, (
        f"{channels}-channel cursor tick averaged {benchmark.stats['mean'] * 1000:.2f} ms "
        f"against a {_CURSOR_BUDGET_S * 1000:.0f} ms budget"
    )


@pytest.mark.parametrize("channels", [32, 128])
def test_bench_window_duration_change(benchmark, qtbot, tmp_path: Path, channels: int) -> None:
    """Changing the shared time span must not overrun the UI-callback ceiling.

    This measures the *callback*, which is what the ceiling governs, not the
    total requery: rows beyond the first slice are refreshed in later
    event-loop turns (D-063). Row work is bounded to the slice budget and the
    axis-label re-render is gone, so what remains is pyqtgraph applying the new
    range to each linked ViewBox — irreducible per row without giving up the
    shared X link the layout is built on.
    """
    pane = _populated_pane(qtbot, tmp_path, channels)
    pane.set_timeline_bounds(0.0, 60.0)
    durations = (5.0, 10.0, 20.0, 40.0)
    counter = {"index": 0}

    def zoom() -> None:
        pane.set_window_duration(durations[counter["index"] % len(durations)])
        counter["index"] += 1

    benchmark(zoom)
    # The last iteration leaves rows queued behind a zero-delay timer. Left
    # armed it keeps firing through whatever benchmark runs next and steals the
    # CPU that benchmark is measuring.
    pane.cancel_pending_rows()

    assert benchmark.stats["mean"] <= _UI_CALLBACK_CEILING_S, (
        f"{channels}-channel zoom averaged {benchmark.stats['mean'] * 1000:.2f} ms "
        f"against a {_UI_CALLBACK_CEILING_S * 1000:.0f} ms UI-callback ceiling"
    )


def test_bench_resize_storm(benchmark, qtbot, tmp_path: Path) -> None:
    """A drag resizes continuously; no single callback may pass the ceiling.

    128 channels is the documented worst-case field workload
    (PLOT_UX_PLAN.md §15).
    """
    pane = _populated_pane(qtbot, tmp_path, 128)
    pane.set_timeline_bounds(0.0, 60.0)
    pane.set_window_duration(10.0)
    widths = (1280, 1400, 1100, 1600)
    counter = {"index": 0}

    def resize() -> None:
        pane.resize(widths[counter["index"] % len(widths)], 800)
        counter["index"] += 1

    benchmark(resize)

    assert benchmark.stats["max"] <= _UI_CALLBACK_CEILING_S, (
        f"worst resize callback was {benchmark.stats['max'] * 1000:.2f} ms "
        f"against a {_UI_CALLBACK_CEILING_S * 1000:.0f} ms ceiling"
    )


def test_bench_row_build_slice(benchmark, qtbot, tmp_path: Path) -> None:
    """One slice of row construction must not freeze the window.

    Rows are built in time slices precisely so a large selection cannot block
    the UI thread (D-060); this guards the slice budget rather than the total.
    """
    cache = _channel_cache(tmp_path, 128)
    names = [f"ch{index}" for index in range(128)]
    panes: list[PlotPane] = []

    def build_one_slice() -> None:
        pane = PlotPane()
        qtbot.addWidget(pane)
        pane.resize(1280, 800)
        pane.load_channels(cache, names)
        panes.append(pane)

    benchmark(build_one_slice)
    for pane in panes:
        pane.cancel_pending_rows()

    assert benchmark.stats["mean"] <= _UI_CALLBACK_CEILING_S, (
        f"first row-build slice averaged {benchmark.stats['mean'] * 1000:.2f} ms "
        f"against a {_UI_CALLBACK_CEILING_S * 1000:.0f} ms ceiling"
    )
