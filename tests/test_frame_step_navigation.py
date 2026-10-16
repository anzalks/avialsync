"""Frame navigation follows real input through accepted camera time mappings."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from avialsync.ui.main_window import MainWindow


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("playing", [False, True])
def test_arrows_advance_the_chosen_frame_after_another_camera_has_exact_sync(
    qtbot: QtBot, selected: bool, playing: bool
) -> None:
    """A generic exact seek must not snap a frame step back onto another camera."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    paths = [Path(f"tests/fixtures/videos/camera_{i}.mp4").resolve() for i in (1, 2)]
    for path in paths:
        window._load_video(path)
    try:
        qtbot.waitUntil(
            lambda: all(str(path) in window._video_frame_times for path in paths), timeout=15000
        )
        pane_paths = window.video_grid.pane_paths()
        first = window.video_grid.panes[pane_paths.index(str(paths[0]))]
        chosen = window.video_grid.panes[pane_paths.index(str(paths[1]))]
        first_times = window._video_frame_times[str(paths[0])]
        first.time_map.set_exact_mapping(first_times * 4, first_times)
        chosen_times = window._video_frame_times[str(paths[1])]
        window.clock.set_bounds(0.0, float(chosen_times[-1]))
        if selected:
            edit = window.transport._time_edit
            edit.setFocus()
            edit.setModified(True)
            qtbot.mouseClick(chosen.surface, Qt.MouseButton.LeftButton)
            assert window._selected_video_path == str(paths[1])
            assert not edit.hasFocus(), "a picture click must release the editor's caret keys"
            qtbot.waitUntil(chosen.hasFocus)
            key_target = chosen
        else:
            window._selected_video_path = None
            chosen.paint_canvas.setFocus()
            qtbot.waitUntil(chosen.paint_canvas.hasFocus)
            key_target = chosen.paint_canvas
        start = 1 if playing else 0
        window.clock.seek(float(chosen_times[start]))
        if playing:
            window.clock.play()
        steps: list[int] = []
        window.transport.frame_step_requested.connect(steps.append)

        for index in range(start + 1, start + 4):
            qtbot.keyClick(key_target, Qt.Key.Key_Right)
            assert steps[-1] == 1, "the shortcut must reach frame stepping"
            assert not window.clock.state.playing
            assert window.clock.state.t == pytest.approx(chosen_times[index])
            assert chosen.frame_record_at(window.clock.state.t)[0] == index
        for index in range(start + 2, start - 1, -1):
            qtbot.keyClick(key_target, Qt.Key.Key_Left)
            assert steps[-1] == -1
            assert window.clock.state.t == pytest.approx(chosen_times[index])
            assert chosen.frame_record_at(window.clock.state.t)[0] == index
    finally:
        window.close()
