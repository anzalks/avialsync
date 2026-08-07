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
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

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
    worker._reader = SimpleNamespace(  # type: ignore[assignment]
        index_at_time=lambda t: decoded.append(t) or 0,
        frame_at_index=lambda i: SimpleNamespace(),
        time_at_index=lambda i: 0.0,
    )

    for step in range(50):
        worker.request(step / 60.0)
    worker.decode_pending()

    assert decoded == [49 / 60.0]

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
