"""Tests for fixed-window oscilloscope plotting."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt

from avialview.core.pyramid import PyramidBuilder
from avialview.ui.plot_pane import PlotPane
from avialview.ui.plot_row import Y_AUTO, Y_MANUAL
from avialview.ui.plot_sweep import PlotPresentation
from avialview.ui.sidebar import SensorInfoWidget, SidebarPane


@pytest.fixture
def sweep_pane(qtbot, tmp_path: Path) -> PlotPane:
    times = np.linspace(100.0, 140.0, 4001)
    PyramidBuilder(tmp_path, "alpha").build_and_save(times, np.sin(times))
    PyramidBuilder(tmp_path, "beta").build_and_save(times, np.cos(times))

    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(900, 500)
    pane.presentation_combo.setCurrentText("Scope")
    pane.set_timeline_bounds(100.0, 140.0)
    pane.load_channels(tmp_path, ["alpha", "beta"])
    # Rows are built across event-loop turns so a big load stays interactive
    # (D-060); a test that asserts on every row must wait for them.
    pane.wait_for_pending_rows()
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


def test_paused_review_reveals_the_complete_current_page(sweep_pane) -> None:
    pane = sweep_pane
    pane.set_cursor(103.0)

    assert pane.presentation is PlotPresentation.REVIEW
    assert pane.channels[0].curve._reveal_enabled is False


def test_live_scope_keeps_clear_and_restart_compatibility(sweep_pane) -> None:
    pane = sweep_pane
    pane.presentation_combo.setCurrentText("Scope")
    pane.set_playing(True)
    pane.set_cursor(104.0)
    pane.set_cursor(106.0)

    assert pane.presentation is PlotPresentation.SCOPE
    assert pane.channels[0].curve._reveal_enabled is True


def test_all_plot_rows_share_one_x_range_and_one_window_slider(sweep_pane) -> None:
    pane = sweep_pane
    pane.window_slider.setValue(900)

    ranges = [tuple(channel.plot_item.viewRange()[0]) for channel in pane.channels]
    assert ranges[0] == pytest.approx((0.0, pane.window_duration))
    assert ranges[1] == pytest.approx(ranges[0])
    assert len(pane.findChildren(type(pane.window_slider))) == 1


def test_only_the_bottom_visible_row_shows_shared_x_axis_values(sweep_pane) -> None:
    pane = sweep_pane
    first_axis = pane.channels[0].plot_item.getAxis("bottom")
    last_axis = pane.channels[1].plot_item.getAxis("bottom")

    assert first_axis.style["showValues"] is False
    assert last_axis.style["showValues"] is True

    pane.set_channel_visible("beta", False)
    assert first_axis.style["showValues"] is True


def test_channel_gutter_and_fit_once_y_range_remain_stable_during_live_playback(sweep_pane) -> None:
    pane = sweep_pane
    pane.set_channel_unit("alpha", "mV")
    pane.set_cursor(104.0)
    initial_range = pane.channels[0].y_range
    pane.set_playing(True)
    pane.set_cursor(106.0)

    assert "mV" in pane.channels[0].plot_item.getAxis("left").labelText
    assert pane.channels[0].y_range == initial_range


def test_channel_y_modes_make_auto_explicit_and_manual_hold_the_current_range(sweep_pane) -> None:
    pane = sweep_pane
    pane.set_cursor(104.0)
    pane.set_channel_y_mode("alpha", Y_AUTO)

    assert pane.channels[0].y_mode == Y_AUTO
    assert pane.channels[0].y_range is not None

    pane.set_channel_y_mode("alpha", Y_MANUAL)
    held_range = pane.channels[0].y_range
    pane.set_cursor(106.0)

    assert pane.channels[0].y_mode == Y_MANUAL
    assert pane.channels[0].y_range == held_range


def test_row_height_control_uses_one_scrollable_plot_stack(sweep_pane) -> None:
    pane = sweep_pane
    pane.row_height_combo.setCurrentText("Compact")

    assert pane.graphics_layout.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert pane.channels[0].plot_item.minimumHeight() == 72


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


def test_decimated_plot_preserves_minimum_and_maximum_envelope(qtbot, tmp_path: Path) -> None:
    """A narrow spike remains visible instead of being averaged into a midpoint."""
    times = np.linspace(100.0, 140.0, 4096)
    values = np.zeros_like(times)
    values[100] = 100.0
    PyramidBuilder(tmp_path, "spike").build_and_save(times, values)

    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(900, 500)
    pane.presentation_combo.setCurrentText("Scope")
    pane.set_timeline_bounds(100.0, 140.0)
    pane.load_channels(tmp_path, ["spike"])
    pane.wait_for_pending_rows()
    pane.set_window_duration(5.5)

    channel = pane.channels[0]
    pane.set_cursor(100.0)

    # Wait for the async worker to finish updating the plot
    qtbot.wait(pane._sweep_control._DRAG_REFRESH_MS + 50)
    pane.update_plots()
    qtbot.wait(50)

    # The curve interleaves each decimated column's min and max into one
    # polyline (D-057), so a spike that only a maximum captures is still drawn.
    # Before that, the visible curve carried the per-column *minimum* and the
    # peak lived only in an alpha fill on top of it.
    x, y = channel.curve.getData()

    assert x is not None and y is not None
    assert np.nanmax(y) == pytest.approx(100.0), "the spike must survive decimation"
    assert np.nanmin(y) == pytest.approx(0.0)


def test_slider_drag_coalesces_pyramid_refreshes(qtbot, sweep_pane, monkeypatch) -> None:
    pane = sweep_pane
    calls = 0
    original = pane.channels[0].reader.query

    def counted_query(t0: float, t1: float, max_points: int):
        nonlocal calls
        calls += 1
        return original(t0, t1, max_points)

    monkeypatch.setattr(pane.channels[0].reader, "query", counted_query)
    pane.window_slider.sliderPressed.emit()
    for value in range(200, 1200, 20):
        pane.window_slider.setValue(value)

    assert calls == 0
    qtbot.waitUntil(lambda: calls >= 1, timeout=1000)

    pane.window_slider.setValue(1300)
    pane.window_slider.setValue(1400)
    pane.window_slider.sliderReleased.emit()
    qtbot.waitUntil(lambda: calls >= 2, timeout=1000)


def test_hidden_rows_are_not_queried(sweep_pane, monkeypatch) -> None:
    pane = sweep_pane
    calls = 0
    original = pane.channels[1].reader.query

    def counted_query(t0: float, t1: float, max_points: int):
        nonlocal calls
        calls += 1
        return original(t0, t1, max_points)

    monkeypatch.setattr(pane.channels[1].reader, "query", counted_query)
    pane.set_channel_visible("beta", False)
    pane.set_cursor(106.0)

    assert calls == 0


def test_hidden_plot_stays_hidden_through_resize_storm(qtbot, sweep_pane) -> None:
    pane = sweep_pane
    hidden = pane.channels[1]
    pane.set_channel_visible("beta", False)
    pane.show()

    for width in range(920, 1121, 20):
        pane.resize(width, 500)
    qtbot.wait(100)

    assert hidden.visible is False
    assert hidden.plot_item.isVisible() is False
    assert hidden.close_proxy.isVisible() is False
    assert hidden.plot_item.maximumHeight() == 0


def test_resize_storm_triggers_one_deferred_redecimation(
    qtbot,
    sweep_pane,
    monkeypatch,
) -> None:
    pane = sweep_pane
    pane.show()
    qtbot.wait(100)
    calls = 0
    original = pane.update_plots

    def counted_update() -> None:
        nonlocal calls
        calls += 1
        original()

    monkeypatch.setattr(pane, "update_plots", counted_update)
    pane._last_point_budget = 0
    for width in range(920, 1021, 10):
        pane.resize(width, 500)
    qtbot.wait(100)

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
    # The signal carries the owning source so a name shared by two files
    # unchecks the right box (P3.5 P1 identity).
    pane.channel_close_requested.connect(
        lambda source_id, channel: sidebar.set_channel_visible(channel, False, source_id)
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
