"""A span change requeries every row without holding the UI thread (D-063).

The benchmark measures the cost; these pin the behaviour that makes it safe —
that the deferred rows really do arrive, that a later change wins over one
still in flight, and that a queued slice cannot outlive the pane.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from avialview.core.pyramid import PyramidBuilder
from avialview.ui.plot_pane import PlotPane

# Enough rows that the requery cannot finish inside one slice budget. A
# smaller selection legitimately completes in the first callback, which is
# the behaviour these tests would then fail to observe.
CHANNEL_COUNT = 128


@pytest.fixture(scope="module")
def channel_cache(tmp_path_factory) -> Path:
    """Built once: 128 pyramids are slow enough to matter per test."""
    cache = tmp_path_factory.mktemp("sliced") / "sliced.avialcache"
    cache.mkdir(parents=True, exist_ok=True)
    times = np.linspace(0.0, 60.0, 20_000)
    for index in range(CHANNEL_COUNT):
        PyramidBuilder(cache, f"ch{index}").build_and_save(times, np.sin(times * (index + 1) * 0.1))
    return cache


@pytest.fixture
def pane(qtbot, channel_cache: Path) -> PlotPane:
    cache = channel_cache
    widget = PlotPane()
    qtbot.addWidget(widget)
    widget.resize(1280, 800)
    widget.load_channels(cache, [f"ch{index}" for index in range(CHANNEL_COUNT)])
    widget.wait_for_pending_rows()
    widget.set_timeline_bounds(0.0, 60.0)
    return widget


def test_a_span_change_defers_rows_instead_of_requerying_all_of_them(pane: PlotPane) -> None:
    """The callback must hand work back to the event loop, not finish it all."""
    pane.set_window_duration(7.0)

    assert pane._pending_refresh, "every row was requeried in one callback"
    assert len(pane._pending_refresh) < CHANNEL_COUNT, "no row was refreshed at all"


def test_every_deferred_row_is_eventually_refreshed(pane: PlotPane) -> None:
    """Deferring must not mean dropping."""
    pane.set_window_duration(7.0)

    pane.wait_for_pending_rows()

    assert not pane._pending_refresh
    for channel in pane.channels:
        times, _ = channel.curve.getData()
        assert times is not None and len(times) > 0, f"{channel.name} was never drawn"


def test_a_later_span_wins_over_one_still_in_flight(pane: PlotPane) -> None:
    """A drag emits several spans; rows must settle on the newest, not a mix."""
    pane.set_window_duration(30.0)
    assert pane._pending_refresh, "the first change must leave work queued"

    pane.set_window_duration(5.0)
    pane.wait_for_pending_rows()

    assert pane.window_duration == pytest.approx(5.0)
    for channel in pane.channels:
        times, _ = channel.curve.getData()
        # Rows are drawn in sweep-relative coordinates, so the span bounds them.
        assert times.max() <= 5.0 + 1e-6, f"{channel.name} kept the superseded span"


def test_playback_page_flips_are_not_deferred(pane: PlotPane) -> None:
    """Rows crossing a page boundary must flip together, or they disagree.

    Only the user-driven span change slices; the playback path stays atomic.
    """
    pane.set_window_duration(5.0)
    pane.wait_for_pending_rows()

    pane.set_cursor(30.0, immediate=True)

    assert not pane._pending_refresh, "a page flip left rows on the previous page"


def test_a_queued_slice_does_not_outlive_the_pane(pane: PlotPane) -> None:
    """Closing must abandon queued work rather than fire into dying widgets."""
    pane.set_window_duration(7.0)
    assert pane._pending_refresh

    pane.cancel_pending_rows()

    assert not pane._pending_refresh
