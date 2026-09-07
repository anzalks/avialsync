"""Fix Tracker: dragging a predicted point to where it belongs (D-099).

The interaction has three jobs and this file pins each one.  It must name the
frame the user is looking at, it must hand the correction to the command bus
rather than applying it, and it must give the pointer back to the video surface
the moment the gesture is not a grab.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from avialsync.core import point_edit_sidecar
from avialsync.core.point_edits import PointEditStore, PointKey, PointMove
from avialsync.ui import recovery
from avialsync.ui.controllers import corrections_controller
from avialsync.ui.main_window import MainWindow
from avialsync.ui.video_overlay import OverlayTrack, PaintCanvas

VIDEO_SIZE = (640, 480)
SOURCE = "/data/eks.csv"


class _PoseReader:
    """A pose channel with the same answers ``PyramidReader`` gives.

    Faithful on the point that matters here: ``sample_at`` reports the last
    sample at or before *t* while ``value_at`` rounds to the nearest one, so a
    test that scrubs between two frames can tell which of the two the overlay
    consulted.
    """

    def __init__(self, times: list[float], values: list[float], *, gaps: list[bool] | None = None):
        self.source_id = SOURCE
        self._t = np.asarray(times, dtype=np.float64)
        self._v = np.asarray(values, dtype=np.float64)
        self._gap = np.asarray(gaps if gaps is not None else [False] * len(times), dtype=bool)

    def coverage(self) -> tuple[float, float]:
        return float(self._t[0]), float(self._t[-1])

    def sample_at(self, t: float) -> tuple[int, float]:
        index = int(np.searchsorted(self._t, t, side="right")) - 1
        index = max(0, min(index, len(self._v) - 1))
        return index, float(self._v[index])

    def value_at(self, t: float) -> float:
        index = int(np.argmin(np.abs(self._t - t)))
        return float(self._v[index])

    def mapped_columns(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return self._t, self._v, self._gap


class _Host(QWidget):
    """Stands in for the pane: publishes a video size, owns no decoder."""

    def __init__(self) -> None:
        super().__init__()
        self.video_size = VIDEO_SIZE


def _canvas(qtbot, track: OverlayTrack, *, t: float = 0.0) -> PaintCanvas:
    host = _Host()
    qtbot.addWidget(host)
    host.resize(*VIDEO_SIZE)
    canvas = PaintCanvas(host)
    # pytest-qt registers widgets weakly, so the only strong reference to the
    # host is this local. Without the back-reference it is collected on return
    # and takes the canvas's C++ side with it.
    canvas.host = host
    canvas.resize(*VIDEO_SIZE)
    canvas.set_tracks([track])
    canvas.t = t
    return canvas


def _track(points: dict[str, tuple[_PoseReader, _PoseReader]]) -> OverlayTrack:
    return OverlayTrack(label="eks", points=points, is_ensemble=True)


def _one_point_track(xs: list[float], ys: list[float], times: list[float]) -> OverlayTrack:
    return _track({"nose": (_PoseReader(times, xs), _PoseReader(times, ys))})


def _mouse(kind: QEvent.Type, x: float, y: float, button, buttons) -> QMouseEvent:
    position = QPointF(x, y)
    return QMouseEvent(kind, position, position, button, buttons, Qt.KeyboardModifier.NoModifier)


def _press(canvas: PaintCanvas, x: float, y: float) -> None:
    canvas.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress, x, y, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton
        )
    )


def _release(canvas: PaintCanvas, x: float, y: float) -> None:
    canvas.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease, x, y, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
        )
    )


def _drag(canvas: PaintCanvas, start: tuple[float, float], end: tuple[float, float]) -> None:
    _press(canvas, *start)
    canvas.mouseMoveEvent(
        _mouse(QEvent.Type.MouseMove, *end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    )
    _release(canvas, *end)


# ── which sample is being corrected ──────────────────────────────────


def test_the_overlay_reads_the_sample_the_frame_is_showing(qtbot) -> None:
    """One authority names the frame (architecture rule 6).

    The pane shows the last frame whose presentation time is at or before *t*.
    ``value_at`` rounds to the *nearest* sample, so at 1.9 s it would hand back
    the coordinate belonging to the 2 s frame, which is not on screen. Harmless
    while the overlay only drew; wrong the moment a drag has to say which frame
    it corrected.
    """
    track = _one_point_track(xs=[10.0, 20.0, 30.0], ys=[10.0, 20.0, 30.0], times=[0.0, 1.0, 2.0])
    canvas = _canvas(qtbot, track, t=1.9)

    resolved = canvas._resolve(track)

    assert [(point.x, point.y) for point in resolved] == [(20.0, 20.0)]
    assert resolved[0].key == PointKey(SOURCE, "nose", 1)


def test_a_point_outside_its_source_s_coverage_is_not_drawn(qtbot) -> None:
    """``sample_at`` clamps into range; a pinned stale coordinate is a lie."""
    track = _one_point_track(xs=[10.0, 20.0], ys=[10.0, 20.0], times=[0.0, 1.0])
    canvas = _canvas(qtbot, track, t=30.0)

    assert canvas._resolve(track) == []


def test_a_point_inside_a_gap_is_not_drawn(qtbot) -> None:
    """A missing stretch must read as missing, exactly as ``value_at`` had it."""
    times = [0.0, 1.0, 2.0]
    track = _track(
        {
            "nose": (
                _PoseReader(times, [10.0, 20.0, 30.0], gaps=[False, True, False]),
                _PoseReader(times, [10.0, 20.0, 30.0], gaps=[False, True, False]),
            )
        }
    )
    canvas = _canvas(qtbot, track, t=1.0)

    assert canvas._resolve(track) == []


# ── the gesture ──────────────────────────────────────────────────────


def test_the_overlay_is_transparent_to_the_mouse_until_the_mode_is_on(qtbot) -> None:
    """Off, the canvas must not intercept anything the video surface wants."""
    canvas = _canvas(qtbot, _one_point_track([100.0], [100.0], [0.0]))
    attribute = Qt.WidgetAttribute.WA_TransparentForMouseEvents

    assert canvas.testAttribute(attribute) is True

    canvas.set_edit_mode(True)
    assert canvas.testAttribute(attribute) is False

    canvas.set_edit_mode(False)
    assert canvas.testAttribute(attribute) is True


def test_a_drag_reports_the_point_and_the_frame_it_corrected(qtbot) -> None:
    canvas = _canvas(
        qtbot,
        _one_point_track(xs=[10.0, 100.0], ys=[10.0, 100.0], times=[0.0, 1.0]),
        t=1.0,
    )
    canvas.set_edit_mode(True)
    moves: list[PointMove] = []
    canvas.point_moved.connect(moves.append)

    _drag(canvas, (100.0, 100.0), (250.0, 180.0))

    assert len(moves) == 1
    assert moves[0].key == PointKey(SOURCE, "nose", 1)
    assert moves[0].before is None
    assert moves[0].after == (250.0, 180.0)


def test_a_drag_carries_the_override_it_replaced(qtbot) -> None:
    """Undo has to return to the previous correction, not to the prediction."""
    store = PointEditStore()
    store.set(PointKey(SOURCE, "nose", 0), (200.0, 200.0))
    canvas = _canvas(qtbot, _one_point_track([10.0], [10.0], [0.0]))
    canvas.set_point_edits(store)
    canvas.set_edit_mode(True)
    moves: list[PointMove] = []
    canvas.point_moved.connect(moves.append)

    _drag(canvas, (200.0, 200.0), (300.0, 220.0))

    assert moves[0].before == (200.0, 200.0)
    assert moves[0].after == (300.0, 220.0)


def test_the_canvas_never_writes_to_the_store_itself(qtbot) -> None:
    """Rule 14: the mutation is the command bus's to make, not a widget's."""
    store = PointEditStore()
    canvas = _canvas(qtbot, _one_point_track([100.0], [100.0], [0.0]))
    canvas.set_point_edits(store)
    canvas.set_edit_mode(True)

    _drag(canvas, (100.0, 100.0), (250.0, 180.0))

    assert len(store) == 0


def test_a_click_that_misses_every_point_starts_no_drag(qtbot) -> None:
    canvas = _canvas(qtbot, _one_point_track([100.0], [100.0], [0.0]))
    canvas.set_edit_mode(True)
    moves: list[PointMove] = []
    canvas.point_moved.connect(moves.append)

    _drag(canvas, (500.0, 400.0), (505.0, 405.0))

    assert moves == []


def test_a_drag_that_ends_where_it_started_is_not_an_edit(qtbot) -> None:
    """Re-placing a correction exactly must not add an undo step that does nothing."""
    store = PointEditStore()
    store.set(PointKey(SOURCE, "nose", 0), (100.0, 100.0))
    canvas = _canvas(qtbot, _one_point_track([10.0], [10.0], [0.0]))
    canvas.set_point_edits(store)
    canvas.set_edit_mode(True)
    moves: list[PointMove] = []
    canvas.point_moved.connect(moves.append)

    _press(canvas, 100.0, 100.0)
    _release(canvas, 100.0, 100.0)

    assert moves == []


def test_a_dragged_point_cannot_be_placed_outside_the_frame(qtbot) -> None:
    """A coordinate off the image is not a coordinate the footage can support."""
    canvas = _canvas(qtbot, _one_point_track([100.0], [100.0], [0.0]))
    canvas.set_edit_mode(True)
    moves: list[PointMove] = []
    canvas.point_moved.connect(moves.append)

    _drag(canvas, (100.0, 100.0), (5000.0, -40.0))

    assert moves[0].after == (float(VIDEO_SIZE[0]), 0.0)


def test_a_point_with_no_source_identity_cannot_be_corrected(qtbot) -> None:
    """The loose-reader path has nothing stable to key a correction to."""

    class _Anonymous(_PoseReader):
        def __init__(self) -> None:
            super().__init__([0.0], [100.0])
            self.source_id = ""

    canvas = _canvas(qtbot, _track({"nose": (_Anonymous(), _Anonymous())}))
    canvas.set_edit_mode(True)
    moves: list[PointMove] = []
    canvas.point_moved.connect(moves.append)

    _drag(canvas, (100.0, 100.0), (200.0, 200.0))

    assert canvas.point_at(100.0, 100.0) is None
    assert moves == []


# ── the pane the canvas sits in ──────────────────────────────────────


def test_the_pane_hands_the_pointer_over_only_in_edit_mode(qtbot) -> None:
    """The stacking order is load-bearing, so it is pinned rather than assumed.

    Four widgets share one grid cell: the surface, the paint canvas, the label
    overlay, and the zoom controls. Off, the canvas is transparent to the mouse
    and the surface answers; on, the canvas must be the one Qt hits, or the
    drag never starts.
    """
    from avialsync.ui.video_pane import VideoPane

    pane = VideoPane()
    qtbot.addWidget(pane)
    pane.resize(320, 240)
    pane.show()
    qtbot.waitExposed(pane)

    centre = pane.rect().center()
    assert pane.childAt(centre) is pane.surface

    pane.set_point_edit_mode(True)
    assert pane.childAt(centre) is pane.paint_canvas

    pane.set_point_edit_mode(False)
    assert pane.childAt(centre) is pane.surface


def test_a_marker_under_the_timecode_is_still_reachable(qtbot) -> None:
    """The chrome labels are readouts, and each was its own dead zone.

    ``overlay`` is transparent to the mouse but the attribute is per widget, so
    the camera name and the timecode swallowed clicks over themselves -- which
    also meant double-click fullscreen never worked in those corners.
    """
    from avialsync.ui.video_pane import VideoPane

    pane = VideoPane()
    qtbot.addWidget(pane)
    pane.resize(320, 240)
    pane.set_label("cam1.mp4")
    pane.show()
    qtbot.waitExposed(pane)

    over_the_name = pane.lbl_name.geometry().center()
    over_the_timecode = pane.lbl_osd.geometry().center()

    assert pane.childAt(over_the_name) is pane.surface
    assert pane.childAt(over_the_timecode) is pane.surface

    pane.set_point_edit_mode(True)

    assert pane.childAt(over_the_name) is pane.paint_canvas
    assert pane.childAt(over_the_timecode) is pane.paint_canvas


def test_zooming_still_reaches_the_video_while_correcting(qtbot) -> None:
    """Edit mode takes the pointer; it must not take zoom and pan with it."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QWheelEvent

    from avialsync.ui.video_pane import VideoPane

    pane = VideoPane()
    qtbot.addWidget(pane)
    pane.resize(320, 240)
    pane.surface.set_video_size(*VIDEO_SIZE)
    pane.set_point_edit_mode(True)

    position = QPointF(160.0, 120.0)
    pane.paint_canvas.wheelEvent(
        QWheelEvent(
            position,
            position,
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
    )

    assert pane.surface.frame_geometry() is not None
    assert pane.surface._zoom > 1.0


# ── what is drawn ────────────────────────────────────────────────────


def test_a_correction_moves_the_marker_it_corrected(qtbot) -> None:
    store = PointEditStore()
    canvas = _canvas(qtbot, _one_point_track([10.0], [10.0], [0.0]))
    canvas.set_point_edits(store)

    store.set(PointKey(SOURCE, "nose", 0), (300.0, 220.0))
    resolved = canvas._resolve(canvas.tracks[0])

    assert [(point.x, point.y) for point in resolved] == [(300.0, 220.0)]
    assert resolved[0].corrected is True


def _painted_pixels(canvas: PaintCanvas) -> int:
    """Render the overlay off-screen and count what it actually put down."""
    from PySide6.QtGui import QImage

    image = QImage(*VIDEO_SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    canvas.render(image)
    bits = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(-1, 4)
    return int(np.count_nonzero(bits[:, 3]))


def test_edit_mode_shows_the_points_even_when_the_layer_is_off(qtbot) -> None:
    """A mode whose purpose is grabbing markers must not start with none drawn."""
    canvas = _canvas(qtbot, _one_point_track([100.0], [100.0], [0.0]))
    canvas.set_points_visible(False)

    assert _painted_pixels(canvas) == 0

    canvas.set_edit_mode(True)

    assert _painted_pixels(canvas) > 0


# ── the window ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolated_recovery_dir(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    yield target


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    if isValid(win):
        win.close()


def test_the_menu_entry_and_the_button_are_the_same_action(window: MainWindow) -> None:
    """Rule 15: a menu item and its button may not be named independently."""
    action = window._act_fix_tracker
    button = window.transport.evidence.fix_tracker_button

    assert button.defaultAction() is action
    assert button.text() == action.text()
    assert action.isCheckable()


def test_the_toggle_reaches_every_pane(window: MainWindow) -> None:
    window._act_fix_tracker.setChecked(True)
    assert window.video_grid.point_edit_mode is True

    window._act_fix_tracker.setChecked(False)
    assert window.video_grid.point_edit_mode is False


def test_turning_the_mode_on_stops_playback(window: MainWindow) -> None:
    """A marker being aimed at is somewhere else by the time the button lands."""
    window.transport.play_toggled.emit(True)
    assert window.clock.state.playing is True

    window._act_fix_tracker.setChecked(True)

    assert window.clock.state.playing is False


def test_a_drag_becomes_one_undoable_correction(window: MainWindow) -> None:
    key = PointKey(SOURCE, "nose", 120)

    window.video_grid.point_moved.emit(PointMove(key=key, before=None, after=(12.0, 34.0)))

    assert window.point_edits.get(key) == (12.0, 34.0)
    assert window.document.is_dirty is True
    assert window.document.undo_label() == "Move nose to (12.0, 34.0) px at frame 120"

    window.document.undo(window._mutations)
    assert window.point_edits.get(key) is None


# ── sample index versus video frame ──────────────────────────────────


def _register_pose_source(window, source_id: str, times: list[float], rate: float) -> None:
    """Register a 2D pose source the way the import path does."""
    reader = _PoseReader(times, [0.0] * len(times))
    reader.source_id = source_id
    window._overlay_sources.setdefault("cam.mp4", {})[source_id] = {
        "label": "eks",
        "is_ensemble": True,
        "points": {"nose": (_Sourced(reader), _Sourced(reader))},
        "frame_rate": rate,
    }


class _Sourced:
    """A MappedChannelReader stand-in exposing ``source_reader``."""

    def __init__(self, reader: _PoseReader) -> None:
        self.source_reader = reader
        self.source_id = reader.source_id


def test_a_contiguous_pose_file_indexes_by_frame(window: MainWindow) -> None:
    """The common case, and the reason the difference stays invisible."""
    _register_pose_source(window, SOURCE, [0.0, 0.1, 0.2, 0.3], rate=10.0)

    assert corrections_controller.frame_for(window, SOURCE, 2) == 2
    assert corrections_controller.index_for(window, SOURCE, 2) == 2


def test_a_pose_file_that_starts_later_does_not(window: MainWindow) -> None:
    """A file covering only frames 100-103: sample 0 is frame 100, not frame 0.

    The sidecar, the corrected CSV and DLC's labeled data all speak video frame
    numbers, so writing the sample index into them would put every correction a
    hundred frames early.
    """
    _register_pose_source(window, SOURCE, [10.0, 10.1, 10.2, 10.3], rate=10.0)

    assert corrections_controller.frame_for(window, SOURCE, 0) == 100
    assert corrections_controller.frame_for(window, SOURCE, 3) == 103
    assert corrections_controller.index_for(window, SOURCE, 103) == 3


def test_a_frame_the_pose_file_does_not_cover_is_refused(window: MainWindow) -> None:
    """Landing it on the nearest row would move the point to another moment."""
    _register_pose_source(window, SOURCE, [10.0, 10.1, 10.2], rate=10.0)

    assert corrections_controller.index_for(window, SOURCE, 500) is None


def test_an_unregistered_source_falls_back_to_the_index(window: MainWindow) -> None:
    """The right answer for a contiguous file, and the only one available."""
    assert corrections_controller.frame_for(window, "/nowhere.csv", 7) == 7
    assert corrections_controller.index_for(window, "/nowhere.csv", 7) == 7


def test_a_correction_is_written_at_the_video_frame_it_names(
    window: MainWindow, tmp_path
) -> None:
    pose = _pose_file(tmp_path)
    _register_pose_source(window, str(pose), [10.0, 10.1, 10.2, 10.3], rate=10.0)

    window.video_grid.point_moved.emit(
        PointMove(key=PointKey(str(pose), "nose", 1), before=None, after=(5.0, 6.0))
    )

    written = point_edit_sidecar.read(pose)
    assert written is not None
    assert [entry.frame for entry in written.entries] == [101]
    assert window.document.undo_label() == "Move nose to (5.0, 6.0) px at frame 101"


def test_reopening_puts_the_correction_back_on_the_same_sample(
    window: MainWindow, tmp_path
) -> None:
    """Frame on disk, sample index in memory -- the round trip has to close."""
    pose = _pose_file(tmp_path)
    _register_pose_source(window, str(pose), [10.0, 10.1, 10.2, 10.3], rate=10.0)
    point_edit_sidecar.write(
        pose, [point_edit_sidecar.Correction(frame=101, bodypart="nose", x=5.0, y=6.0)]
    )

    window._adopt_point_edits(str(pose))

    assert window.point_edits.get(PointKey(str(pose), "nose", 1)) == (5.0, 6.0)


def test_a_correction_naming_an_absent_frame_is_left_out_and_reported(
    window: MainWindow, tmp_path
) -> None:
    pose = _pose_file(tmp_path)
    _register_pose_source(window, str(pose), [10.0, 10.1, 10.2], rate=10.0)
    point_edit_sidecar.write(
        pose, [point_edit_sidecar.Correction(frame=9000, bodypart="nose", x=5.0, y=6.0)]
    )

    window._adopt_point_edits(str(pose))

    assert window.point_edits.count_for(str(pose)) == 0
    assert "not in" in window.notifications.message


# ── where a correction is kept ───────────────────────────────────────


def _pose_file(tmp_path) -> Path:
    path = tmp_path / "eks.csv"
    path.write_text("scorer,a,b\nbodyparts,nose,nose\ncoords,x,y\n0,1.0,2.0\n")
    return path


def test_a_correction_is_written_beside_its_pose_file(window: MainWindow, tmp_path) -> None:
    """A correction is a fact about the recording, so it lives with it (D-099).

    Not on Ctrl+S: two hundred careful drags are collected data, and leaving
    them in RAM until somebody remembers to save is the wrong default for work
    that cannot be regenerated.
    """
    pose = _pose_file(tmp_path)
    key = PointKey(str(pose), "nose", 120)

    window.video_grid.point_moved.emit(PointMove(key=key, before=None, after=(12.5, 34.5)))

    written = point_edit_sidecar.read(pose)
    assert written is not None
    assert [(e.frame, e.bodypart, e.x, e.y) for e in written.entries] == [(120, "nose", 12.5, 34.5)]
    assert "eks.csv" in window.notifications.message


def test_undoing_a_correction_reaches_the_file_too(window: MainWindow, tmp_path) -> None:
    """Undo is a correction like any other, and takes the same route to disk."""
    pose = _pose_file(tmp_path)
    key = PointKey(str(pose), "nose", 120)
    window.video_grid.point_moved.emit(PointMove(key=key, before=None, after=(12.5, 34.5)))

    window.document.undo(window._mutations)

    written = point_edit_sidecar.read(pose)
    assert written is not None
    assert written.entries == [], "the file is emptied, never deleted"
    assert point_edit_sidecar.sidecar_path(pose).exists()


def test_the_session_records_a_count_not_the_coordinates(window: MainWindow, tmp_path) -> None:
    """One authority. The count is what makes a lost sidecar reportable."""
    pose = _pose_file(tmp_path)
    key = PointKey(str(pose), "nose", 120)
    window.video_grid.point_moved.emit(PointMove(key=key, before=None, after=(12.5, 34.5)))

    state = window._build_session_state()

    assert state.point_edits == [{"source": str(pose), "count": 1, "storage": "sidecar"}]


def test_a_folder_that_cannot_be_written_keeps_the_work_in_the_session(
    window: MainWindow, tmp_path
) -> None:
    """An archived acquisition on read-only media is the ordinary case."""
    missing = tmp_path / "not-a-folder" / "eks.csv"
    key = PointKey(str(missing), "nose", 120)

    window.video_grid.point_moved.emit(PointMove(key=key, before=None, after=(12.5, 34.5)))

    state = window._build_session_state()
    assert state.point_edits[0]["storage"] == "session"
    assert state.point_edits[0]["edits"] == [
        {"source": str(missing), "point": "nose", "index": 120, "x": 12.5, "y": 34.5}
    ]
    assert "could not be written" in window.notifications.message


def test_opening_the_pose_file_again_brings_its_corrections(window: MainWindow, tmp_path) -> None:
    """The whole point of the sidecar: corrections outlive the session."""
    pose = _pose_file(tmp_path)
    point_edit_sidecar.write(
        pose, [point_edit_sidecar.Correction(frame=120, bodypart="nose", x=12.5, y=34.5)]
    )

    window._adopt_point_edits(str(pose))

    assert window.point_edits.get(PointKey(str(pose), "nose", 120)) == (12.5, 34.5)


def test_a_session_expecting_more_corrections_than_it_finds_says_so(
    window: MainWindow, tmp_path
) -> None:
    """Silently showing fewer points than the user left behind is the failure."""
    pose = _pose_file(tmp_path)
    point_edit_sidecar.write(
        pose, [point_edit_sidecar.Correction(frame=120, bodypart="nose", x=12.5, y=34.5)]
    )
    corrections_controller.restore_manifest(
        window, [{"source": str(pose), "count": 47, "storage": "sidecar"}]
    )

    window._adopt_point_edits(str(pose))

    assert "47" in window.notifications.message
    assert window.point_edits.count_for(str(pose)) == 1, "what survives is still shown"


def test_a_session_whose_corrections_file_is_gone_says_so(window: MainWindow, tmp_path) -> None:
    pose = _pose_file(tmp_path)
    corrections_controller.restore_manifest(
        window, [{"source": str(pose), "count": 47, "storage": "sidecar"}]
    )

    window._adopt_point_edits(str(pose))

    assert "no corrections file" in window.notifications.message


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
