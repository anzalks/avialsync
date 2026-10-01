from __future__ import annotations

import numpy as np

from avialsync.engine.stimulus_grid_export import GridLabels, GridVideo
from avialsync.engine.stimulus_grid_worker import (
    StimulusEventScanWorker,
    StimulusGridExportWorker,
)

_LABELS = GridLabels(
    title="Title",
    event="Event {index} {time}",
    no_footage="No footage",
    ruler="Ruler {before} {after}",
    current="Current {time}",
    no_signal="No signal",
    frame="Frame {index}",
)


class _Reader:
    def sample_count(self) -> int:
        return 6

    def iter_raw_chunks(self):
        yield np.array([0.0, 0.1, 0.2]), np.array([0.0, 1.0, 1.0])
        yield np.array([0.3, 0.4, 0.5]), np.array([0.0, 0.0, 1.0])


class _Reference:
    channel_id = "stimulus"

    def open(self) -> _Reader:
        return _Reader()


def test_event_scan_finds_rising_edges_across_chunk_boundaries() -> None:
    worker = StimulusEventScanWorker(_Reference(), threshold=0.5, min_interval=0.0)
    results: list[tuple[float, ...]] = []
    worker.finished.connect(results.append)

    worker.run()

    assert results == [(0.1, 0.5)]


def test_event_scan_can_be_cancelled_between_chunks() -> None:
    worker = StimulusEventScanWorker(_Reference(), threshold=0.5, min_interval=0.0)
    cancelled: list[bool] = []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.cancel()

    worker.run()

    assert cancelled == [True]


def test_failed_grid_export_leaves_existing_destination_untouched(tmp_path) -> None:
    destination = tmp_path / "comparison.mp4"
    destination.write_bytes(b"existing output")
    errors: list[str] = []
    worker = StimulusGridExportWorker(
        (GridVideo(tmp_path / "missing.mp4", "Missing camera"),),
        (1.0,),
        0.5,
        1.0,
        destination,
        30,
        _LABELS,
    )
    worker.error.connect(errors.append)

    worker.run()

    assert errors
    assert destination.read_bytes() == b"existing output"
    assert list(tmp_path.iterdir()) == [destination]
