"""Golden sync testing for video playback."""

import pathlib
import random

import numpy as np
import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from kinochronix.ui.main_window import MainWindow
from tests.util_framestrip import decode_frame_strip


@pytest.fixture
def app_with_main_window(qapp: QApplication) -> MainWindow:
    """Fixture providing an initialized main window."""
    win = MainWindow()
    win.show()
    return win


def test_golden_sync_basic(app_with_main_window: MainWindow, qtbot) -> None:
    """Test video frame accuracy via framestrip."""
    win = app_with_main_window

    fixture_dir = pathlib.Path("tests/fixtures")
    video_path = fixture_dir / "videos/base_30fps.mp4"
    if not video_path.exists():
        pytest.skip("Fixtures not generated")

    win.video_pane.open(str(video_path))

    # Give mpv a moment to load and populate duration
    def is_loaded():
        has_mpv = win.video_pane.mpv is not None
        has_dur = getattr(win.video_pane.mpv, 'duration', None) is not None
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
            return not win.video_pane.is_seeking and abs(win.video_pane.time_pos - t) < 0.05

        qtbot.waitUntil(is_settled, timeout=2000)

        # Give one more tick for OpenGL to swap buffer
        qtbot.wait(100)

        # Extract pixel data via mpv screenshot
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            img_path = os.path.join(td, "screenshot.png")
            win.video_pane.mpv.command("screenshot-to-file", img_path)

            # Read via QImage
            img = QImage(img_path)
            assert not img.isNull(), "Grabbed null frame"

            # Convert QImage to numpy
            img = img.convertToFormat(QImage.Format.Format_Grayscale8)
            ptr = img.bits()
            arr = np.frombuffer(ptr, np.uint8).reshape((img.height(), img.bytesPerLine()))
            arr = arr[:, :img.width()].copy()

        # Decode
        decoded = decode_frame_strip(arr)

        assert decoded == target_frame, f"Expected {target_frame}, got {decoded} at {target_time}s"
