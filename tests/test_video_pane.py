"""Video-pane construction, decoding, and teardown tests.

Everything here used to be about libmpv: which of three render paths a platform
took, and the ordering dance needed to stop an event thread that outlived the
widget. D-075 deleted all of it. What replaced those tests are the properties
that matter for a pane that decodes for itself — that it renders one way
everywhere, that decoding never runs on the UI thread, that requests coalesce
instead of queueing, and that the thread it owns is stopped by the pane that
started it.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QCloseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QPushButton

from avialsync.ui import video_pane
from tests.util_framestrip import decode_frame_strip
from tests.util_pyav_fixtures import cfr_times, write_video

pytest.importorskip("av")

FPS = 30.0
FRAME_COUNT = 90


@pytest.fixture(scope="module")
def clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("pane") / "clip.mp4"
    write_video(path, frame_times=cfr_times(FRAME_COUNT), gop_size=15)
    return path


def _opened_pane(clip: Path, qtbot) -> video_pane.VideoPane:
    pane = video_pane.VideoPane()
    qtbot.addWidget(pane)
    pane.open(str(clip))
    qtbot.waitUntil(lambda: pane.has_media, timeout=5000)
    return pane


# ── One rendering path, everywhere ────────────────────────────────────


def test_the_pane_renders_the_same_way_on_every_platform(qapp: QApplication) -> None:
    """No render context, no ``wid`` embedding, no headless special case.

    The three-way fork was the highest-risk integration surface in the project
    and the reason video bugs were platform-specific. Constructing a pane must
    now touch nothing platform-dependent at all.
    """
    pane = video_pane.VideoPane()
    try:
        assert pane.surface is not None
        assert not hasattr(pane, "gl_widget")
        assert not hasattr(pane, "video_container")
        assert not hasattr(pane, "mpv")
    finally:
        pane.close()


def test_a_pane_with_no_media_still_builds_its_chrome(qapp: QApplication) -> None:
    """A pane is usable before anything is opened in it.

    ``__init__`` used to abort early when libmpv was missing, leaving a pane
    whose every later call raised AttributeError. There is no such early return
    now, but the call sequence is still worth pinning.
    """
    pane = video_pane.VideoPane()
    try:
        assert pane.paint_canvas is not None
        assert pane.overlay is not None
        assert pane.lbl_osd is not None

        pane.set_label("Camera 1")
        pane.set_has_footage(False)
        pane.set_has_footage(True)
        pane.set_tracking_readers([])

        assert pane.lbl_name.text() == "Camera 1"
        assert pane.has_media is False
    finally:
        pane.close()


def test_video_surface_wheel_zoom_middle_drag_and_reset(qtbot) -> None:
    """Each surface owns a bounded view transform driven by its input events."""
    surface = video_pane.VideoSurface()
    qtbot.addWidget(surface)
    try:
        surface.resize(320, 240)
        surface.set_frame(np.zeros((360, 640, 3), dtype=np.uint8))
        surface.show()
        qtbot.waitUntil(surface.isVisible)

        wheel = QWheelEvent(
            QPointF(160.0, 120.0),
            QPointF(160.0, 120.0),
            QPoint(),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )
        QApplication.sendEvent(surface, wheel)
        zoomed_scale, _, _ = surface.frame_geometry() or (0.0, 0.0, 0.0)
        assert zoomed_scale == pytest.approx(0.5 * 1.15)

        surface.zoom_by(2.0 / 1.15)
        _, before_x, before_y = surface.frame_geometry() or (0.0, 0.0, 0.0)
        qtbot.mousePress(surface, Qt.MouseButton.MiddleButton, pos=QPoint(160, 120))
        qtbot.mouseMove(surface, QPoint(180, 130))
        qtbot.mouseRelease(surface, Qt.MouseButton.MiddleButton, pos=QPoint(180, 130))
        _, after_x, after_y = surface.frame_geometry() or (0.0, 0.0, 0.0)
        assert after_x == pytest.approx(before_x + 20.0)
        assert after_y == pytest.approx(before_y + 10.0)

        surface.reset_view()
        assert surface.frame_geometry() == pytest.approx((0.5, 0.0, 30.0))
    finally:
        surface.close()


def test_pan_by_places_a_chosen_point_and_never_uncovers_the_edge(qtbot) -> None:
    """Callers can aim the magnified view without reproducing a drag gesture.

    ``tools/generate_session_screenshot.py`` frames each pane on a tracked marker
    this way, so the offset a pan asks for has to be the offset it gets — right
    up to the frame's own border, past which it must clamp instead.
    """
    surface = video_pane.VideoSurface()
    qtbot.addWidget(surface)
    try:
        surface.resize(320, 240)
        surface.set_frame(np.zeros((360, 640, 3), dtype=np.uint8))
        surface.zoom_by(4.0)
        _, before_x, before_y = surface.frame_geometry() or (0.0, 0.0, 0.0)

        surface.pan_by(QPointF(-30.0, 25.0))
        _, after_x, after_y = surface.frame_geometry() or (0.0, 0.0, 0.0)
        assert (after_x, after_y) == pytest.approx((before_x - 30.0, before_y + 25.0))

        # Far past the edge: the request is honoured only as far as the frame goes.
        surface.pan_by(QPointF(10_000.0, 0.0))
        scale, clamped_x, _ = surface.frame_geometry() or (0.0, 0.0, 0.0)
        assert clamped_x == pytest.approx(0.0)
        assert scale * 640 > 320
    finally:
        surface.close()


def test_video_pane_zoom_controls_and_overlay_share_the_surface_transform(qtbot) -> None:
    """Control actions and tracking points use the same per-pane view state."""
    pane = video_pane.VideoPane()
    qtbot.addWidget(pane)
    try:
        pane.resize(320, 240)
        pane.surface.set_frame(np.zeros((360, 640, 3), dtype=np.uint8))
        pane.show()
        qtbot.waitUntil(lambda: pane.surface.width() > 0)

        fitted_scale = min(pane.surface.width() / 640.0, pane.surface.height() / 360.0)
        pane.zoom_in_button.click()
        scale, _, _ = pane.surface.frame_geometry() or (0.0, 0.0, 0.0)
        assert scale == pytest.approx(fitted_scale * 1.25)
        assert pane.paint_canvas._video_scale() == pytest.approx(
            pane.surface.frame_geometry(pane.paint_canvas.width(), pane.paint_canvas.height())
        )

        pane.reset_zoom_button.click()
        reset_scale, reset_x, reset_y = pane.surface.frame_geometry() or (0.0, 0.0, 0.0)
        assert reset_scale == pytest.approx(fitted_scale)
        assert reset_x == pytest.approx((pane.surface.width() - 640.0 * fitted_scale) / 2.0)
        assert reset_y == pytest.approx((pane.surface.height() - 360.0 * fitted_scale) / 2.0)
        assert pane.zoom_in_button.toolTip() == "Zoom in"
        assert pane.zoom_out_button.toolTip() == "Zoom out"
        assert pane.reset_zoom_button.toolTip() == "Reset zoom"
        assert isinstance(pane.zoom_in_button, QPushButton)
        assert isinstance(pane.zoom_out_button, QPushButton)
        assert isinstance(pane.reset_zoom_button, QPushButton)
        assert not pane.zoom_in_button.isFlat()
        assert not pane.zoom_out_button.isFlat()
        assert not pane.reset_zoom_button.isFlat()
    finally:
        pane.close()


# ── Decoding ──────────────────────────────────────────────────────────


def test_opening_a_clip_publishes_its_timestamps_and_size(clip: Path, qtbot) -> None:
    """The pane adopts the decoder's table; nothing is inferred from a rate."""
    pane = _opened_pane(clip, qtbot)
    try:
        assert pane.video_size == (640, 360)
        assert pane._frame_times is not None
        assert len(pane._frame_times) == FRAME_COUNT
    finally:
        pane.close()


