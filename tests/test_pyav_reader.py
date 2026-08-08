"""Unit tests for the PyAV exact-frame reader.

Frame *identity* is proven in ``tests/test_frame_identity.py`` against pixels.
This file covers the machinery around it: how the timestamp table is built, when
the reader re-seeks instead of walking forward, what the frame window keeps, and
how it fails.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from avialsync.core.errors import SourceOpenError
from avialsync.engine.pyav_reader import PyAVReader, to_rgb_array
from tests.util_framestrip import decode_frame_strip
from tests.util_pyav_fixtures import cfr_times, vfr_times, write_video

pytest.importorskip("av")

GOP = 30
FRAME_COUNT = 180


@pytest.fixture(scope="module")
def long_gop_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("reader") / "long_gop.mp4"
    write_video(path, frame_times=cfr_times(FRAME_COUNT), gop_size=GOP)
    return path


def test_the_fixture_really_demuxes_out_of_order(long_gop_video: Path) -> None:
    """Guard the guard: without B-frames the display-order sort proves nothing."""
    import av

    with av.open(str(long_gop_video)) as container:
        stream = container.streams.video[0]
        demuxed = [packet.pts for packet in container.demux(stream) if packet.pts is not None]

    assert demuxed != sorted(demuxed), (
        "fixture encoded without B-frames, so it can no longer catch a pts table "
        "left in decode order — check the encoder preset in util_pyav_fixtures"
    )


def test_the_timestamp_table_is_sorted_into_display_order(long_gop_video: Path) -> None:
    """Packets arrive in decode order; every lookup assumes display order."""
    with PyAVReader(long_gop_video) as reader:
        assert reader.frame_count == FRAME_COUNT
        assert np.all(np.diff(reader.frame_times) > 0)
        np.testing.assert_allclose(reader.frame_times, cfr_times(FRAME_COUNT), atol=1e-6)


def test_walking_forward_inside_a_gop_does_not_re_seek(
    long_gop_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The crossover is measured in frames against GOP size, never in seconds."""
    with PyAVReader(long_gop_video, max_cached_frames=1) as reader:
        seeks: list[int] = []
        original = reader._seek_to_keyframe_for

        def counting_seek(target: int) -> None:
            seeks.append(target)
            original(target)

        monkeypatch.setattr(reader, "_seek_to_keyframe_for", counting_seek)

        # One seek to reach the middle of a GOP...
        reader.frame_at_index(GOP + 5)
        assert len(seeks) == 1

        # ...then every forward step inside it walks, because walking costs
        # fewer frames than returning to the keyframe would.
        for index in range(GOP + 6, 2 * GOP):
            reader.frame_at_index(index)
        assert len(seeks) == 1

        # Crossing into the next GOP is still a walk: the decoder is behind the
        # target, and decoding on past the boundary is cheaper than re-seeking
        # to a keyframe it is about to pass anyway.
        reader.frame_at_index(2 * GOP + 1)
        assert len(seeks) == 1

        # Going backwards cannot be walked at all.
        reader.frame_at_index(5)
        assert len(seeks) == 2


def test_a_jump_seeks_to_the_covering_keyframe_not_the_start(
    long_gop_video: Path,
) -> None:
    """A far jump must cost one GOP of decode, not the whole file."""
    with PyAVReader(long_gop_video, max_cached_frames=4) as reader:
        target = 5 * GOP + 7
        frame = reader.frame_at_index(target)
        assert decode_frame_strip(to_rgb_array(frame)) == target
        assert reader._keyframe_index_for(target) == 5 * GOP


def test_the_frame_window_evicts_oldest_first(long_gop_video: Path) -> None:
    """The cache is a window on where the user just was, bounded by frames."""
    with PyAVReader(long_gop_video, max_cached_frames=4) as reader:
        for index in range(40, 48):
            reader.frame_at_index(index)
        assert len(reader._cache) == 4
        assert sorted(reader._cache) == [44, 45, 46, 47]


def test_the_cache_is_keyed_by_integer_index_not_float_time(
    long_gop_video: Path,
) -> None:
    """Two float probes in one interval must be one entry, never two."""
    with PyAVReader(long_gop_video, max_cached_frames=4) as reader:
        reader.frame_at_time(50 / 30.0 + 0.0001)
        before = len(reader._cache)
        reader.frame_at_time(50 / 30.0 + 0.0300)
        assert len(reader._cache) == before
        assert list(reader._cache)[-1] == 50


def test_variable_rate_frames_resolve_by_timestamp_not_by_nominal_rate(
    tmp_path: Path,
) -> None:
    """``t * fps`` arithmetic is wrong on VFR footage; the table is not."""
    path = tmp_path / "vfr.mp4"
    written = write_video(path, frame_times=vfr_times(60), gop_size=15)

    with PyAVReader(path) as reader:
        for index in (0, 1, 17, 42, 59):
            midpoint = float(written[index])
            if index + 1 < len(written):
                midpoint = (midpoint + float(written[index + 1])) / 2.0
            frame = reader.frame_at_time(midpoint)
            assert decode_frame_strip(to_rgb_array(frame)) == index


def test_time_and_index_round_trip(long_gop_video: Path) -> None:
    """Naming a frame and finding it again must be the same operation."""
    with PyAVReader(long_gop_video) as reader:
        for index in (0, 1, 77, FRAME_COUNT - 1):
            assert reader.index_at_time(reader.time_at_index(index)) == index


def test_opening_a_non_video_file_raises_a_typed_error(tmp_path: Path) -> None:
    """A bad file is a source error the UI can phrase, not a stray FFmpeg one."""
    path = tmp_path / "not_video.mp4"
    path.write_bytes(b"this is not a container")
    with pytest.raises(SourceOpenError):
        PyAVReader(path)


def test_opening_a_missing_file_raises_a_typed_error(tmp_path: Path) -> None:
    with pytest.raises(SourceOpenError):
        PyAVReader(tmp_path / "absent.mp4")


def test_the_reader_needs_no_qt(long_gop_video: Path) -> None:
    """``engine/pyav_reader.py`` must stay headless and worker-thread safe."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import avialsync.engine.pyav_reader; "
            "sys.exit(1 if 'PySide6.QtCore' in sys.modules else 0)",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"importing the reader pulled in Qt: {result.stderr}"
