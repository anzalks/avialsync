"""Golden sync testing for video playback."""

import math
import pathlib
import random
from collections.abc import Callable
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from util_framestrip import decode_frame_strip

from avialsync.ui.main_window import MainWindow

OBSERVER_SETTLE_TIMEOUT_MS = 5_000
FIXTURE_FRAME_RATE = 30.0


def _fixture_frame_time(frame_index: int) -> float:
    """Return a timestamp inside the known decoded interval for a fixture frame.

    Frame ``n`` of this 30 fps fixture presents at ``n/30`` and stays on screen
    until ``(n+1)/30``, so a probe *inside* its interval is ``(n + 0.25)/30``.

    This used to read ``(n - 0.25)/30``, which is a quarter of a frame *below*
    ``n`` — inside frame ``n-1``'s interval, not ``n``'s — while the test still
    expected frame ``n`` back, and passed. That combination is only possible
    against a reader that returns the first frame with ``pts >= t``, which is
    the 33 ms misattribution D-075 exists to remove: at every scrub position
    between two frames it names the frame that has not been shown yet. The
    probe is corrected here rather than the expectation, so the test asserts the
    same thing it always claimed to — the frame whose interval contains ``t``.
    """
    return (frame_index + 0.25) / FIXTURE_FRAME_RATE


@pytest.fixture
def app_with_main_window(qapp: QApplication) -> MainWindow:
    """Fixture providing an initialized main window."""
    win = MainWindow()
    win.show()
    yield win
    win.close()


def _capture_frame(pane) -> np.ndarray | None:
    """Return the greyscale pixels the pane is actually displaying.

    This reads the buffer the pane blitted, so it is evidence about what is on
    screen rather than about what a decoder says it did.  Under libmpv this had
    to go through ``screenshot-raw video``, which could transiently return the
    *pre-seek* frame after the seek observer had already settled — hence the
    retry loop that used to live here.  There is no such window now: the buffer
    is replaced in the same slot that clears ``is_seeking``, so a settled pane
    is displaying its target frame by construction.
    """
    buffer = pane.surface._buffer
    if buffer is None:
        return None
    return np.rint(buffer @ np.array([0.299, 0.587, 0.114])).astype(np.uint8)


def _wait_for_decoded_frame(
    pane, expected_frame: int, expected_time: float, qtbot, retry_seek: Callable[[], None]
) -> int:
    """Capture the exact frame the pane settled on."""
    del retry_seek
    frame_tolerance = 0.5 / FIXTURE_FRAME_RATE

    def is_settled_at_target() -> bool:
        return not pane.is_seeking and abs(pane.time_pos - expected_time) <= frame_tolerance

    qtbot.waitUntil(is_settled_at_target, timeout=OBSERVER_SETTLE_TIMEOUT_MS)

    captured = _capture_frame(pane)
    assert captured is not None, "pane settled without ever painting a frame"
    return decode_frame_strip(captured)


def test_capture_frame_reports_nothing_before_the_first_paint() -> None:
    """An unpainted pane must read as absent evidence, never as frame zero."""

    class EmptyPane:
        surface = SimpleNamespace(_buffer=None)

    assert _capture_frame(EmptyPane()) is None


def test_golden_sync_basic(app_with_main_window: MainWindow, qtbot) -> None:
    """Test video frame accuracy via framestrip."""
    win = app_with_main_window

    fixture_dir = pathlib.Path("tests/fixtures")
    video_path = fixture_dir / "videos/camera_1.mp4"  # base 30fps h264, no offset
    if not video_path.exists():
        pytest.fail("Fixtures not generated — run: python tools/make_fixtures.py")

    win.video_grid.add_pane(str(video_path))
    pane = win.video_grid.panes[0]

    qtbot.waitUntil(lambda: pane.has_media, timeout=5000)

    random.seed(42)
    # Test 5 random frames
    for _ in range(5):
        target_frame = random.randint(10, 100)
        target_time = _fixture_frame_time(target_frame)

        # Seek
        win.player.seek(target_time, exact=True)

        # The painted frame is the definitive evidence.
        decoded = _wait_for_decoded_frame(
            pane,
            target_frame,
            target_time,
            qtbot,
            lambda pane=pane, target_time=target_time: pane.seek(target_time, exact=True),
        )

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

    qtbot.waitUntil(lambda: all(pane.has_media for pane in panes), timeout=5000)

    random.seed(42)
    # Test 3 random frames
    for _ in range(3):
        target_frame = random.randint(10, 100)
        target_time = _fixture_frame_time(target_frame)

        # Seek (master time)
        win.player.seek(target_time, exact=True)

        # Check each pane's exact frame via decoding
        for i, pane in enumerate(panes):
            # Pane 0 is aligned; panes 1 and 2 carry known offsets, so each
            # one is expected at its *own* source time. The frame is the one
            # whose interval contains that instant — floor, never round: a
            # rounded index names the next frame from halfway through the
            # current one, which is the misattribution under test.
            expected_source_t = pane.time_map.to_source(target_time)
            expected_frame = int(math.floor(expected_source_t * FIXTURE_FRAME_RATE + 1e-9))
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
