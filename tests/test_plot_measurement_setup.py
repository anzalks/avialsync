"""Benchmark setup must execute the same work as the visible plot pane."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from benchmarks.test_bench_plot_pane import _populated_pane, _settled_page
from PySide6.QtCore import QEvent, QObject


def test_populated_measurement_pane_is_visible(qtbot, tmp_path: Path) -> None:
    pane = _populated_pane(qtbot, tmp_path, 4)
    assert pane.isVisible(), "hidden resize calls do not deliver the measured resize work"


def test_prepared_measurement_page_contains_the_loaded_rows(qtbot, tmp_path: Path) -> None:
    pane = _populated_pane(qtbot, tmp_path, 4)
    pane.set_timeline_bounds(0.0, 60.0)
    pane.set_window_duration(10.0)
    page = _settled_page(qtbot, pane)
    assert len(page.rows) == len(pane.channels)
    assert all(len(x) > 0 and len(x) == len(y) for _, x, y in page.rows)
    pane._requested_rows = tuple(pane.channels)
    for channel in pane.channels:
        channel.curve.setData([0.0], [float("nan")])
    pane._on_page_ready(page)
    for index, x, y in page.rows:
        actual_x, actual_y = pane.channels[index].curve.getData()
        np.testing.assert_array_equal(actual_x, x)
        np.testing.assert_array_equal(actual_y, y)


def test_visible_measurement_resize_delivers_events(qtbot, tmp_path: Path) -> None:
    class ResizeObserver(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.events = 0

        def eventFilter(self, watched, event) -> bool:
            if event.type() == QEvent.Type.Resize:
                self.events += 1
            return False

    pane = _populated_pane(qtbot, tmp_path, 4)
    observer = ResizeObserver()
    pane.installEventFilter(observer)
    pane.resize(pane.width() + 80, pane.height())
    assert observer.events > 0
    assert not pane.grab().isNull()
