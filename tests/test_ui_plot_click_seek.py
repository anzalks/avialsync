"""Tests for exact master-time seeking from plotted data."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, Qt

from avialsync.core.pyramid import PyramidBuilder
from avialsync.ui.main_window import MainWindow


class _PlotClick:
    """Small pyqtgraph scene-click stand-in for the interaction controller."""

    def __init__(self, scene_pos: QPointF) -> None:
        self._scene_pos = scene_pos
        self.accepted = False

    def button(self) -> Qt.MouseButton:
        return Qt.MouseButton.LeftButton

    def scenePos(self) -> QPointF:
        return self._scene_pos

    def accept(self) -> None:
        self.accepted = True


def test_clicking_a_plot_seeks_the_shared_master_clock(qtbot, tmp_path: Path) -> None:
    """A data-row click selects its absolute time, not just the displayed page."""
    times = np.linspace(100.0, 140.0, 4001)
    PyramidBuilder(tmp_path, "signal").build_and_save(times, np.sin(times))

    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.show()
    window.clock.set_bounds(100.0, 140.0)
    window.plot_pane.set_timeline_bounds(100.0, 140.0)
    window.plot_pane.load_channels(tmp_path, ["signal"])
    window.plot_pane.wait_for_pending_rows()
    window.plot_pane.set_cursor(101.0)

    channel = window.plot_pane.channels[0]
    click = _PlotClick(channel.plot_item.vb.mapViewToScene(QPointF(1.5, 0.0)))
    window.plot_pane._interactions.on_scene_clicked(click)

    assert click.accepted
    assert window.clock.state.t == 101.5
