"""Golden sync testing for video playback."""

import pathlib
import random

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.exceptions import TimeoutError as QtTimeoutError
from util_framestrip import decode_frame_strip

from avialview.ui.main_window import MainWindow

DECODED_FRAME_TIMEOUT_MS = 5_000
FIXTURE_FRAME_RATE = 30.0


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


def _wait_for_decoded_frame(pane, expected_frame: int, qtbot) -> int:
    """Wait until libmpv's decoded frame is the requested exact frame."""
    decoded_frame = -1

    def is_expected_frame() -> bool:
        nonlocal decoded_frame
        frame = _capture_frame(pane)
        if frame is None:
            return False
        decoded_frame = decode_frame_strip(frame)
        return decoded_frame == expected_frame

    try:
        qtbot.waitUntil(is_expected_frame, timeout=DECODED_FRAME_TIMEOUT_MS)
    except QtTimeoutError as error:
        raise AssertionError(
            f"Expected decoded frame {expected_frame}; last decoded frame was {decoded_frame}; "
            f"mpv time-pos was {pane.time_pos}."
        ) from error
    return decoded_frame


def test_capture_frame_retries_when_mpv_is_busy() -> None:
    """A transient exact-seek command error must not become stale evidence."""

    class BusyMpv:
        def command(self, *_args: str) -> None:
            raise SystemError("mpv is seeking")

    class BusyPane:
        mpv = BusyMpv()

    assert _capture_frame(BusyPane()) is None


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
        decoded = _wait_for_decoded_frame(pane, target_frame, qtbot)

        assert decoded == target_frame, f"Expected {target_frame}, got {decoded} at {target_time}s"


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
            decoded = _wait_for_decoded_frame(pane, expected_frame, qtbot)

            assert decoded == expected_frame, (
                f"Pane {i}: Expected {expected_frame}, got {decoded} at {target_time}s master time"
            )
