"""Tests for PlotPane measure markers and measure_changed signal."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def plot_pane(app):
    from avialview.ui.plot_pane import PlotPane

    return PlotPane()


class TestMeasureMarkers:
    def test_initial_state(self, plot_pane):
        assert plot_pane._measure_a is None
        assert plot_pane._measure_b is None

    def test_set_a(self, plot_pane):
        plot_pane.set_measure_a(1.5)
        assert plot_pane._measure_a == pytest.approx(1.5)
        assert plot_pane._measure_b is None

    def test_set_b(self, plot_pane):
        plot_pane.set_measure_a(1.0)
        plot_pane.set_measure_b(3.0)
        assert plot_pane._measure_b == pytest.approx(3.0)

    def test_clear(self, plot_pane):
        plot_pane.set_measure_a(1.0)
        plot_pane.set_measure_b(2.0)
        plot_pane.clear_measure()
        assert plot_pane._measure_a is None
        assert plot_pane._measure_b is None

    def test_measure_changed_signal_emitted(self, app, plot_pane):
        received = []
        plot_pane.measure_changed.connect(lambda a, b: received.append((a, b)))
        plot_pane.set_measure_a(2.0)
        plot_pane.set_measure_b(5.0)
        assert len(received) == 1
        ta, tb = received[0]
        assert ta == pytest.approx(2.0)
        assert tb == pytest.approx(5.0)

    def test_measure_changed_orders_min_max(self, app, plot_pane):
        received = []
        plot_pane.clear_measure()
        plot_pane.measure_changed.connect(lambda a, b: received.append((a, b)))
        plot_pane.set_measure_a(8.0)
        plot_pane.set_measure_b(3.0)
        ta, tb = received[-1]
        assert ta < tb  # always emitted in (min, max) order

    def test_signal_not_emitted_with_only_a(self, app):
        from avialview.ui.plot_pane import PlotPane

        p = PlotPane()
        received = []
        p.measure_changed.connect(lambda a, b: received.append((a, b)))
        p.set_measure_a(1.0)
        assert received == []

    def test_clear_empties_lines(self, plot_pane):
        plot_pane.set_measure_a(1.0)
        plot_pane.set_measure_b(2.0)
        plot_pane.clear_measure()
        assert plot_pane._measure_a_lines == []
        assert plot_pane._measure_b_lines == []
