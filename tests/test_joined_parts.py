"""A stream recorded in parts, joined into one source with the gaps kept (D-219)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from avialsync.core.source import ChannelInfo, TimeSeriesSource
from avialsync.engine.pyav_reader import PyAVReader
from avialsync.loaders.joined_parts import (
    JOINED_PARTS,
    JoinedTimeSeriesSource,
    JoinedVideoSource,
    loader_name,
)
from tests.util_pyav_fixtures import cfr_times, write_video


def test_a_cameras_parts_play_as_one_inter_frame_video_with_the_gap_kept(tmp_path: Path) -> None:
    first, second = tmp_path / "trial_1.mp4", tmp_path / "trial_2.mp4"
    write_video(first, frame_times=cfr_times(45), gop_size=10)
    write_video(second, frame_times=cfr_times(45), gop_size=10)
    loader = JoinedVideoSource()
    loader.open(
        first / JOINED_PARTS,
        {"parts": [{"path": str(first), "start": 0.0}, {"path": str(second), "start": 60.0}]},
    )
    manifest = loader.prepare(lambda _fraction: None)
    times = loader.frame_times()
    assert len(times) == 90
    assert times[44] == pytest.approx(44 / 30, abs=1e-3)
    assert times[45] == pytest.approx(60.0, abs=1e-3)

    # A frame between two keyframes of the second file is that file's frame.
    with PyAVReader(manifest) as reader:
        frame = reader.frame_at_index(45 + 13)
        assert float(frame.pts * frame.time_base) == pytest.approx(13 / 30, abs=1e-3)
    with PyAVReader(second) as alone:
        expected = alone.frame_at_index(13).to_ndarray(format="rgb24")
    with PyAVReader(manifest) as reader:
        np.testing.assert_array_equal(
            reader.frame_at_index(45 + 13).to_ndarray(format="rgb24"), expected
        )

    again = JoinedVideoSource()
    again.open(first / JOINED_PARTS, {"parts": loader._parts})
    built = manifest.stat().st_mtime_ns
    assert again.prepare(lambda _fraction: None) == manifest
    assert manifest.stat().st_mtime_ns == built  # reused, not rebuilt


def test_a_joined_video_whose_first_part_starts_late_covers_its_frames(tmp_path: Path) -> None:
    """Bounds are where the frames are, not ``(0, duration)``.

    A camera that missed a session's first trials has its first part well after
    the session zero (D-217). Bounds counted from zero ended a whole first-part
    start early, so every later trial showed No Footage over recorded frames.
    """
    first, second = tmp_path / "trial_7.mp4", tmp_path / "trial_8.mp4"
    write_video(first, frame_times=cfr_times(45), gop_size=10)
    write_video(second, frame_times=cfr_times(45), gop_size=10)
    loader = JoinedVideoSource()
    loader.open(
        first / JOINED_PARTS,
        {"parts": [{"path": str(first), "start": 570.0}, {"path": str(second), "start": 900.0}]},
    )
    loader.prepare(lambda _fraction: None)
    times = loader.frame_times()
    start, end = loader.time_bounds()
    assert start == pytest.approx(times[0]) == pytest.approx(570.0, abs=1e-3)
    assert end == pytest.approx(times[-1]) == pytest.approx(900.0 + 44 / 30, abs=1e-3)


class FakePart(TimeSeriesSource):
    """Three samples at 10 Hz, each part's value from its own config."""

    @classmethod
    def can_open(cls, path: Path) -> float:
        return 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        self._value = float(config["value"])
        self._names = list(config.get("channels", ["x"]))

    def channels(self) -> list[ChannelInfo]:
        return [ChannelInfo(name, "", "Float64", 10.0) for name in self._names]

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        yield np.arange(3) / 10.0, np.full(3, self._value)


def test_a_streams_parts_are_read_by_their_own_loader_at_their_start(tmp_path: Path) -> None:
    loader = JoinedTimeSeriesSource()
    loader.open(
        tmp_path / "a",
        {
            "part_loader": loader_name(FakePart),
            "parts": [
                {"path": str(tmp_path / "a"), "start": 0.0, "config": {"value": 1}},
                {"path": str(tmp_path / "b"), "start": 60.0, "config": {"value": 2}},
            ],
        },
    )
    assert [channel.name for channel in loader.channels()] == ["x"]
    chunks = list(loader.read_chunks("x"))
    times = np.concatenate([t for t, _v in chunks])
    values = np.concatenate([v for _t, v in chunks])
    np.testing.assert_allclose(times, [0.0, 0.1, 0.2, 60.0, 60.1, 60.2])
    np.testing.assert_allclose(values, [1, 1, 1, 2, 2, 2])


