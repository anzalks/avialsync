"""Painted surfaces answer assistive technology on query (D-179, DS-12)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QAbstractButton, QApplication
from shiboken6 import isValid

from avialsync.ui.design_tokens import ControlRole, role_of
from avialsync.ui.main_window import MainWindow
from avialsync.ui.tracking_3d_pane import Tracking3DCanvas
from avialsync.ui.transport import Transport
from tests.test_ui_plot_row_geometry import _pane_with_channels


def _value(widget) -> str:
    return QAccessible.queryAccessibleInterface(widget).text(QAccessible.Text.Value)


def _description(widget) -> str:
    return QAccessible.queryAccessibleInterface(widget).text(QAccessible.Text.Description)


def test_plot_rows_report_name_unit_and_value_at_the_playhead(qtbot, tmp_path: Path) -> None:
    pane = _pane_with_channels(qtbot, tmp_path, 3, 1000, 600)
    pane.set_cursor(1.0, immediate=True)
    interface = QAccessible.queryAccessibleInterface(pane.graphics_layout)
    assert interface.role() == QAccessible.Role.Chart
    value = _value(pane.graphics_layout)
    for channel in pane.channels:
        assert f"{channel.name}: " in value
    sample = pane.channels[0].reader.sample_at(1.0)
    assert sample is not None and f"{sample[1]:.4g}" in value
    assert "3 channel rows" in _description(pane.graphics_layout)


def test_lanes_report_each_source_span(qtbot) -> None:
    transport = Transport()
    qtbot.addWidget(transport)
    transport.set_bounds(0.0, 10.0)
    transport.set_source_coverage("/rec/camera_1.mp4", 1.0, 9.0, "video")
    transport.set_time(2.5)
    overview = transport.overview
    assert "2.500" in _value(overview)
    assert "1.000–9.000 s" in _description(overview)


def test_video_and_3d_report_what_they_show(qtbot) -> None:
    pytest.importorskip("av")
    from avialsync.ui.video_pane import VideoPane

    pane = VideoPane()
    qtbot.addWidget(pane)
    pane.set_label("camera_1.mp4")
    pane.surface.set_frame(np.zeros((360, 640, 3), dtype=np.uint8))
    assert QAccessible.queryAccessibleInterface(pane).role() == QAccessible.Role.Graphic
    assert " · f " in _value(pane)
    assert _description(pane).startswith("camera_1.mp4: ")
    pane.close()

    canvas = Tracking3DCanvas()
    qtbot.addWidget(canvas)
    assert "points; azimuth 40°, elevation 25°" in _value(canvas)


def test_nothing_is_pushed_to_assistive_technology_per_tick(qtbot, monkeypatch, tmp_path) -> None:
    """Values are read when asked; playback never announces them (D-179)."""
    calls: list[object] = []
    monkeypatch.setattr(QAccessible, "updateAccessibility", lambda event: calls.append(event))
    pane = _pane_with_channels(qtbot, tmp_path, 4, 1000, 600)
    transport = Transport()
    qtbot.addWidget(transport)
    transport.set_bounds(0.0, 4.0)
    for tick in range(240):
        t = tick / 60.0
        pane.set_cursor(t)
        transport.set_time(t)
    assert calls == []
    source = Path("src/avialsync/ui/accessible_views.py").read_text(encoding="utf-8")
    assert "updateAccessibility(" not in source


@pytest.fixture
def window(qapp: QApplication, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    if isValid(win):
        win.close()


def test_every_primary_action_is_reachable_by_keyboard(window: MainWindow) -> None:
    """DS-12 step 4: Tab reaches each primary; the rail moves by arrow keys."""
    primaries = [
        button
        for button in window.findChildren(QAbstractButton)
        if role_of(button) is ControlRole.PRIMARY
    ]
    assert primaries
    for button in primaries:
        assert button.focusPolicy() & Qt.FocusPolicy.TabFocus, button.accessibleName()
        assert button.accessibleName() or button.text()
    for index in range(window._left_tabs.count()):
        assert window._left_tabs.button(index).focusPolicy() & Qt.FocusPolicy.TabFocus
