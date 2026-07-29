"""Tests for the shared bounded plot-window slider."""

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


@pytest.mark.parametrize(
    ("unit", "value", "expected_seconds"),
    [
        ("ms", 250.0, 0.25),
        ("s", 45.0, 45.0),
        ("min", 2.0, 120.0),
        ("h", 1.5, 5400.0),
    ],
)
def test_time_span_unit_conversion_preserves_duration_and_typed_value_sets_it(
    qtbot,
    unit: str,
    value: float,
    expected_seconds: float,
) -> None:
    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.set_timeline_bounds(0.0, 10_000.0)

    pane.set_window_duration(10.0)
    pane.window_unit_combo.setCurrentText(unit)
    assert pane.window_duration == pytest.approx(10.0)
    pane.window_limit_spin.setValue(value)

    assert pane.window_duration == pytest.approx(expected_seconds)
    expected_label = f"{value:.1f} ms" if unit == "ms" else f"{value:.3f} {unit}"
    assert pane.window_value_label.text() == expected_label


def test_time_span_editor_is_the_same_duration_authority_as_the_slider(qtbot) -> None:
    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.set_timeline_bounds(0.0, 3600.0)
    pane.set_window_duration(8.0)

    pane.window_limit_spin.setValue(60.0)

    assert pane.window_duration == pytest.approx(60.0)
    assert pane.window_slider.value() == pane._sweep_control.slider_from_duration(60.0)


def test_transport_has_no_second_plot_zoom_control(qtbot) -> None:
    """Plot navigation has one authority below the plots, not one in Transport."""
    transport = Transport()
    qtbot.addWidget(transport)

    assert not hasattr(transport, "window_combo")
    assert not hasattr(transport, "follow_checkbox")
