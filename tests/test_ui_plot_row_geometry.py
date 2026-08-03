"""Plot rows must occupy the pane, not collapse to their minimum width.

Rows are built across event-loop turns (D-060), so the last resize the graphics
view saw often predates the rows themselves. pyqtgraph only refreshes its
central item's geometry from a resize, and ``layout.activate()`` merely arranges
children *inside* whatever geometry that item already has. When the two raced
the wrong way every row rendered about 8 px wide inside a pane a thousand pixels
across: the curve was correct and invisible.

It was intermittent, which is worse than broken — the committed demo
screenshots were captured on a run that happened to lay out, so nothing showed
it was wrong.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from avialsync.core.pyramid import PyramidBuilder
from avialsync.ui.plot_pane import PlotPane

#: The left gutter carries the rotated channel label and the tick numbers. It is
#: fixed-width, so everything else across the pane belongs to the curve.
_GUTTER_ALLOWANCE_PX = 200


def _pane_with_channels(qtbot, tmp_path: Path, count: int, width: int, height: int) -> PlotPane:
    cache = tmp_path / f"rows{count}.avialcache"
    cache.mkdir(parents=True, exist_ok=True)
    times = np.arange(4_000, dtype=np.float64) / 1000.0
    names = [f"ch{index}" for index in range(count)]
    for index, name in enumerate(names):
        PyramidBuilder(cache, name).build_and_save(times, np.sin(times + index))

    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(width, height)
    pane.show()
    qtbot.waitExposed(pane)
    pane.set_timeline_bounds(0.0, 4.0)
    pane.load_channels(cache, names)
    pane.wait_for_pending_rows()
    return pane


@pytest.mark.parametrize(("count", "width"), [(1, 1000), (3, 1000), (1, 1500), (4, 1500)])
def test_rows_fill_the_pane_width(qtbot, tmp_path: Path, count: int, width: int) -> None:
    """Every row's plot area must span the pane, whatever the size or row count."""
    pane = _pane_with_channels(qtbot, tmp_path, count, width, 700)

    assert len(pane.channels) == count
    for channel in pane.channels:
        drawn = channel.plot_item.getViewBox().sceneBoundingRect().width()
        assert drawn > pane.graphics_layout.width() - _GUTTER_ALLOWANCE_PX, (
            f"{channel.name} drew {drawn:.0f} px inside a "
            f"{pane.graphics_layout.width()} px view — the row collapsed to its "
            f"minimum, so the curve is correct but invisible"
        )


def test_a_row_added_after_the_first_load_also_fills_the_pane(qtbot, tmp_path: Path) -> None:
    """A second load must not leave the newest row collapsed beside settled ones."""
    pane = _pane_with_channels(qtbot, tmp_path, 2, 1400, 700)

    second = tmp_path / "later.avialcache"
    second.mkdir(parents=True, exist_ok=True)
    times = np.arange(4_000, dtype=np.float64) / 1000.0
    PyramidBuilder(second, "late").build_and_save(times, np.cos(times))
    pane.load_channels(second, ["late"])
    pane.wait_for_pending_rows()

    widths = {
        channel.name: channel.plot_item.getViewBox().sceneBoundingRect().width()
        for channel in pane.channels
    }
    assert len(widths) == 3
    floor = pane.graphics_layout.width() - _GUTTER_ALLOWANCE_PX
    assert all(value > floor for value in widths.values()), widths
