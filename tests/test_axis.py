"""Tests for the shared continuous plot-window slider."""

from __future__ import annotations

import pytest

from avialview.ui.plot_pane import PlotPane
from avialview.ui.transport import Transport


def test_adjacent_slider_positions_produce_distinct_continuous_windows(qtbot) -> None:
    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.set_timeline_bounds(0.0, 120.0)

    pane.window_slider.setValue(700)
    first = pane.window_duration
    pane.window_slider.setValue(701)
    second = pane.window_duration

    assert second > first
    assert second - first < first * 0.02


def test_programmatic_window_change_keeps_slider_and_label_in_sync(qtbot) -> None:
    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.set_timeline_bounds(0.0, 120.0)

    pane.set_window_duration(7.25)

    assert pane.window_duration == pytest.approx(7.25)
    assert pane.window_slider.value() == pane._sweep_control.slider_from_duration(7.25)
    assert pane.window_value_label.text() == "7.250 s"


def test_transport_has_no_second_plot_zoom_control(qtbot) -> None:
    """Plot navigation has one authority below the plots, not one in Transport."""
    transport = Transport()
    qtbot.addWidget(transport)

    assert not hasattr(transport, "window_combo")
    assert not hasattr(transport, "follow_checkbox")