def test_a_channel_one_part_did_not_record_is_missing_there_not_invented(
    tmp_path: Path,
) -> None:
    """A later block of trials tracked more markers: the earlier ones read NaN for them."""
    loader = JoinedTimeSeriesSource()
    loader.open(
        tmp_path / "a",
        {
            "part_loader": loader_name(FakePart),
            "parts": [
                {"path": "a", "start": 0.0, "config": {"value": 1, "channels": ["x"]}},
                {"path": "b", "start": 60.0, "config": {"value": 2, "channels": ["y", "x"]}},
                {"path": "c", "start": 90.0, "config": {"value": 3, "channels": ["y"]}},
            ],
        },
    )
    assert [channel.name for channel in loader.channels()] == ["x", "y"]
    chunks = list(loader.read_all_chunks())
    assert all(set(chunk) == {"x", "y"} for chunk in chunks)
    x = np.concatenate([chunk["x"][1] for chunk in chunks])
    y = np.concatenate([chunk["y"][1] for chunk in chunks])
    times = np.concatenate([chunk["x"][0] for chunk in chunks])
    np.testing.assert_allclose(times, [0, 0.1, 0.2, 60, 60.1, 60.2, 90, 90.1, 90.2])
    np.testing.assert_array_equal(np.isnan(x), [0, 0, 0, 0, 0, 0, 1, 1, 1])
    np.testing.assert_array_equal(np.isnan(y), [1, 1, 1, 0, 0, 0, 0, 0, 0])


def test_a_missing_part_loader_is_named() -> None:
    from avialsync.core.errors import SourceOpenError

    with pytest.raises(SourceOpenError, match="not installed"):
        JoinedTimeSeriesSource().open(
            Path("x"), {"part_loader": "nowhere:Nothing", "parts": [{"path": "x", "start": 0}]}
        )


def test_a_label_spelled_two_ways_across_parts_is_one_channel(tmp_path: Path) -> None:
    """``Back2`` then ``back2``: one marker, and one file on a case-insensitive disk."""
    loader = JoinedTimeSeriesSource()
    loader.open(
        tmp_path / "a",
        {
            "part_loader": loader_name(FakePart),
            "parts": [
                {"path": "a", "start": 0.0, "config": {"value": 1, "channels": ["Back2_x"]}},
                {"path": "b", "start": 60.0, "config": {"value": 2, "channels": ["back2_x"]}},
            ],
        },
    )
    assert [channel.name for channel in loader.channels()] == ["Back2_x"]
    values = np.concatenate([chunk["Back2_x"][1] for chunk in loader.read_all_chunks()])
    np.testing.assert_allclose(values, [1, 1, 1, 2, 2, 2])


def test_two_spellings_in_one_part_stay_two_channels(tmp_path: Path) -> None:
    loader = JoinedTimeSeriesSource()
    loader.open(
        tmp_path / "a",
        {
            "part_loader": loader_name(FakePart),
            "parts": [
                {"path": "a", "start": 0.0, "config": {"value": 1, "channels": ["A", "a"]}},
            ],
        },
    )
    assert [channel.name for channel in loader.channels()] == ["A", "a"]


class FakeFramePart(FakePart):
    """Pose on a video's frames: times are frame index / fps."""

    def is_frame_indexed(self) -> bool:
        return True


def test_frame_indexed_parts_number_on_through_the_joined_video(tmp_path: Path) -> None:
    """The video's own frame times place them; a shift by seconds names no frame."""
    loader = JoinedTimeSeriesSource()
    loader.open(
        tmp_path / "a",
        {
            "part_loader": loader_name(FakeFramePart),
            "parts": [
                {"path": "a", "start": 0.0, "config": {"value": 1, "fps": 10, "frame_count": 3}},
                {"path": "b", "start": 60.0, "config": {"value": 2, "fps": 10, "frame_count": 3}},
            ],
        },
    )
    assert loader.is_frame_indexed()
    times = np.concatenate([t for t, _v in loader.read_chunks("x")])
    np.testing.assert_allclose(times * 10, [0, 1, 2, 3, 4, 5])


def test_a_joined_sources_sidecars_sit_beside_its_first_file(tmp_path: Path) -> None:
    from avialsync.core.artifacts import get_kind
    from avialsync.core.sidecar_names import beside, on_disk

    video = tmp_path / "trial_1.avi"
    video.write_bytes(b"")
    joined = video / JOINED_PARTS
    assert on_disk(joined) == tmp_path / "trial_1_avi_joined_parts"
    assert beside(joined, "_avialfix.csv").parent == tmp_path
    marker_file = get_kind("custom-markers-2d").target_for(joined)
    assert marker_file == tmp_path / "trial_1_avi_joined_parts_custom_markers.csv"
