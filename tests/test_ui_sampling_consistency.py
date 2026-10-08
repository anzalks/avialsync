"""Auxiliary views use the same gap-aware sample as the Values panel."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from avialsync.core.pyramid import PyramidBuilder
from avialsync.ui.plot_pane import PlotPane


def test_accessible_plot_value_does_not_clamp_across_a_gap(qtbot, tmp_path: Path) -> None:
    cache = tmp_path / "source"
    cache.mkdir()
    times = np.array([0.0, 1.0, 2.0, 20.0, 21.0])
    PyramidBuilder(cache, "signal").build_and_save(times, times)
    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.load_channels(cache, ["signal"])
    pane.wait_for_pending_rows()
    pane.set_timeline_bounds(0.0, 21.0)
    pane.set_cursor(10.0, immediate=True)

    assert "signal: —" in pane.accessible_value()
