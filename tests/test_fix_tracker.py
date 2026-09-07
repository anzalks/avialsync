"""Fix Tracker: dragging a predicted point to where it belongs (D-099).

The interaction has three jobs and this file pins each one.  It must name the
frame the user is looking at, it must hand the correction to the command bus
rather than applying it, and it must give the pointer back to the video surface
the moment the gesture is not a grab.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from avialsync.core.point_edits import PointEditStore, PointKey, PointMove
from avialsync.ui import recovery
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


def test_a_correction_is_written_into_the_session(window: MainWindow) -> None:
    """Without this the dirty flag would promise work the save silently drops."""
    key = PointKey(SOURCE, "nose", 120)
    window.video_grid.point_moved.emit(PointMove(key=key, before=None, after=(12.0, 34.0)))

    state = window._build_session_state()

    assert state.point_edits == [
        {"source": SOURCE, "point": "nose", "index": 120, "x": 12.0, "y": 34.0}
    ]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
