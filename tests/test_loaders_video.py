from pathlib import Path

import numpy as np
import pytest

from avialview.loaders.video_standard import VideoStandardLoader

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
    assert len(frame_times) > 2
    assert loader.is_vfr() is True
    intervals = np.diff(frame_times)
    assert np.unique(np.round(intervals, 4)).size >= 2


def test_video_standard_uses_presentation_order_frame_timestamps(monkeypatch) -> None:
    """B-frame packet order must not decide VFR detection or frame stepping."""

    class _Result:
        stdout = "0.000000,\n0.050000,\n0.066667,\n"

    captured: list[str] = []

    def fake_run(command, **_kwargs):
        captured.extend(command)
        return _Result()

    monkeypatch.setattr("avialview.loaders.video_standard.subprocess.run", fake_run)
    loader = VideoStandardLoader()
    loader._extract_frame_times(Path("presentation-order.mp4"))

    assert "frame=best_effort_timestamp_time" in captured
    assert loader.frame_times() is not None
    np.testing.assert_allclose(loader.frame_times(), [0.0, 0.05, 0.066667])


def test_video_standard_detects_variable_frame_intervals() -> None:
    """VFR detection is based on timestamps, not a misleading average FPS."""
    loader = VideoStandardLoader()
    loader._frame_times = np.array([0.0, 1 / 30, 2 / 30, 4 / 30])

    assert loader.is_vfr() is True


def test_video_standard_detects_constant_frame_intervals() -> None:
    """CFR timestamps must not receive the VFR integrity warning."""
    loader = VideoStandardLoader()
    loader._frame_times = np.array([0.0, 1 / 30, 2 / 30, 3 / 30])

    assert loader.is_vfr() is False


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