def test_a_seek_paints_the_frame_containing_that_time(clip: Path, qtbot) -> None:
    """End-to-end, through the real thread: the pixels must name the frame."""
    pane = _opened_pane(clip, qtbot)
    try:
        for index in (0, 17, 61, 42, 5):
            # A quarter of a frame past the boundary — inside frame `index`.
            pane.seek((index + 0.25) / FPS)
            qtbot.waitUntil(lambda: not pane.is_seeking, timeout=5000)
            assert pane.surface._buffer is not None
            assert decode_frame_strip(pane.surface._buffer) == index
    finally:
        pane.close()


def test_the_pane_reports_the_frames_own_timestamp_not_the_request(clip: Path, qtbot) -> None:
    """``time_pos`` is evidence about what is on screen, not an echo."""
    pane = _opened_pane(clip, qtbot)
    try:
        pane.seek((20 + 0.25) / FPS)
        qtbot.waitUntil(lambda: not pane.is_seeking, timeout=5000)
        assert pane.time_pos == pytest.approx(20 / FPS, abs=1e-6)
    finally:
        pane.close()


def test_an_open_time_frame_does_not_answer_a_later_seek(clip: Path, qtbot, monkeypatch) -> None:
    """``is_seeking`` must mean "the frame I asked for", not "a frame".

    Opening a pane issues a seek of its own so something is on screen, so a pane
    that has just reported ``has_media`` still has a decode in flight. While
    ``is_seeking`` was a bare boolean, that first frame cleared the flag for
    whatever seek the caller made in the meantime: a caller waiting on
    ``not pane.is_seeking`` was handed the *previous* frame, and
    ``Seeker.is_settled`` — which promises every pane has painted the frame it
    was asked for — could not tell the difference.

    Delaying only the first decode makes that ordering happen every time. It
    reproduced the intermittent failure of
    ``test_the_pane_reports_the_frames_own_timestamp_not_the_request``, which
    was a real defect surfacing under load rather than a slow test.
    """
    from avialsync.engine.pyav_reader import PyAVReader

    original = PyAVReader.frame_at_index
    calls = {"count": 0}

    def slow_first_decode(self: PyAVReader, index: int):
        calls["count"] += 1
        if calls["count"] == 1:
            time.sleep(0.3)
        return original(self, index)

    monkeypatch.setattr(PyAVReader, "frame_at_index", slow_first_decode)

    pane = _opened_pane(clip, qtbot)
    try:
        # The open-time seek is still outstanding; this is the state the race
        # needed, and asserting it keeps the test honest if that ever changes.
        assert pane.is_seeking

        pane.seek((20 + 0.25) / FPS)
        qtbot.waitUntil(lambda: not pane.is_seeking, timeout=5000)

        assert pane.time_pos == pytest.approx(20 / FPS, abs=1e-6)
        assert decode_frame_strip(pane.surface._buffer) == 20
    finally:
        pane.close()


