"""Render event-aligned video comparisons as one encoded movie.

Rows are pictures -- cameras, and imaging stacks as the image viewer shows
them (:mod:`~avialsync.engine.stimulus_grid_imaging`) -- with one column per
event. Under them, each chosen sensor group is a full-width band with every
event overlaid (:mod:`~avialsync.engine.stimulus_grid_bands`), D-210.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Sequence
from contextlib import ExitStack
from fractions import Fraction
from heapq import merge
from pathlib import Path

import numpy as np

from avialsync.core.errors import ExportError
from avialsync.core.timeline import TimeMap
from avialsync.engine.pyav_reader import PyAVReader
from avialsync.engine.stimulus_grid_bands import GridBand, GridStream, read_band_traces
from avialsync.engine.stimulus_grid_imaging import GridImaging, ImagingRow
from avialsync.engine.stimulus_grid_layout import (
    MAX_GRID_EVENTS,
    GridLabels,
    GridLayout,
    GridRow,
    GridVideo,
    band_for_signal,
    plan_grid,
)
from avialsync.engine.stimulus_grid_render import (
    RowReader,
    _image_to_rgb,
    _render_background,
    _render_frame,
)
from avialsync.engine.stimulus_grid_trace import GridSignal, GridTrace
from avialsync.engine.transcode import (
    CancelCheck,
    ProgressCallback,
    TranscodeCancelled,
    encode_video,
)

logger = logging.getLogger(__name__)
_OUTPUT_TICKS_PER_SECOND = 1_000_000
__all__ = [
    "GridBand",
    "GridImaging",
    "GridLabels",
    "GridLayout",
    "GridSignal",
    "GridStream",
    "GridTrace",
    "GridVideo",
    "MAX_GRID_EVENTS",
    "export_stimulus_grid",
    "plan_grid",
]


def export_stimulus_grid(
    videos: Sequence[GridRow],
    event_times: Sequence[float],
    before: float,
    after: float,
    destination: Path,
    labels: GridLabels,
    *,
    fps: int = 30,
    playback_speed: float = 1.0,
    signal: GridSignal | None = None,
    bands: Sequence[GridBand] = (),
    high_detail: bool = False,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> None:
    """Encode picture rows by selected event columns, with sensor bands beneath.

    *videos* are the rows in order: cameras (:class:`GridVideo`) and imaging
    stacks (:class:`GridImaging`). Every column advances through the same
    relative-time window. ``fps`` caps composite updates; each row samples
    its mapped frame at every output time. *signal* is the single trigger band
    of earlier exports, used when no *bands* are given.
    """
    if fps < 1 or fps > 120:
        raise ExportError("Output frame rate must be between 1 and 120 fps.")
    if not np.isfinite(playback_speed) or not 0.01 <= playback_speed <= 10.0:
        raise ExportError("Playback speed must be between 0.01x and 10x.")
    if not videos:
        raise ExportError("At least one camera or imaging row is required.")
    if not event_times or len(event_times) > MAX_GRID_EVENTS:
        raise ExportError(f"Select between 1 and {MAX_GRID_EVENTS} stimulus events.")
    events = tuple(float(time) for time in event_times)
    if not all(np.isfinite(time) for time in events) or any(
        right <= left for left, right in zip(events, events[1:], strict=False)
    ):
        raise ExportError("Stimulus event times must be finite and strictly increasing.")
    bands = tuple(bands) or ((band_for_signal(signal),) if signal is not None else ())
    duration = before + after
    output_duration = duration / playback_speed
    destination.parent.mkdir(parents=True, exist_ok=True)

    with ExitStack() as stack:
        readers: dict[int, RowReader] = {}
        aspect_ratios: list[float] = []
        for index, row in enumerate(videos):
            if isinstance(row, GridImaging):
                imaging = ImagingRow(row)
                stack.callback(imaging.close)
                readers[index] = imaging
                aspect_ratios.append(row.aspect_ratio)
                continue
            reader = stack.enter_context(PyAVReader(row.path, max_cached_frames=2))
            reader.stream.thread_type = "SLICE"
            codec = reader.stream.codec_context
            aspect_ratios.append(
                codec.width / codec.height if codec.width > 0 and codec.height > 0 else 16 / 9
            )
            readers[index] = (reader, row.time_map, _reader_bounds(reader, row.time_map))
        layout = plan_grid(
            len(videos),
            len(events),
            before,
            after,
            high_detail=high_detail,
            cell_aspect_ratios=aspect_ratios,
            bands=bands,
        )
        traces = tuple(
            read_band_traces(band, events, before, after, layout.width) for band in bands
        )
        background = _render_background(
            videos, events, layout, before, after, labels, bands, traces
        )

        def frames() -> Iterator[tuple[np.ndarray, float]]:
            for output_time in _frame_schedule(readers, events, before, after, fps, playback_speed):
                if should_cancel is not None and should_cancel():
                    raise TranscodeCancelled
                relative_time = output_time * playback_speed - before
                image = _render_frame(
                    videos,
                    events,
                    readers,
                    layout,
                    relative_time,
                    before,
                    after,
                    labels,
                    bands=bands,
                    background=background,
                )
                yield _image_to_rgb(image), output_time

        def report_progress(seconds: float) -> None:
            if progress is not None:
                progress(min(1.0, seconds / output_duration))

        from avialsync.core.artifact_io import publish

        def write(temporary: Path) -> None:
            from avialsync.core.artifact_provenance import record

            provenance = record(
                "stimulus-grid",
                tuple(row.path for row in videos),
                time_maps={
                    row.label: {
                        "offset_seconds": row.time_map.offset,
                        "drift_ms_per_hour": row.time_map.drift_ms_per_hour,
                    }
                    for row in videos
                },
            )
            encode_video(
                temporary,
                frames(),
                rate=Fraction(fps, 1),
                time_base=Fraction(1, _OUTPUT_TICKS_PER_SECOND),
                end_seconds=output_duration,
                encoder_preset="ultrafast",
                encoder_crf="17",
                progress=report_progress if progress is not None else None,
                should_cancel=should_cancel,
                metadata={
                    "creation_time": str(provenance["written"]),
                    "comment": json.dumps(provenance),
                },
            )

        publish(destination, write, kind="stimulus-grid", sources=(row.path for row in videos))
        if progress is not None:
            progress(1.0)


def _frame_schedule(
    readers: dict[int, RowReader],
    events: Sequence[float],
    before: float,
    after: float,
    fps: int,
    playback_speed: float,
) -> Iterator[float]:
    """Merge cursor ticks and every row's picture changes without exceeding the output rate."""
    ticks_per_second = _OUTPUT_TICKS_PER_SECOND
    end_tick = int(round((before + after) * ticks_per_second / playback_speed))
    step_ticks = max(1, round(ticks_per_second / fps))
    # Rounded source PTS can land slightly beside a nominal cadence tick.
    # Treat them as one update instead of creating a near-zero duplicate frame.
    cadence_tolerance = max(10, round(step_ticks * 0.01))

    def tile_ticks(
        reader: PyAVReader, mapping: TimeMap, bounds: tuple[float, float], event: float
    ) -> Iterator[int]:
        start = mapping.to_source(event - before)
        end = mapping.to_source(event + after)
        times = reader.frame_times
        first = int(np.searchsorted(times, start, side="left"))
        stop = int(np.searchsorted(times, end, side="left"))
        for source_time in times[first:stop]:
            elapsed = (mapping.to_master(float(source_time)) - event + before) / playback_speed
            # The rendered instant must never precede this source frame's PTS.
            yield int(np.ceil(elapsed * ticks_per_second - 1e-9))
        coverage_end = (bounds[1] - event + before) / playback_speed
        yield int(np.ceil(coverage_end * ticks_per_second - 1e-9))

    def row_ticks(row: RowReader, event: float) -> Iterator[int]:
        if isinstance(row, ImagingRow):
            changes = row.ticks(event, before, after, playback_speed, ticks_per_second)
        else:
            changes = tile_ticks(*row, event)
        return (tick for tick in changes if 0 < tick < end_tick)

    timelines = (row_ticks(row, event) for row in readers.values() for event in events)
    previous = 0
    yield 0.0
    for tick in merge(*timelines):
        if tick <= previous:
            continue
        while tick - previous > step_ticks + cadence_tolerance:
            previous += step_ticks
            yield previous / ticks_per_second
        if tick - previous < step_ticks - cadence_tolerance:
            continue
        previous = tick
        yield tick / ticks_per_second
    while end_tick - previous > step_ticks + cadence_tolerance:
        previous += step_ticks
        yield previous / ticks_per_second


def _reader_bounds(reader: PyAVReader, time_map: TimeMap) -> tuple[float, float]:
    """Include the last frame's presentation interval in source coverage."""
    times = reader.frame_times
    intervals = np.diff(times[-17:])
    positive = intervals[intervals > 0]
    if len(positive):
        final_interval = float(np.median(positive))
    else:
        nominal_rate = reader.stream.average_rate or reader.stream.base_rate
        final_interval = 1.0 / float(nominal_rate) if nominal_rate else 1.0 / 30.0
    return (
        time_map.to_master(float(times[0])),
        time_map.to_master(float(times[-1]) + final_interval),
    )
