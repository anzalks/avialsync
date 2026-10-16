"""Data Streams lanes can be read and stepped along with the keyboard."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from avialsync.ui.timeline_keys import step_target
from avialsync.ui.transport import TimelineOverview


def test_step_target_moves_between_instants() -> None:
    times = np.array([1.0, 2.0, 5.0])

    assert step_target(times, 1.0, 1) == 2.0
    assert step_target(times, 2.0, -1) == 1.0
    assert step_target(times, 5.0, 1) is None
    assert step_target(times, 0.5, -1) is None
    assert step_target(np.empty(0), 0.0, 1) is None


def test_arrow_keys_choose_a_lane_and_step_its_events(qtbot: QtBot) -> None:
    lanes = TimelineOverview()
    qtbot.addWidget(lanes)
    lanes.resize(800, 120)
    lanes.set_bounds(0.0, 10.0)
    lanes.set_ttl_events([1.0, 3.0])
    lanes.set_gap_events([(6.0, "gap here")])
    lanes.show()
    lanes.setFocus()
    qtbot.waitUntil(lanes.hasFocus)
    seeks: list[float] = []
    lanes.seek_requested.connect(seeks.append)

    labels = lanes.lane_labels()
    gap_lane = labels.index("Data gaps")
    for _ in range(gap_lane):
        qtbot.keyClick(lanes, Qt.Key.Key_Down)
    qtbot.keyClick(lanes, Qt.Key.Key_Right)

    assert seeks == [6.0]
    assert "gap here" in lanes.accessible_value()

    for _ in range(gap_lane):
        qtbot.keyClick(lanes, Qt.Key.Key_Up)
    qtbot.keyClick(lanes, Qt.Key.Key_Left)

    assert seeks[-1] == 3.0
    qtbot.keyClick(lanes, Qt.Key.Key_Home)
    assert seeks[-1] == 0.0


def test_focused_lanes_keep_arrow_keys_from_window_shortcuts(qtbot: QtBot) -> None:
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtWidgets import QMainWindow

    window = QMainWindow()
    qtbot.addWidget(window)
    lanes = TimelineOverview()
    window.setCentralWidget(lanes)
    window.resize(800, 160)
    lanes.set_bounds(0.0, 10.0)
    lanes.set_ttl_events([1.0, 3.0])
    stepped: list[bool] = []
    step = QAction(window)
    step.setShortcut(QKeySequence(Qt.Key.Key_Right))
    step.triggered.connect(lambda: stepped.append(True))
    window.addAction(step)
    window.show()
    lanes.setFocus()
    qtbot.waitUntil(lanes.hasFocus)
    seeks: list[float] = []
    lanes.seek_requested.connect(seeks.append)

    qtbot.keyClick(lanes, Qt.Key.Key_Right)

    assert seeks == [1.0]
    assert stepped == []
