from pathlib import Path

import numpy as np
import pytest

from avialsync.loaders.video_standard import VideoStandardLoader

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


def test_video_standard_uses_presentation_order_frame_timestamps(tmp_path: Path) -> None:
    """B-frame packet order must not decide VFR detection or frame stepping.

    Against a real long-GOP fixture rather than a mocked ``ffprobe`` stdout:
    the loader now builds its table with the same ``PyAVReader`` the pane
    decodes through, so what is worth asserting is that a file which genuinely
    demuxes out of order still yields a sorted table.
    """
    from tests.util_pyav_fixtures import cfr_times, write_video

    video = tmp_path / "presentation-order.mp4"
    written = write_video(video, frame_times=cfr_times(90), gop_size=30)

    loader = VideoStandardLoader()
    loader._extract_frame_times(video)

    times = loader.frame_times()
    assert times is not None
    assert np.all(np.diff(times) > 0), "table left in decode order"
    np.testing.assert_allclose(times, written, atol=1e-6)


def test_the_loader_and_the_decoder_share_one_frame_table(tmp_path: Path) -> None:
    """Two tables over one file would be two authorities on which frame is which.

    The pane selects the displayed frame from the decoder's table and names it
    from the loader's. D-075 requires those to be one thing; this pins that they
    are, byte for byte, rather than merely close.
    """
    from avialsync.engine.pyav_reader import PyAVReader
    from tests.util_pyav_fixtures import cfr_times, write_video

    video = tmp_path / "shared.mp4"
    write_video(video, frame_times=cfr_times(60), gop_size=15)

    loader = VideoStandardLoader()
    loader._extract_frame_times(video)
    with PyAVReader(video) as reader:
        np.testing.assert_array_equal(loader.frame_times(), reader.frame_times)


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
    """A second open mmaps the validated frame index instead of rebuilding it.

    Building the table costs a full demux pass — 225 ms on a 716 MB session
    file — so the sidecar is what keeps a repeat open cheap.
    """
    from tests.util_pyav_fixtures import cfr_times, write_video

    video = tmp_path / "long.mp4"
    write_video(video, frame_times=cfr_times(90), gop_size=30)

    builds: list[Path] = []
    original = VideoStandardLoader._extract_frame_times

    def counting_extract(self: VideoStandardLoader, path: Path) -> None:
        builds.append(path)
        original(self, path)

    monkeypatch.setattr(VideoStandardLoader, "_extract_frame_times", counting_extract)

    first = VideoStandardLoader()
    first.open(video, {})
    second = VideoStandardLoader()
    second.open(video, {})

    assert len(builds) == 1, "the second open rebuilt the table instead of reading the sidecar"
    np.testing.assert_array_equal(first.frame_times(), second.frame_times())
    assert isinstance(second.frame_times(), np.memmap), "the cache must be mmap-read, not re-parsed"
    np.testing.assert_allclose(second.frame_times(), cfr_times(90), atol=1e-6)


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
