from __future__ import annotations

from fractions import Fraction

import av
import numpy as np
import pytest

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
