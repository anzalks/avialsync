"""Golden sync testing for video playback."""

import pathlib
import random
import sys
import time
from collections.abc import Callable

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.exceptions import TimeoutError as QtTimeoutError
from util_framestrip import decode_frame_strip

from avialview.ui.main_window import MainWindow

DECODED_FRAME_TIMEOUT_MS = 10_000
OBSERVER_SETTLE_TIMEOUT_MS = 5_000
FIXTURE_FRAME_RATE = 30.0
RAW_CAPTURE_RETRY_MS = 50


def _fixture_frame_time(frame_index: int) -> float:
    """Return a timestamp inside the known decoded interval for a fixture frame."""
    return (frame_index - 0.25) / FIXTURE_FRAME_RATE


@pytest.fixture
def app_with_main_window(qapp: QApplication) -> MainWindow:
    """Fixture providing an initialized main window."""
    win = MainWindow()
    win.show()
    yield win
    win.close()


def _capture_frame(pane) -> np.ndarray | None:
    """Return the decoded frame, or None while libmpv is still seeking."""
    try:
        screenshot = pane.mpv.command("screenshot-raw", "video")
    except SystemError:
        # libmpv reports -12 while a seek has not produced a frame yet.  The
        # caller retries through Qt's event loop rather than treating stale
        # data as a settled frame.
        return None
    assert screenshot["format"] == "bgr0"
    pixels = np.frombuffer(screenshot["data"], np.uint8).reshape(
        (screenshot["h"], screenshot["stride"] // 4, 4)
    )[:, : screenshot["w"], :3]
    return np.rint(pixels @ np.array([0.114, 0.587, 0.299])).astype(np.uint8)


def _wait_for_decoded_frame(
    pane, expected_frame: int, expected_time: float, qtbot, retry_seek: Callable[[], None]
) -> int:
    """Capture the exact decoded frame after a bounded observer-settle retry."""
    frame_tolerance = 0.5 / FIXTURE_FRAME_RATE

    def is_settled_at_target() -> bool:
        return not pane.is_seeking and abs(pane.time_pos - expected_time) <= frame_tolerance

    try:
        qtbot.waitUntil(is_settled_at_target, timeout=OBSERVER_SETTLE_TIMEOUT_MS)
    except QtTimeoutError:
        # A duplicated exact command is safe and gives a delayed Windows
        # libmpv observer one bounded opportunity to report its target.
        retry_seek()
        qtbot.waitUntil(is_settled_at_target, timeout=OBSERVER_SETTLE_TIMEOUT_MS)

    deadline = time.monotonic() + DECODED_FRAME_TIMEOUT_MS / 1_000
    last_decoded_frame: int | None = None
    while time.monotonic() < deadline:
        captured_frame = _capture_frame(pane)
        if captured_frame is not None:
            last_decoded_frame = decode_frame_strip(captured_frame)
            if last_decoded_frame == expected_frame:
                return last_decoded_frame
        # A raw snapshot can transiently expose the pre-seek frame even after
        # the observer settles. Treat it as unavailable evidence, never as a
        # successful capture, and yield through Qt rather than sleeping.
        qtbot.wait(RAW_CAPTURE_RETRY_MS)

    raise AssertionError(
        f"libmpv settled at {pane.time_pos}, but raw capture never reached expected frame "
        f"{expected_frame}; last decoded frame was {last_decoded_frame}."
    )


def test_capture_frame_retries_when_mpv_is_busy() -> None:
    """A transient exact-seek command error must not become stale evidence."""

    class BusyMpv:
        def command(self, *_args: str) -> None:
            raise SystemError("mpv is seeking")

    class BusyPane:
        mpv = BusyMpv()

    assert _capture_frame(BusyPane()) is None


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows libmpv cannot safely capture raw frames with Qt's offscreen platform",
)
def test_golden_sync_basic(app_with_main_window: MainWindow, qtbot) -> None:
    """Test video frame accuracy via framestrip."""
    win = app_with_main_window

    fixture_dir = pathlib.Path("tests/fixtures")
    video_path = fixture_dir / "videos/camera_1.mp4"  # base 30fps h264, no offset
    if not video_path.exists():
        pytest.fail("Fixtures not generated — run: python tools/make_fixtures.py")

    win.video_grid.add_pane(str(video_path))
    pane = win.video_grid.panes[0]

    # Give mpv a moment to load and populate duration
    def is_loaded():
        has_mpv = pane.mpv is not None
        has_dur = getattr(pane.mpv, "duration", None) is not None
        return has_mpv and has_dur

    qtbot.waitUntil(is_loaded, timeout=5000)

    random.seed(42)
    # Test 5 random frames
    for _ in range(5):
        target_frame = random.randint(10, 100)
        target_time = _fixture_frame_time(target_frame)

        # Seek
        win.player.seek(target_time, exact=True)

        # The decoded frame is the definitive seek-settle evidence.  The
        # seeking property is advisory and may not transition on every mpv VO.
        decoded = _wait_for_decoded_frame(
            pane,
            target_frame,
            target_time,
            qtbot,
            lambda pane=pane, target_time=target_time: pane.seek(target_time, exact=True),
        )

        assert decoded == target_frame, f"Expected {target_frame}, got {decoded} at {target_time}s"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows libmpv cannot safely capture raw frames with Qt's offscreen platform",
)
def test_golden_sync_multi(app_with_main_window: MainWindow, qtbot) -> None:
    """Test multi-camera golden sync with offsets."""
    win = app_with_main_window

    fixture_dir = pathlib.Path("tests/fixtures")
    cam1 = fixture_dir / "videos/camera_1.mp4"
    cam2 = fixture_dir / "videos/camera_2.mp4"
    cam3 = fixture_dir / "videos/camera_3.mp4"

    if not cam1.exists():
        pytest.fail("Fixtures not generated — run: python tools/make_fixtures.py")

    win.video_grid.add_pane(str(cam1))
    win.video_grid.add_pane(str(cam2))
    win.video_grid.add_pane(str(cam3))

    # Apply known offsets directly to the panes
    panes = win.video_grid.panes
    panes[0].time_map.update(0.0, 0.0, 0.0)
    panes[1].time_map.update(1.234, 0.0, 0.0)
    panes[2].time_map.update(7.500, 0.0, 0.0)

    # Give mpv a moment to load and populate duration on all panes
    def is_loaded():
        for pane in panes:
            if pane.mpv is None or getattr(pane.mpv, "duration", None) is None:
                return False
        return True

    qtbot.waitUntil(is_loaded, timeout=5000)

    random.seed(42)
    # Test 3 random frames
    for _ in range(3):
        target_frame = random.randint(10, 100)
        target_time = _fixture_frame_time(target_frame)

        # Seek (master time)
        win.player.seek(target_time, exact=True)

        # Check each pane's exact frame via decoding
        for i, pane in enumerate(panes):
            # The expected frame is the target frame for pane 0.
            # For pane 1 and 2, it is shifted by offset.
            # wait, if Master is at target_time, and pane 1 has offset 1.234,
            # source time = target_time + 1.234.
            # frame = round(source_time * 30.0)
            expected_source_t = pane.time_map.to_source(target_time)
            expected_frame = round(expected_source_t * 30.0)
            decoded = _wait_for_decoded_frame(
                pane,
                expected_frame,
                expected_source_t,
                qtbot,
                lambda pane=pane, expected_source_t=expected_source_t: pane.seek(
                    expected_source_t, exact=True
                ),
            )

            assert decoded == expected_frame, (
                f"Pane {i}: Expected {expected_frame}, got {decoded} at {target_time}s master time"
            )
