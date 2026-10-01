from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest

from avialsync.core.errors import ExportError
from avialsync.core.pyramid import PyramidBuilder
from avialsync.core.timeline import TimeMap
from avialsync.engine import stimulus_grid_export
from avialsync.engine.display_pipeline import DisplayLevels
from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.pyav_reader import PyAVReader
from avialsync.engine.stimulus_grid_export import (
    MAX_GRID_EVENTS,
    GridLabels,
    GridSignal,
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
    no_signal="No signal",
    frame="Frame {index}",
)


def test_three_cameras_and_twelve_events_make_a_wide_grid() -> None:
    layout = plan_grid(video_count=3, event_count=12, before=0.5, after=1.5, has_signal=True)

    assert layout.width <= 2560
    assert layout.height <= 4320
    assert layout.width % 2 == 0
    assert layout.height % 2 == 0
    assert layout.width > 3 * layout.height
    assert layout.cell_rect(0, 11).x() > layout.cell_rect(0, 0).x()
    assert layout.cell_rect(0, 11).y() == layout.cell_rect(0, 0).y()
    assert layout.cell_rect(2, 0).y() > layout.cell_rect(0, 0).y()
    assert layout.cell_rect(2, 11).bottom() < layout.height - layout.bottom_band


def test_three_camera_twelve_event_export_puts_cameras_in_rows(tmp_path, qapp) -> None:
    videos = []
    for camera_index in range(3):
        path = tmp_path / f"camera_{camera_index}.mp4"
        frames = [
            (
                np.full(
                    (36, 64, 3),
                    (35 + 65 * camera_index, 25 + 12 * event_index, 70),
                    dtype=np.uint8,
                ),
                float(event_index),
            )
            for event_index in range(12)
        ]
        encode_video(path, frames, rate=Fraction(1, 1))
        videos.append(GridVideo(path, f"Camera {camera_index + 1}"))

    destination = tmp_path / "wide.mp4"
    export_stimulus_grid(
        videos,
        [float(index) for index in range(12)],
        before=0.0,
        after=1.0,
        destination=destination,
        labels=_LABELS,
        fps=1,
    )
    with av.open(str(destination)) as container:
        frames = list(container.decode(video=0))
    assert len(frames) == 1
    image = frames[0].to_ndarray(format="rgb24")
    layout = plan_grid(3, 12, 0.0, 1.0)
    assert image.shape[:2] == (layout.height, layout.width)
    for camera_index in range(3):
        for event_index in range(12):
            cell = layout.cell_rect(camera_index, event_index)
            pixel = image[cell.y() + cell.height() // 2, cell.x() + cell.width() // 2]
            assert abs(int(pixel[0]) - (35 + 65 * camera_index)) < 20
            assert abs(int(pixel[1]) - (25 + 12 * event_index)) < 20


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
    assert len(frames) == 3
    assert [float(frame.pts * frame.time_base) for frame in frames] == pytest.approx(
        [0.0, 0.1, 0.2]
    )
    assert float(stream.duration * stream.time_base) == pytest.approx(0.3)
    assert (frames[0].width, frames[0].height) == (expected.width, expected.height)


@pytest.mark.parametrize("speed", [0.130435, 1.0, 2.0])
def test_230_fps_source_keeps_every_frame_at_each_export_speed(
    tmp_path, qapp, monkeypatch, speed: float
) -> None:
    source = tmp_path / "high_speed.mp4"
    frame = np.full((18, 32, 3), (120, 150, 180), dtype=np.uint8)
    encode_video(
        source,
        [(frame, index / 230) for index in range(46)],
        rate=Fraction(230, 1),
    )
    with PyAVReader(source) as reader:
        source_times = reader.frame_times.copy()
    requested: list[int] = []
    reader_type = stimulus_grid_export.PyAVReader
    frame_at_index = reader_type.frame_at_index

    def record_frame_index(reader, index):
        requested.append(index)
        return frame_at_index(reader, index)

    monkeypatch.setattr(reader_type, "frame_at_index", record_frame_index)
    destination = tmp_path / "grid.mp4"
    export_stimulus_grid(
        [GridVideo(source, "High-speed camera")],
        [0.0],
        before=0.0,
        after=0.2,
        destination=destination,
        labels=_LABELS,
        fps=30,
        playback_speed=speed,
    )

    with av.open(str(destination)) as container:
        stream = container.streams.video[0]
        frames = list(container.decode(stream))
        duration = float(stream.duration * stream.time_base)
    assert len(frames) == 46
    assert duration == pytest.approx(0.2 / speed, abs=2e-6)
    assert requested == list(range(46))
    assert [float(frame.pts * frame.time_base) for frame in frames] == pytest.approx(
        (source_times / speed).tolist(), abs=2e-6
    )


def test_camera_event_union_retains_offset_vfr_frames(tmp_path, qapp, monkeypatch) -> None:
    paths = (tmp_path / "first.mp4", tmp_path / "second.mp4")
    frame = np.full((18, 32, 3), (120, 150, 180), dtype=np.uint8)
    camera_times = (
        (0.0, 0.04, 0.08, 1.0, 1.04, 1.08),
        (0.01, 0.03, 0.095, 1.01, 1.03, 1.095),
    )
    for path, times in zip(paths, camera_times, strict=True):
        encode_video(path, [(frame, time) for time in times], rate=Fraction(30, 1))

    seen: dict[Path, set[int]] = {path: set() for path in paths}
    reader_type = stimulus_grid_export.PyAVReader
    frame_at_index = reader_type.frame_at_index

    def record_frame_index(reader, index):
        seen[reader.path].add(index)
        return frame_at_index(reader, index)

    monkeypatch.setattr(reader_type, "frame_at_index", record_frame_index)
    destination = tmp_path / "union.mp4"
    export_stimulus_grid(
        [GridVideo(paths[0], "First"), GridVideo(paths[1], "Second", TimeMap(offset=0.005))],
        [0.0, 1.0],
        before=0.0,
        after=0.12,
        destination=destination,
        labels=_LABELS,
        fps=10,
    )

    assert all(indices == set(range(6)) for indices in seen.values())
    with av.open(str(destination)) as container:
        stream = container.streams.video[0]
        packets = [packet for packet in container.demux(stream) if packet.pts is not None]
    presentation = sorted(float(packet.pts * packet.time_base) for packet in packets)
    assert presentation == pytest.approx([0.0, 0.005, 0.025, 0.04, 0.08, 0.09], abs=2e-6)
    assert sorted(float(packet.duration * packet.time_base) for packet in packets) == pytest.approx(
        sorted([0.005, 0.02, 0.015, 0.04, 0.01, 0.03]), abs=2e-6
    )


def test_timed_encoder_reports_timestamps_it_cannot_preserve(tmp_path) -> None:
    frame = np.zeros((18, 32, 3), dtype=np.uint8)
    with pytest.raises(ExportError, match="too close to preserve every frame"):
        encode_video(
            tmp_path / "too_close.mp4",
            [(frame, 0.0), (frame, 0.0000001)],
            rate=Fraction(30, 1),
            time_base=Fraction(1, 1_000_000),
            end_seconds=0.01,
        )


def test_last_frame_is_shown_for_its_interval_then_coverage_ends(tmp_path, qapp) -> None:
    source = tmp_path / "source.mp4"
    destination = tmp_path / "comparison.mp4"
    frame = np.full((18, 32, 3), (20, 40, 210), dtype=np.uint8)
    encode_video(source, [(frame, 0.0), (frame, 0.1)], rate=Fraction(10, 1))
    export_stimulus_grid(
        [GridVideo(source, "Camera")],
        [0.0],
        before=0.0,
        after=0.4,
        destination=destination,
        labels=_LABELS,
        fps=10,
    )

    with av.open(str(destination)) as container:
        frames = list(container.decode(video=0))
    cell = plan_grid(1, 1, 0.0, 0.4).cell_rect(0, 0)
    x, y = cell.x() + 20, cell.y() + 20
    last_interval = frames[1].to_ndarray(format="rgb24")[y, x]
    after_end = frames[2].to_ndarray(format="rgb24")[y, x]
    assert last_interval[2] > 130
    assert after_end[2] < 100


@pytest.mark.parametrize("speed", [0.0, -0.5, 10.1, float("nan")])
def test_grid_rejects_invalid_playback_speed(tmp_path, speed: float) -> None:
    with pytest.raises(ExportError, match="Playback speed"):
        export_stimulus_grid(
            [GridVideo(tmp_path / "unused.mp4", "Camera")],
            [0.0],
            0.0,
            1.0,
            tmp_path / "unused_export.mp4",
            _LABELS,
            playback_speed=speed,
        )


def test_grid_exports_one_shared_trace_for_aligned_event_windows(tmp_path, qapp) -> None:
    source = tmp_path / "source.mp4"
    destination = tmp_path / "comparison.mp4"
    frame = np.full((36, 64, 3), (20, 40, 210), dtype=np.uint8)
    encode_video(source, [(frame, index / 10) for index in range(31)], rate=Fraction(10, 1))
    times = np.arange(0.0, 3.0, 0.01)
    values = np.where(((times >= 0.5) & (times < 0.7)) | ((times >= 1.5) & (times < 1.7)), 1.0, 0.0)
    PyramidBuilder(tmp_path, "ttl").build_and_save(times, values)
    signal = GridSignal(ReaderReference(tmp_path, "ttl", offset=-0.25), "TTL", 0.5)

    traces = stimulus_grid_export._read_signal_traces(signal, (0.75, 1.75), 0.2, 0.4, 640)
    assert len(traces) == 2
    assert all(np.any((trace.times >= 0.0) & (trace.high == 1.0)) for trace in traces)
    assert all(len(trace.times) <= 640 for trace in traces)

    export_stimulus_grid(
        [GridVideo(source, "Camera A"), GridVideo(source, "Camera B")],
        [0.75, 1.75],
        before=0.2,
        after=0.4,
        destination=destination,
        labels=_LABELS,
        fps=5,
        signal=signal,
    )
    with av.open(str(destination)) as container:
        frames = list(container.decode(video=0))
    layout = plan_grid(2, 2, 0.2, 0.4, has_signal=True)
    image = frames[0].to_ndarray(format="rgb24")
    assert len(frames) == 7
    assert image.shape[:2] == (layout.height, layout.width)
    # The chart spans both event columns, below every camera row.
    chart = image[layout.height - 140 : layout.height - 50, 110 : layout.width - 28]
    assert np.count_nonzero((chart[:, :, 1] > 100) & (chart[:, :, 2] > 100)) > 50
    cell = layout.cell_rect(0, 0)
    pixel_on_former_video_marker = image[
        cell.y() + cell.height() // 2, cell.x() + cell.width() // 2
    ]
    assert pixel_on_former_video_marker[2] > 130
    assert pixel_on_former_video_marker[0] < 100


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
    requested_indices: list[int] = []
    reader_type = stimulus_grid_export.PyAVReader
    index_at_time = reader_type.index_at_time
    frame_at_index = reader_type.frame_at_index

    def record_source_time(reader, source_time):
        requested_times.append(source_time)
        return index_at_time(reader, source_time)

    def record_frame_index(reader, index):
        requested_indices.append(index)
        return frame_at_index(reader, index)

    monkeypatch.setattr(reader_type, "index_at_time", record_source_time)
    monkeypatch.setattr(reader_type, "frame_at_index", record_frame_index)
    export_stimulus_grid(
        [video],
        [0.1],
        before=0.0,
        after=0.1,
        destination=destination,
        labels=_LABELS,
        fps=10,
    )

    assert requested_times == pytest.approx([0.15, 0.2, 0.3])
    assert requested_indices == [1, 2, 3]


def test_stimulus_grid_applies_high_bit_depth_display_levels(qapp) -> None:
    frame = av.VideoFrame.from_ndarray(
        np.full((36, 64), 1024, dtype=np.uint16),
        format="gray12le",
    )

    class _Reader:
        def index_at_time(self, _source_time):
            return 0

        def frame_at_index(self, _index):
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

    cell = layout.cell_rect(0, 0)
    pixel = image.pixelColor(cell.x() + cell.width() // 2, cell.y() + cell.height() // 2)
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
    with pytest.raises(ExportError):
        plan_grid(video_count, event_count, before, after)
