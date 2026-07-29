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
    assert loader.video_metadata().codec == "h264"
    assert loader.video_metadata().file_size_bytes == path.stat().st_size

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

    assert "packet=pts_time" in captured
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


def test_timestamp_evidence_overrides_misleading_nominal_cfr_rate() -> None:
    """Variable presentation intervals win over a container's nominal CFR declaration."""
    loader = VideoStandardLoader()
    loader._fps = 30.0
    loader._frame_times = np.array([0.0, 1 / 30, 2 / 30, 4 / 30, 5 / 30])

    metadata = loader.video_metadata()

    assert metadata.is_vfr is True
    assert metadata.nominal_fps == pytest.approx(30.0)
    assert metadata.measured_fps == pytest.approx(24.0)
    assert metadata.min_frame_rate == pytest.approx(15.0)
    assert metadata.max_frame_rate == pytest.approx(30.0)


def test_frame_timestamp_cache_avoids_reprobing_long_video(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A second open mmaps the validated frame index instead of rerunning ffprobe."""
    video = tmp_path / "long.mp4"
    video.write_bytes(b"fake-video-payload")
    metadata_json = (
        '{"format":{"duration":"1.0","size":"18"},'
        '"streams":[{"codec_type":"video","codec_name":"h264",'
        '"r_frame_rate":"30/1","width":640,"height":480}]}'
    )
    commands: list[list[str]] = []

    class _Result:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def fake_run(command: list[str], **_kwargs: object) -> _Result:
        commands.append(command)
        if "-show_streams" in command:
            return _Result(metadata_json)
        return _Result("0.000000,\n0.033333,\n0.066667,\n")

    monkeypatch.setattr("avialview.loaders.video_standard.require_ffprobe", lambda: Path("ffprobe"))
    monkeypatch.setattr("avialview.loaders.video_standard.subprocess.run", fake_run)

    first = VideoStandardLoader()
    first.open(video, {})
    second = VideoStandardLoader()
    second.open(video, {})

    frame_probes = [command for command in commands if "packet=pts_time" in command]
    assert len(frame_probes) == 1
    assert isinstance(second.frame_times(), np.memmap)
    np.testing.assert_allclose(second.frame_times(), [0.0, 0.033333, 0.066667])


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