def test_decoding_never_runs_on_the_ui_thread(clip: Path, qtbot) -> None:
    """AGENTS.md rule 3: no decoding on the thread that has to stay responsive."""
    pane = _opened_pane(clip, qtbot)
    decode_threads: list[int] = []
    original = video_pane.DecodeWorker.decode_pending

    def recording_decode(self: video_pane.DecodeWorker) -> None:
        decode_threads.append(threading.get_ident())
        original(self)

    try:
        video_pane.DecodeWorker.decode_pending = recording_decode  # type: ignore[method-assign]
        pane.seek(1.0)
        qtbot.waitUntil(lambda: not pane.is_seeking, timeout=5000)
    finally:
        video_pane.DecodeWorker.decode_pending = original  # type: ignore[method-assign]
        pane.close()

    assert decode_threads, "the decode slot never ran"
    assert threading.get_ident() not in decode_threads


def test_a_seek_before_the_file_opens_is_not_lost(clip: Path, qtbot) -> None:
    """A session restores a scrub position before any decoder exists."""
    pane = video_pane.VideoPane()
    qtbot.addWidget(pane)
    try:
        pane.seek((33 + 0.25) / FPS)
        pane.open(str(clip))
        qtbot.waitUntil(lambda: pane.has_media and not pane.is_seeking, timeout=5000)
        assert decode_frame_strip(pane.surface._buffer) == 33
    finally:
        pane.close()


