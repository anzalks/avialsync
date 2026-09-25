"""Each group of controls sits under what it acts on (D-126).

Top to bottom: the videos, then the video tools; the plots, then the plot
controls and the time span; the Data Streams lanes, then their controls; then
the play controls. Asserted on window coordinates of a shown window, as order
rather than pixels (AGENTS.md: font metrics differ per platform).
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from avialsync.ui.main_window import MainWindow


@pytest.fixture
def window(qapp, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1400, 1000)
    win.show()
    qtbot.waitExposed(win)
    yield win
    if isValid(win):
        win.close()


def _top(window: MainWindow, widget: QWidget) -> int:
    return widget.mapTo(window, QPoint(0, 0)).y()


def _bottom(window: MainWindow, widget: QWidget) -> int:
    return _top(window, widget) + widget.height()


def test_controls_sit_under_what_they_act_on(window: MainWindow) -> None:
    plots = window.plot_pane
    evidence = window.data_streams
    order = [
        ("videos", _top(window, window.video_grid)),
        ("video tools", _top(window, window.view_toolbar)),
        ("plots", _top(window, plots._plot_scroll)),
        ("plot controls", _top(window, plots._plot_header)),
        ("time span", _top(window, plots._sweep_control)),
        ("data streams lanes", _top(window, evidence.overview)),
        ("data streams controls", _top(window, evidence.collapse_button)),
        ("play controls", _top(window, window.transport.play_btn)),
    ]
    tops = [top for _, top in order]
    assert tops == sorted(tops), order
    assert _bottom(window, window.video_grid) <= _top(window, window.view_toolbar)


def test_video_tools_are_under_the_videos_not_the_3d_view(window: MainWindow) -> None:
    window.tracking_3d_pane.setVisible(True)
    toolbar = window.view_toolbar
    left = toolbar.mapTo(window, QPoint(0, 0)).x()
    right = left + toolbar.width()
    pane = window.tracking_3d_pane.mapTo(window, QPoint(0, 0)).x()
    assert right <= pane, "the 3D pane keeps its full height beside them"


def test_every_tool_is_in_its_row(window: MainWindow) -> None:
    toolbar = window.view_toolbar
    for button in (
        toolbar.flag_button,
        toolbar.fix_tracker_button,
        toolbar.add_marker_button,
        toolbar.add_wheel_button,
        toolbar.snapshot_button,
        toolbar.fit_videos_button,
        toolbar.fullscreen_button,
    ):
        assert button.parentWidget() is toolbar
    assert window.data_streams.collapse_button.parentWidget() is window.data_streams
