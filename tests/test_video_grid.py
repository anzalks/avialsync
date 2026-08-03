"""Video-grid native lifecycle tests."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from avialsync.ui import video_grid


def test_file_loaded_callback_is_connected_before_playback(monkeypatch, qapp) -> None:
    """Tiny media may load synchronously; the readiness event must not be lost."""
    events: list[str] = []

    class _ImmediatePane(QWidget):
        double_clicked = Signal(object)
        right_clicked = Signal(object)
        file_loaded = Signal()

        def __init__(self, parent: QWidget) -> None:
            super().__init__(parent)

        def open(self, _path: str) -> None:
            events.append("open")
            self.file_loaded.emit()

        def set_label(self, _label: str) -> None:
            return

    monkeypatch.setattr(video_grid, "VideoPane", _ImmediatePane)
    grid = video_grid.VideoGrid()

    grid.add_pane(
        "camera.mp4",
        on_file_loaded=lambda: events.append("ready"),
    )

    assert events == ["open", "ready"]
    assert grid.pane_paths() == ["camera.mp4"]


def test_unchecked_video_stays_hidden_through_relayout(monkeypatch, qtbot) -> None:
    """Grid/fullscreen layout changes must not override the sidebar checkbox."""

    class _Pane(QWidget):
        double_clicked = Signal(object)
        right_clicked = Signal(object)
        file_loaded = Signal()

        def __init__(self, parent: QWidget) -> None:
            super().__init__(parent)

        def open(self, _path: str) -> None:
            self.file_loaded.emit()

        def set_label(self, _label: str) -> None:
            return

    monkeypatch.setattr(video_grid, "VideoPane", _Pane)
    grid = video_grid.VideoGrid()
    qtbot.addWidget(grid)
    first = grid.add_pane("first.mp4")
    second = grid.add_pane("second.mp4")

    grid.set_pane_visible("first.mp4", False)
    grid.set_grid_mode(True)
    grid.toggle_fullscreen("second.mp4")
    grid.toggle_fullscreen("second.mp4")

    assert first.isHidden()
    assert not second.isHidden()
    assert grid.visible_panes() == [second]
