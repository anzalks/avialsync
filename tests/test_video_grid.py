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
        point_moved = Signal(object)

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
        point_moved = Signal(object)

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


class _RecordingPane(QWidget):
    """A pane that records what the grid handed it, without opening media."""

    double_clicked = Signal(object)
    right_clicked = Signal(object)
    file_loaded = Signal()
    point_moved = Signal(object)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.overlay_tracks: list = []
        self.tracking_readers: list = []
        self.point_edits: object | None = None
        self.point_edit_mode = False

    def open(self, _path: str) -> None:
        self.file_loaded.emit()

    def set_label(self, _label: str) -> None:
        return

    def set_overlay_tracks(self, tracks: list) -> None:
        self.overlay_tracks = tracks

    def set_tracking_readers(self, readers: list) -> None:
        self.tracking_readers = readers

    def set_point_edits(self, edits: object) -> None:
        self.point_edits = edits

    def set_point_edit_mode(self, enabled: bool) -> None:
        self.point_edit_mode = enabled


def test_overlay_tracks_wait_for_a_pane_that_does_not_exist_yet(monkeypatch, qtbot) -> None:
    """Pose data resolves before later cameras have panes; it must not be lost.

    Panes are built one at a time and each demuxes its whole file first, so on a
    multi-camera session every camera after the first had its 2D overlay
    resolved while it had no pane. The tracks were dropped and never re-offered,
    which is why only the first video was ever painted.
    """
    monkeypatch.setattr(video_grid, "VideoPane", _RecordingPane)
    grid = video_grid.VideoGrid()
    qtbot.addWidget(grid)

    face_tracks = ["face-eks"]
    side_tracks = ["side-eks"]
    grid.set_overlay_tracks("FaceCam.mp4", face_tracks)
    grid.set_overlay_tracks("SideCam.mp4", side_tracks)

    face_pane = grid.add_pane("FaceCam.mp4")
    side_pane = grid.add_pane("SideCam.mp4")

    assert face_pane.overlay_tracks == face_tracks
    assert side_pane.overlay_tracks == side_tracks


def test_each_camera_keeps_only_its_own_held_tracks(monkeypatch, qtbot) -> None:
    """Holding tracks must not turn into broadcasting them."""
    monkeypatch.setattr(video_grid, "VideoPane", _RecordingPane)
    grid = video_grid.VideoGrid()
    qtbot.addWidget(grid)

    grid.set_overlay_tracks("FaceCam.mp4", ["face-eks"])

    face_pane = grid.add_pane("FaceCam.mp4")
    side_pane = grid.add_pane("SideCam.mp4")

    assert face_pane.overlay_tracks == ["face-eks"]
    assert side_pane.overlay_tracks == []


def test_broadcast_tracking_readers_reach_a_later_pane(monkeypatch, qtbot) -> None:
    """The loose-reader path has the same ordering hazard as named tracks."""
    monkeypatch.setattr(video_grid, "VideoPane", _RecordingPane)
    grid = video_grid.VideoGrid()
    qtbot.addWidget(grid)

    early = grid.add_pane("FaceCam.mp4")
    grid.set_tracking_readers(["reader"])
    late = grid.add_pane("SideCam.mp4")

    assert early.tracking_readers == ["reader"]
    assert late.tracking_readers == ["reader"]


def test_removing_a_camera_releases_its_held_tracks(monkeypatch, qtbot) -> None:
    """Held tracks own readers over mmap'd pyramids; a removed pane frees them."""
    monkeypatch.setattr(video_grid, "VideoPane", _RecordingPane)
    grid = video_grid.VideoGrid()
    qtbot.addWidget(grid)

    grid.set_overlay_tracks("FaceCam.mp4", ["face-eks"])
    grid.add_pane("FaceCam.mp4")
    grid.remove_pane("FaceCam.mp4")

    assert grid.add_pane("FaceCam.mp4").overlay_tracks == []


def test_a_pane_built_later_opens_in_the_grid_s_edit_state(monkeypatch, qtbot) -> None:
    """Fix Tracker is the grid's mode, so a camera that arrives late joins it.

    Panes are built one at a time and each demuxes its whole file first, so on a
    multi-camera session the later cameras appear well after the user turned the
    mode on. Without this they would come up read-only and the same drag would
    work on one pane and do nothing on the next.
    """
    from avialsync.core.point_edits import PointEditStore

    monkeypatch.setattr(video_grid, "VideoPane", _RecordingPane)
    grid = video_grid.VideoGrid()
    qtbot.addWidget(grid)

    store = PointEditStore()
    grid.set_point_edits(store)
    grid.set_point_edit_mode(True)

    late = grid.add_pane("SideCam.mp4")

    assert late.point_edits is store
    assert late.point_edit_mode is True


def test_leaving_edit_mode_reaches_every_pane(monkeypatch, qtbot) -> None:
    monkeypatch.setattr(video_grid, "VideoPane", _RecordingPane)
    grid = video_grid.VideoGrid()
    qtbot.addWidget(grid)

    first = grid.add_pane("FaceCam.mp4")
    second = grid.add_pane("SideCam.mp4")
    grid.set_point_edit_mode(True)
    grid.set_point_edit_mode(False)

    assert grid.point_edit_mode is False
    assert [first.point_edit_mode, second.point_edit_mode] == [False, False]