def test_a_pane_that_cannot_open_its_file_says_so(qapp: QApplication, qtbot, tmp_path) -> None:
    """A bad file must leave a pane that explains itself, not a traceback."""
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a container")

    pane = video_pane.VideoPane()
    qtbot.addWidget(pane)
    try:
        with qtbot.waitSignal(pane.open_failed, timeout=5000):
            pane.open(str(broken))
        assert pane.has_media is False
        assert "unavailable" in pane.lbl_no_footage.text().lower()
    finally:
        pane.close()


# ── Coalescing ────────────────────────────────────────────────────────


def test_requests_coalesce_onto_the_newest_wanted_time() -> None:
    """A 60 Hz tick must not queue a backlog of frames nobody will see.

    Sync correctness beats frame completeness (AGENTS.md rule 6): a decoder
    slower than the tick rate skips to the newest request rather than working
    through every one in order and falling further behind.
    """
    worker = video_pane.DecodeWorker("unused.mp4")
    decoded: list[float] = []
    announced: list[int] = []
    pixels = np.zeros((2, 2, 3), dtype=np.uint8)
    worker._reader = SimpleNamespace(  # type: ignore[assignment]
        index_at_time=lambda t: decoded.append(t) or 0,
        # Convertible, unlike a bare namespace: the id is only observable on
        # `frame_ready`, which a frame that cannot become an array never reaches.
        frame_at_index=lambda i: SimpleNamespace(to_ndarray=lambda format=None: pixels),
        time_at_index=lambda i: 0.0,
    )
    worker.frame_ready.connect(lambda request_id, *_: announced.append(request_id))

    for step in range(50):
        worker.request(step, step / 60.0)
    worker.decode_pending()

    assert decoded == [49 / 60.0]
    # The id travels with the time, so the surviving request keeps its own id
    # rather than the last one posted being reported against an older time.
    assert announced == [49]

    # A second invocation with nothing outstanding must not redo the work.
    worker.decode_pending()
    assert decoded == [49 / 60.0]


def test_video_osd_queue_keeps_only_latest_frame() -> None:
    """A delayed UI thread must not accumulate one OSD event per decoded frame."""

    class _Signal:
        def __init__(self) -> None:
            self.emissions = 0

        def emit(self) -> None:
            self.emissions += 1

    signal = _Signal()
    pane = SimpleNamespace(
        _osd_lock=threading.Lock(),
        _pending_osd=(0.0, 0.0),
        _osd_event_pending=False,
        _osd_update=signal,
    )

    for frame in range(10_000):
        video_pane.VideoPane._queue_osd_update(pane, frame / 30.0, 30.0)

    assert pane._pending_osd == (9999 / 30.0, 30.0)
    assert pane._osd_event_pending is True
    assert signal.emissions == 1


# ── Teardown ──────────────────────────────────────────────────────────


def test_close_stops_the_decode_thread(clip: Path, qtbot) -> None:
    """Ownership is explicit, exactly as it was for libmpv's event thread.

    The pane that started the thread stops it; nothing is left to garbage
    collection or Qt child destruction.
    """
    pane = _opened_pane(clip, qtbot)
    thread = pane._thread
    assert thread is not None and thread.isRunning()

    pane.close()

    assert not thread.isRunning()
    assert pane._worker is None
    assert pane.has_media is False


def test_reopening_replaces_the_decoder_rather_than_leaking_it(clip: Path, qtbot) -> None:
    """Relinking a source must not leave the previous file's thread running."""
    pane = _opened_pane(clip, qtbot)
    try:
        first = pane._thread
        pane.open(str(clip))
        qtbot.waitUntil(lambda: pane.has_media, timeout=5000)

        assert first is not None and not first.isRunning()
        assert pane._thread is not first
        assert pane._thread is not None and pane._thread.isRunning()
    finally:
        pane.close()


