"""View -> Fit All Videos: every camera back to 1.00x, x 0, y 0, from one click."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF
from shiboken6 import isValid

from avialsync.ui.main_window import MainWindow
from avialsync.ui.video_pane import VideoSurface


@pytest.fixture
def window(qapp, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    if isValid(win):
        win.close()


def _zoomed_surface(window: MainWindow) -> VideoSurface:
    surface = VideoSurface(window)
    surface.resize(320, 180)
    surface.set_video_size(640, 360)
    surface.zoom_by(2.5, QPointF(40.0, 30.0))
    surface.pan_by(QPointF(-25.0, 12.0))
    assert surface.view_readout() != "1.00×  x +0  y +0"
    return surface


def test_fit_all_videos_is_greyed_until_a_video_is_open(window: MainWindow) -> None:
    button = window.transport.evidence.fit_videos_button
    assert button.text() == window._act_fit_videos.text() == "Fit All Videos"
    assert not button.isEnabled()
    assert "no videos" in button.toolTip()


def test_fit_all_videos_button_resets_every_camera(window: MainWindow, monkeypatch) -> None:
    surfaces = [_zoomed_surface(window), _zoomed_surface(window)]
    monkeypatch.setattr(window.video_grid, "panes", [SimpleNamespace(surface=s) for s in surfaces])
    monkeypatch.setattr(window.video_grid, "pane_paths", lambda: ["/rec/a.mp4", "/rec/b.mp4"])
    window._refresh_action_availability()
    button = window.transport.evidence.fit_videos_button
    assert button.isEnabled()

    button.click()

    assert [s.view_readout() for s in surfaces] == ["1.00×  x +0  y +0"] * 2


def test_fit_all_videos_has_its_shortcut(window: MainWindow) -> None:
    assert window._act_fit_videos.shortcut().toString() == "Ctrl+Shift+0"
