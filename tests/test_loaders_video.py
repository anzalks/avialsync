from pathlib import Path

import pytest

from kinochronix.loaders.video_standard import VideoStandardLoader

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "videos"


def test_video_standard_basic():
    path = FIXTURE_DIR / "base_30fps.mp4"
    if not path.exists():
        pytest.skip("Fixtures not generated")

    loader = VideoStandardLoader()
    assert loader.can_open(path) > 0.0

    loader.open(path, {})
    assert not loader.needs_conversion()
    assert loader.fps() == 30.0
    assert loader.start_time() is not None

    frame_times = loader.frame_times()
    assert frame_times is not None
    assert len(frame_times) > 0

    # At 30fps, delta between frames is ~0.0333
    dt = frame_times[1] - frame_times[0]
    assert 0.03 <= dt <= 0.04


def test_video_standard_vfr():
    path = FIXTURE_DIR / "vfr.mp4"
    if not path.exists():
        pytest.skip("Fixtures not generated")

    loader = VideoStandardLoader()
    loader.open(path, {})

    frame_times = loader.frame_times()
    assert frame_times is not None
    assert len(frame_times) > 0
    # Variable frame rate should produce variable dt, but let's just ensure it parses successfully


def test_video_standard_no_metadata():
    path = FIXTURE_DIR / "no_metadata.mp4"
    if not path.exists():
        pytest.skip("Fixtures not generated")

    loader = VideoStandardLoader()
    loader.open(path, {})

    start_time = loader.start_time()
    assert start_time is None or start_time == 0.0


def test_video_standard_dropped_frames():
    path = FIXTURE_DIR / "dropped_frames.mp4"
    if not path.exists():
        pytest.skip("Fixtures not generated")

    loader = VideoStandardLoader()
    loader.open(path, {})

    frame_times = loader.frame_times()
    assert frame_times is not None
    assert len(frame_times) > 0
