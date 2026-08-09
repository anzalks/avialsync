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


# ── Format acceptance: extension fast path, then a real probe ─────────


def test_known_container_extensions_are_claimed_without_opening_the_file(tmp_path: Path) -> None:
    """The common case must not pay a file open during loader selection."""
    for suffix in (".mp4", ".mov", ".mkv", ".avi", ".webm", ".mpg", ".mts", ".wmv", ".mxf"):
        # Deliberately not real media: a claim on these must come from the
        # extension alone, so an unreadable file still scores.
        candidate = tmp_path / f"clip{suffix}"
        candidate.write_bytes(b"not really video")
        assert VideoStandardLoader.can_open(candidate) == 0.9, suffix


def test_a_real_video_with_an_unknown_extension_is_still_accepted(tmp_path: Path) -> None:
    """A rig that names its recordings something nobody listed must still load.

    This is the point of probing: the decoder handles far more containers than
    any extension list will keep up with, so what decides is whether the file
    actually holds video.
    """
    from tests.util_pyav_fixtures import cfr_times, write_video

    # Written as mp4 then renamed: PyAV cannot infer an output format from an
    # unknown suffix, and the point here is a real MP4 that a rig happens to
    # name something else — which is exactly what the probe has to see through.
    written = tmp_path / "written.mp4"
    write_video(written, frame_times=cfr_times(30), gop_size=15)
    recording = tmp_path / "recording.rig"
    written.rename(recording)

    assert VideoStandardLoader.can_open(recording) == 0.5

    loader = VideoStandardLoader()
    loader.open(recording, {})
    assert loader.video_metadata().frame_count == 30


def test_a_still_image_is_not_claimed_as_video(tmp_path: Path) -> None:
    """FFmpeg opens a PNG as a one-frame video stream.

    Unguarded, the probe would claim every screenshot in a session folder as a
    camera. Still-image extensions are therefore refused before the probe runs.
    """
    from PySide6.QtGui import QImage

    for suffix in (".png", ".jpg", ".tif", ".bmp"):
        image_path = tmp_path / f"frame{suffix}"
        QImage(8, 8, QImage.Format.Format_RGB888).save(str(image_path))
        assert VideoStandardLoader.can_open(image_path) == 0.0, suffix


def test_other_loaders_formats_are_never_probed(tmp_path: Path) -> None:
    """Handing every dropped table to FFmpeg's detector is both slow and risky."""
    for suffix in (".csv", ".json", ".npy", ".wav", ".avv"):
        candidate = tmp_path / f"data{suffix}"
        candidate.write_bytes(b"0,1,2\n")
        assert VideoStandardLoader.can_open(candidate) == 0.0, suffix


def test_a_probed_match_never_outranks_a_format_specific_loader() -> None:
    """FFmpeg's detection is permissive; the score has to respect that.

    A probed video scores below CSVLoader's 0.8 so that a misdetected table can
    never be opened as a camera, whatever FFmpeg makes of its bytes.
    """
    from avialsync.loaders.csv_loader import CSVLoader

    probed_score = 0.5
    assert probed_score < CSVLoader.can_open(Path("anything.csv"))


def test_an_unreadable_file_is_declined_rather_than_raising(tmp_path: Path) -> None:
    """`can_open` runs on every dropped path; raising there costs the whole drop."""
    junk = tmp_path / "mystery.unknown"
    junk.write_bytes(b"\x00\x01\x02 not a container")

    assert VideoStandardLoader.can_open(junk) == 0.0
    assert VideoStandardLoader.can_open(tmp_path / "absent.unknown") == 0.0
