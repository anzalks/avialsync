"""Performance guard for event-aligned multi-camera composition."""

from __future__ import annotations

from fractions import Fraction

import numpy as np
import pytest

from avialsync.engine.stimulus_grid_export import GridLabels, GridVideo, export_stimulus_grid
from avialsync.engine.transcode import encode_video

_LABELS = GridLabels(
    title="Stimulus-aligned comparison",
    event="Event {index} {time:.3f} s",
    no_footage="No footage",
    ruler="{before:.2f} s    Stimulus    +{after:.2f} s",
    current="Current: {time:+.2f} s",
)
_GRID_BUDGET_S = 2.0


@pytest.mark.benchmark(group="stimulus-grid-export")
def test_bench_three_camera_four_event_grid(benchmark, tmp_path, qapp) -> None:
    """Render six output frames while comparing four events across three cameras."""
    source = tmp_path / "camera.mp4"
    output = tmp_path / "comparison.mp4"
    frame = np.full((72, 128, 3), (80, 120, 160), dtype=np.uint8)
    encode_video(
        source,
        ((frame, index / 10) for index in range(31)),
        rate=Fraction(10, 1),
    )
    videos = tuple(GridVideo(source, f"Camera {index}") for index in range(3))
    events = (0.5, 1.0, 1.5, 2.0)

    benchmark(
        export_stimulus_grid,
        videos,
        events,
        0.2,
        0.4,
        output,
        _LABELS,
        fps=10,
    )

    if benchmark.stats is None:
        pytest.skip("benchmark statistics unavailable (benchmarks disabled)")
    assert benchmark.stats.stats.median < _GRID_BUDGET_S
