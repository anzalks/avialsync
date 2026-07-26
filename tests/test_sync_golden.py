"""Golden sync testing for video playback."""

import pathlib
import random

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from util_framestrip import decode_frame_strip

from avialview.ui.main_window import MainWindow


@pytest.fixture
def app_with_main_window(qapp: QApplication) -> MainWindow:
    """Fixture providing an initialized main window."""
    win = MainWindow()
    win.show()
    return win


def _capture_frame(pane) -> np.ndarray:
    """Return libmpv's current decoded video frame without an OSD render race."""
    screenshot = pane.mpv.command("screenshot-raw", "video")
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
        decoded_frame = decode_frame_strip(_capture_frame(pane))
        return decoded_frame == expected_frame

    qtbot.waitUntil(is_expected_frame, timeout=2000)
    return decoded_frame


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
        target_time = target_frame / 30.0

        # Seek
        win.player.seek(target_time, exact=True)

        # Wait for mpv to settle (is_seeking == False)
        # Note: Qt needs event loop to pump
        def is_settled(t=target_time):
            return not pane.is_seeking and abs(pane.time_pos - t) < 0.05

        qtbot.waitUntil(is_settled, timeout=2000)

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
        target_time = target_frame / 30.0

        # Seek (master time)
        win.player.seek(target_time, exact=True)

        def is_settled(t_tgt=target_time):
            for pane in panes:
                source_t = pane.time_map.to_source(t_tgt)
                if pane.is_seeking or abs(pane.time_pos - source_t) > 0.05:
                    return False
            return True

        qtbot.waitUntil(is_settled, timeout=2000)

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
