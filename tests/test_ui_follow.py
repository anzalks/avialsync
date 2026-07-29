"""Tests for fixed-window oscilloscope plotting."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt

from avialview.core.pyramid import PyramidBuilder
from avialview.ui.plot_pane import PlotPane
from avialview.ui.sidebar import SensorInfoWidget, SidebarPane


@pytest.fixture
def sweep_pane(qtbot, tmp_path: Path) -> PlotPane:
    times = np.linspace(100.0, 140.0, 4001)
    PyramidBuilder(tmp_path, "alpha").build_and_save(times, np.sin(times))
    PyramidBuilder(tmp_path, "beta").build_and_save(times, np.cos(times))

    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(900, 500)
    pane.set_timeline_bounds(100.0, 140.0)
    pane.load_channels(tmp_path, ["alpha", "beta"])
    pane.set_window_duration(5.5)
    return pane


def test_sweep_grows_left_to_right_then_restarts_without_moving_axis(sweep_pane) -> None:
    pane = sweep_pane
    pane.set_cursor(105.2)
    first_range = tuple(pane._master_plot.viewRange()[0])

    assert first_range == pytest.approx((0.0, 5.5))
    assert pane.sweep_start == pytest.approx(100.0)
    assert pane.channels[0].curve._sweep_position == pytest.approx(5.2)

    pane.set_cursor(105.6)

    assert tuple(pane._master_plot.viewRange()[0]) == pytest.approx(first_range)
    assert pane.sweep_start == pytest.approx(105.5)
    assert pane.channels[0].curve._sweep_position == pytest.approx(0.1)
    assert pane.channels[0].cursor_line.value() == pytest.approx(0.1)


def test_all_plot_rows_share_one_x_range_and_one_window_slider(sweep_pane) -> None:
    pane = sweep_pane
    pane.window_slider.setValue(900)

    ranges = [tuple(channel.plot_item.viewRange()[0]) for channel in pane.channels]
    assert ranges[0] == pytest.approx((0.0, pane.window_duration))
    assert ranges[1] == pytest.approx(ranges[0])
    assert len(pane.findChildren(type(pane.window_slider))) == 1


def test_pyramid_is_not_requeried_on_every_master_clock_tick(sweep_pane, monkeypatch) -> None:
    pane = sweep_pane
    calls = 0
    original = pane.channels[0].reader.query

    def counted_query(t0: float, t1: float, max_points: int):
        nonlocal calls
        calls += 1
        return original(t0, t1, max_points)

    monkeypatch.setattr(pane.channels[0].reader, "query", counted_query)
    pane.set_cursor(101.0)
    pane.set_cursor(102.0)
    pane.set_cursor(103.0)
    assert calls == 0

    pane.set_cursor(106.0)
    assert calls == 1


def test_measure_markers_keep_absolute_time_but_render_in_current_sweep(sweep_pane) -> None:
    pane = sweep_pane
    pane.set_cursor(106.0)
    pane.set_measure_a(106.5)

    assert pane._measure_a == pytest.approx(106.5)
    assert pane._measure_a_lines[0].value() == pytest.approx(1.0)


def test_row_close_hides_plot_and_unchecks_sidebar_channel(qtbot, sweep_pane) -> None:
    pane = sweep_pane
    sidebar = SidebarPane()
    qtbot.addWidget(sidebar)
    sidebar.add_sensor("/tmp/source.csv", ["alpha", "beta"])
    pane.channel_close_requested.connect(
        lambda channel: sidebar.set_channel_visible(channel, False)
    )
    sensor = next(
        widget
        for widget in sidebar.findChildren(SensorInfoWidget)
        if widget.path == "/tmp/source.csv"
    )

    qtbot.mouseClick(pane.channels[0].close_button, Qt.MouseButton.LeftButton)

    assert not pane.channels[0].plot_item.isVisible()
    assert sensor._channel_items["alpha"].checkState(0) == Qt.CheckState.Unchecked
    assert pane.channels[0].close_button.size().width() <= 18