def test_qt_closing_the_pane_also_stops_the_decode_thread(clip: Path, qtbot) -> None:
    """Qt closes widgets without calling ``close()`` — the thread must still stop.

    ``close()`` only runs when something calls it. An application quitting, or a
    parent being destroyed, delivers ``closeEvent`` instead, and a ``QThread``
    still running when its C++ object is destroyed makes Qt *abort* the process:
    "QThread: Destroyed while thread is still running". That is a crash on exit
    rather than a leak, and it is what the screenshot tool hit.

    Explicit shutdown through ``VideoGrid.shutdown()`` is still the intended
    path; this is the backstop, not permission to rely on destruction.
    """
    pane = _opened_pane(clip, qtbot)
    thread = pane._thread
    assert thread is not None and thread.isRunning()

    # Qt's own close path, not the convenience method.
    pane.closeEvent(QCloseEvent())

    assert not thread.isRunning()
    assert pane._worker is None


def test_closing_a_pane_that_never_opened_anything_is_safe(qapp: QApplication) -> None:
    """Teardown runs on panes that failed or were never used."""
    pane = video_pane.VideoPane()
    pane.close()
    assert pane._worker is None


# ── Painting ──────────────────────────────────────────────────────────


def test_the_surface_holds_the_buffer_its_image_borrows(qapp: QApplication) -> None:
    """``QImage`` does not copy the array it wraps.

    Dropping the array would leave the image pointing at freed memory, which
    faults during a repaint rather than raising — so the reference is held
    deliberately and this pins it.
    """
    surface = video_pane.VideoSurface()
    rgb = np.zeros((360, 640, 3), dtype=np.uint8)
    rgb[:] = 200
    surface.set_frame(rgb)

    assert surface._buffer is rgb
    assert surface._image is not None
    assert surface._image.width() == 640
    assert surface._image.height() == 360


def test_losing_footage_clears_the_frame_instead_of_freezing_it(clip: Path, qtbot) -> None:
    """D-010: outside a source's bounds we show a placeholder, never a stale frame."""
    pane = _opened_pane(clip, qtbot)
    try:
        pane.seek(1.0)
        qtbot.waitUntil(lambda: not pane.is_seeking, timeout=5000)
        assert pane.surface._buffer is not None

        pane.set_has_footage(True)
        pane.set_has_footage(False)

        assert pane.surface._buffer is None
        assert pane.lbl_no_footage.isVisible() or pane.lbl_no_footage.text()
    finally:
        pane.close()


# ── A padded recording must settle its seeks (D-102) ──────────────────
#
# The contiguity guarantee is pinned in tests/test_display_pipeline.py. What is
# pinned here is the consequence of losing it, because that is what the user
# actually reported: not "an exception in the log" but "it blinks and nothing
# plays, and navigation stopped being seamless".
#
# `_on_frame_ready` paints before it clears `is_seeking`, updates `time_pos`,
# and emits `frame_presented`. A raise on the first line loses all three:
#   * `SeekGroup.is_settled()` never becomes true again, so `Player.seek`
#     coalesces every non-exact (drag) seek into `_pending_scrub_t` and
#     `_on_tick` never flushes it — scrubbing dies while exact seeks still work,
#     which is what "not seamless" feels like from the outside;
#   * the master clock is deliberately not gated on settling, so the playhead,
#     plots and readout keep moving over a picture that never changes.

#: A width whose rgb24 rows FFmpeg pads, and one it does not.
PADDED_FRAME_SIZE = (1290, 720)
ALIGNED_FRAME_SIZE = (640, 360)


@pytest.mark.parametrize("size", [PADDED_FRAME_SIZE, ALIGNED_FRAME_SIZE])
def test_a_decoded_frame_settles_the_seek_it_answers(size, qtbot) -> None:
    """Whatever the width, delivering the awaited frame must end the seek."""
    import av

    from avialsync.engine.display_pipeline import to_display_array
    from avialsync.engine.seeker import SeekGroup

    pane = video_pane.VideoPane()
    qtbot.addWidget(pane)
    pane.resize(400, 300)
    pane.is_seeking = True
    pane._seek_id = 7
    rgb, _ = to_display_array(av.VideoFrame(*size, "yuv420p"))
    presented: list[float] = []
    pane.frame_presented.connect(presented.append)

    pane._on_frame_ready(7, 0, 1.25, rgb)

    assert not pane.is_seeking, "the pane never stopped waiting for its own frame"
    assert SeekGroup([pane]).is_settled(), "Player would coalesce every drag seek forever"
    assert pane.time_pos == 1.25
    assert presented == [1.25]
