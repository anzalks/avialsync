from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest

from avialsync.core.timeline import TimeMap
from avialsync.engine import stimulus_grid_export
from avialsync.engine.display_pipeline import DisplayLevels
from avialsync.engine.stimulus_grid_export import (
    MAX_GRID_EVENTS,
    GridLabels,
    GridVideo,
    export_stimulus_grid,
    plan_grid,
)
from avialsync.engine.transcode import encode_video

_LABELS = GridLabels(
    title="Stimulus-aligned comparison",
    event="Event {index}\n{time:.3f} s",
    no_footage="No footage",
    ruler="{before:.2f} s    Stimulus    +{after:.2f} s",
    current="Current: {time:+.2f} s",
)


def test_grid_places_trigger_at_shared_relative_time_position() -> None:
    layout = plan_grid(video_count=3, event_count=4, before=1.5, after=2.5)

    assert layout.width <= 2560
    assert layout.height <= 4320
    assert layout.width % 2 == 0
    assert layout.height % 2 == 0
    assert layout.height > layout.cell_height * 4
    assert layout.trigger_x == round(layout.cell_width * 1.5 / 4.0)


def test_stimulus_grid_export_is_decodable(tmp_path, qapp) -> None:
    source = tmp_path / "source.mp4"
    destination = tmp_path / "comparison.mp4"
    red_frame = np.full((36, 64, 3), (210, 35, 25), dtype=np.uint8)
    blue_frame = np.full((36, 64, 3), (20, 40, 210), dtype=np.uint8)
    encode_video(
        source,
        [(red_frame, 0.0), (blue_frame, 0.1), (blue_frame, 0.2)],
        rate=Fraction(10, 1),
    )

    export_stimulus_grid(
        [GridVideo(source, "Camera A")],
        [0.1],
        before=0.1,
        after=0.2,
        destination=destination,
        labels=_LABELS,
        fps=5,
    )

    with av.open(str(destination)) as container:
        stream = container.streams.video[0]
        frames = list(container.decode(stream))

    expected = plan_grid(video_count=1, event_count=1, before=0.1, after=0.2)
    assert len(frames) == 2
    assert (frames[0].width, frames[0].height) == (expected.width, expected.height)


def test_stimulus_grid_reuses_one_reader_per_camera(tmp_path, qapp, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    destination = tmp_path / "comparison.mp4"
    frame = np.full((36, 64, 3), (80, 120, 160), dtype=np.uint8)
    encode_video(
        source,
        [(frame, 0.0), (frame, 0.1), (frame, 0.2)],
        rate=Fraction(10, 1),
    )
    opened: list[object] = []
    reader_type = stimulus_grid_export.PyAVReader

    def counting_reader(path, max_cached_frames=2):
        opened.append(path)
        return reader_type(path, max_cached_frames)

    monkeypatch.setattr(stimulus_grid_export, "PyAVReader", counting_reader)
    export_stimulus_grid(
        [GridVideo(source, "Camera A"), GridVideo(source, "Camera B")],
        [0.1, 0.2],
        before=0.1,
        after=0.2,
        destination=destination,
        labels=_LABELS,
        fps=5,
    )

    assert len(opened) == 2


def test_stimulus_grid_uses_a_snapshot_of_exact_video_mapping(tmp_path, qapp, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    destination = tmp_path / "comparison.mp4"
    frame = np.full((36, 64, 3), (80, 120, 160), dtype=np.uint8)
    encode_video(
        source,
        [(frame, index / 10) for index in range(5)],
        rate=Fraction(10, 1),
    )
    mapping = TimeMap()
    mapping.set_exact_mapping(
        np.array([0.0, 0.1, 0.2]),
        np.array([0.0, 0.15, 0.4]),
    )
    video = GridVideo(source, "Camera", mapping)
    mapping.set_mapping(0.0, 0.0)

    requested_times: list[float] = []
    reader_type = stimulus_grid_export.PyAVReader
    frame_at_time = reader_type.frame_at_time

    def record_source_time(reader, source_time):
        requested_times.append(source_time)
        return frame_at_time(reader, source_time)

    monkeypatch.setattr(reader_type, "frame_at_time", record_source_time)
    export_stimulus_grid(
        [video],
        [0.1],
        before=0.0,
        after=0.1,
        destination=destination,
        labels=_LABELS,
        fps=10,
    )

    assert requested_times == pytest.approx([0.15])


def test_stimulus_grid_applies_high_bit_depth_display_levels(qapp) -> None:
    frame = av.VideoFrame.from_ndarray(
        np.full((36, 64), 1024, dtype=np.uint16),
        format="gray12le",
    )

    class _Reader:
        def frame_at_time(self, _source_time):
            return frame

    video = GridVideo(
        Path("unused.mp4"),
        "Camera",
        display_levels=DisplayLevels(black=0.4, white=0.6),
    )
    layout = plan_grid(video_count=1, event_count=1, before=0.0, after=0.1)
    image = stimulus_grid_export._render_frame(
        [video],
        [0.0],
        {0: (_Reader(), video.time_map, (0.0, 0.1))},
        layout,
        0.0,
        0.0,
        0.1,
        _LABELS,
    )

    pixel = image.pixelColor(200, 44 + 28 + layout.cell_height // 2)
    assert pixel.red() < 5
    assert pixel.green() < 5
    assert pixel.blue() < 5


@pytest.mark.parametrize(
    ("video_count", "event_count", "before", "after"),
    [
        (0, 1, 1.0, 1.0),
        (1, 0, 1.0, 1.0),
        (1, MAX_GRID_EVENTS + 1, 1.0, 1.0),
        (1, 1, -1.0, 1.0),
        (1, 1, 1.0, 0.0),
    ],
)
def test_grid_rejects_invalid_layout_inputs(
    video_count: int, event_count: int, before: float, after: float
) -> None:
    with pytest.raises(ValueError):
        plan_grid(video_count, event_count, before, after)
