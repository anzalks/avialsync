from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest

from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.pyramid import PyramidBuilder, PyramidReader
from avialsync.core.timeline import TimeMap
from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.pyav_reader import PyAVReader
from avialsync.engine.stimulus_grid_export import GridLabels, GridVideo
from avialsync.engine.stimulus_grid_worker import (
    StimulusEventScanWorker,
    StimulusGridExportWorker,
    StimulusTimelineWorker,
)
from avialsync.engine.transcode import encode_video

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


def test_timeline_preview_copies_bounded_pyramid_result(tmp_path: Path) -> None:
    PyramidBuilder(tmp_path, "stimulus").build_and_save(
        np.arange(10_000, dtype=np.float64), np.ones(10_000)
    )
    reader = MappedChannelReader(PyramidReader(tmp_path, "stimulus"), TimeMap())
    worker = StimulusTimelineWorker(2, ReaderReference.from_reader(reader))
    results: list[tuple[int, object]] = []
    worker.finished.connect(lambda *args: results.append(args))

    worker.run()

    assert results[0][0] == 2
    _bounds, times, low, high, _gaps = results[0][1]
    assert len(times) <= 1200
    assert len(low) == len(high) == len(times)


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


def test_grid_export_refuses_to_replace_a_source_video(tmp_path) -> None:
    source = tmp_path / "camera.mp4"
    image = np.full((36, 64, 3), 128, dtype=np.uint8)
    encode_video(source, [(image, 0.0), (image, 0.1)], rate=Fraction(10, 1))
    original = source.read_bytes()
    errors: list[str] = []
    worker = StimulusGridExportWorker(
        (GridVideo(source, "Camera"),), (0.1,), 0.1, 0.1, source, 10, _LABELS
    )
    worker.error.connect(errors.append)

    worker.run()

    assert errors and "separate from the source videos" in errors[0]
    assert source.read_bytes() == original
    assert list(tmp_path.iterdir()) == [source]


def test_cancelled_grid_export_preserves_existing_destination(tmp_path, qapp) -> None:
    source = tmp_path / "camera.mp4"
    destination = tmp_path / "comparison.mp4"
    image = np.full((36, 64, 3), 128, dtype=np.uint8)
    encode_video(source, [(image, 0.0), (image, 0.1)], rate=Fraction(10, 1))
    destination.write_bytes(b"previous export")
    cancelled: list[bool] = []
    worker = StimulusGridExportWorker(
        (GridVideo(source, "Camera"),), (0.1,), 0.1, 0.1, destination, 10, _LABELS
    )
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.cancel()

    worker.run()

    assert cancelled == [True]
    assert destination.read_bytes() == b"previous export"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["camera.mp4", "comparison.mp4"]


def test_grid_export_replaces_existing_mp4_with_decodable_result(tmp_path, qapp) -> None:
    source = tmp_path / "camera.mp4"
    destination = tmp_path / "comparison.mp4"
    image = np.full((36, 64, 3), 128, dtype=np.uint8)
    encode_video(source, [(image, 0.0), (image, 0.1)], rate=Fraction(10, 1))
    destination.write_bytes(b"previous export")
    finished: list[tuple[str, bool]] = []
    errors: list[str] = []
    worker = StimulusGridExportWorker(
        (GridVideo(source, "Camera"),), (0.1,), 0.1, 0.1, destination, 10, _LABELS
    )
    worker.finished.connect(lambda path, replaced: finished.append((path, replaced)))
    worker.error.connect(errors.append)

    worker.run()

    assert finished == [(str(destination), True)]
    assert not errors
    with av.open(str(destination)) as container:
        assert len(list(container.decode(video=0))) == 2
    assert sorted(path.name for path in tmp_path.iterdir()) == ["camera.mp4", "comparison.mp4"]


def test_worker_publishes_vfr_h264_with_source_timestamps(tmp_path, qapp) -> None:
    source = tmp_path / "high_speed.mp4"
    destination = tmp_path / "comparison.mp4"
    image = np.full((18, 32, 3), (120, 150, 180), dtype=np.uint8)
    source_times = np.arange(46, dtype=np.float64) / 230
    encode_video(
        source,
        ((image, float(time)) for time in source_times),
        rate=Fraction(230, 1),
    )
    with PyAVReader(source) as reader:
        source_times = reader.frame_times.copy()
    finished: list[tuple[str, bool]] = []
    errors: list[str] = []
    worker = StimulusGridExportWorker(
        (GridVideo(source, "High-speed camera"),),
        (0.0,),
        0.0,
        0.2,
        destination,
        30,
        _LABELS,
        playback_speed=0.130435,
    )
    worker.finished.connect(lambda path, replaced: finished.append((path, replaced)))
    worker.error.connect(errors.append)

    worker.run()

    assert finished == [(str(destination), False)]
    assert not errors
    with av.open(str(destination)) as container:
        stream = container.streams.video[0]
        presentation_times = [
            float(frame.pts * frame.time_base) for frame in container.decode(stream)
        ]
    assert presentation_times == pytest.approx((source_times / 0.130435).tolist(), abs=2e-6)
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "comparison.mp4",
        "high_speed.mp4",
    ]


def test_unexpected_worker_exception_is_reported_and_temp_file_removed(
    tmp_path, monkeypatch
) -> None:
    destination = tmp_path / "comparison.mp4"
    temporary_files: list[Path] = []

    def fail_export(_videos, _events, _before, _after, output_path, *_args, **_kwargs) -> None:
        temporary = Path(output_path)
        temporary_files.append(temporary)
        assert temporary.exists()
        assert not temporary.name.startswith(".")
        assert ".exporting." in temporary.name
        assert temporary.name.endswith(".part.mp4")
        raise TypeError("unexpected frame payload")

    monkeypatch.setattr("avialsync.engine.stimulus_grid_worker.export_stimulus_grid", fail_export)
    errors: list[str] = []
    worker = StimulusGridExportWorker(
        (GridVideo(tmp_path / "camera.mp4", "Camera"),),
        (0.1,),
        0.1,
        0.1,
        destination,
        30,
        _LABELS,
    )
    worker.error.connect(errors.append)

    worker.run()

    assert errors == ["unexpected frame payload"]
    assert len(temporary_files) == 1
    assert not temporary_files[0].exists()
    assert list(tmp_path.iterdir()) == []


def test_failed_publish_preserves_existing_mp4(tmp_path, qapp, monkeypatch) -> None:
    source = tmp_path / "camera.mp4"
    destination = tmp_path / "comparison.mp4"
    image = np.full((36, 64, 3), 128, dtype=np.uint8)
    encode_video(source, [(image, 0.0), (image, 0.1)], rate=Fraction(10, 1))
    destination.write_bytes(b"previous export")

    original_replace = type(destination).replace

    def denied_replace(path, target):
        if target == destination:
            raise PermissionError("The old MP4 is open in another application")
        return original_replace(path, target)

    monkeypatch.setattr(type(destination), "replace", denied_replace)
    finished: list[tuple[str, bool]] = []
    errors: list[str] = []
    worker = StimulusGridExportWorker(
        (GridVideo(source, "Camera"),), (0.1,), 0.1, 0.1, destination, 10, _LABELS
    )
    worker.finished.connect(lambda path, replaced: finished.append((path, replaced)))
    worker.error.connect(errors.append)

    worker.run()

    assert not finished
    assert errors and "old MP4 is open" in errors[0]
    assert destination.read_bytes() == b"previous export"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["camera.mp4", "comparison.mp4"]
