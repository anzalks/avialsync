"""Removing a video persists the session before the media client is torn down.

Tearing down a libmpv client can take the whole process with it on Windows
(HANDOUT.md "Pending"). At close that costs nothing, because the autosave has
already run. Mid-session it would cost everything since the last autosave, which
is up to the two-minute timer.

So the order matters, and it is what these pin: the grid drops the pane from its
model, the session is written as it will be, and only then is `close()` called.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QWidget

from avialsync.ui.main_window import MainWindow
from avialsync.ui.video_grid import VideoGrid


class _FakePane(QWidget):
    """A real widget the grid's layout accepts, minus libmpv.

    A plain object cannot stand in here: `remove_pane` hands the pane to
    `QLayout.removeWidget`, which rejects anything that is not a QWidget.
    """

    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self._order = order
        self.closed = False

    def close(self) -> bool:  # noqa: D102 - overrides QWidget.close
        self.closed = True
        self._order.append("closed")
        return True

    def set_label(self, _label: str) -> None:
        return


def test_detach_is_announced_before_the_pane_is_closed(qtbot) -> None:
    """The signal is useless if it arrives after the teardown it guards."""
    grid = VideoGrid()
    qtbot.addWidget(grid)
    order: list[str] = []
    pane = _FakePane(order)
    grid.panes = [pane]
    grid._paths = ["camera.mp4"]
    grid._pane_enabled = [True]
    grid.pane_detached.connect(lambda _p: order.append("detached"))

    grid.remove_pane("camera.mp4")

    assert order == ["detached", "closed"], order


def test_the_pane_is_gone_from_the_model_when_detach_fires(qtbot) -> None:
    """A snapshot taken here must describe the session without this video."""
    grid = VideoGrid()
    qtbot.addWidget(grid)
    seen: list[list[str]] = []
    grid.panes = [_FakePane([]), _FakePane([])]
    grid._paths = ["a.mp4", "b.mp4"]
    grid._pane_enabled = [True, True]
    grid.pane_detached.connect(lambda _p: seen.append(list(grid._paths)))

    grid.remove_pane("a.mp4")

    assert seen == [["b.mp4"]], seen


@pytest.fixture
def window(qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.close()


def test_removing_a_video_writes_the_session_first(window, tmp_path: Path, qtbot) -> None:
    """End to end: the file on disk is correct before teardown could crash."""
    session = tmp_path / "s.avv"
    window._session_path = session

    order: list[str] = []
    pane = _FakePane(order)
    window.video_grid.panes = [pane]
    window.video_grid._paths = ["camera.mp4"]
    window.video_grid._pane_enabled = [True]
    window.video_grid.pane_detached.connect(
        lambda _p: order.append("written" if session.exists() else "missing")
    )

    window._on_video_remove_requested("camera.mp4")

    assert session.exists(), "the session was never written"
    assert order[-1] == "closed", order
    saved = json.loads(session.read_text(encoding="utf-8"))
    assert [entry["path"] for entry in saved["videos"]] == [], (
        "the snapshot still lists the video the user just removed"
    )


def test_no_session_open_means_nothing_is_written(window, qtbot) -> None:
    """Removal must not invent a session file for someone who never saved one."""
    window._session_path = None
    pane = _FakePane([])
    window.video_grid.panes = [pane]
    window.video_grid._paths = ["camera.mp4"]
    window.video_grid._pane_enabled = [True]

    window._on_video_remove_requested("camera.mp4")

    assert pane.closed
