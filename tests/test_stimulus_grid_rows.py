"""Imaging rows and multi-stream sensor bands in the stimulus grid movie (D-210)."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest
import tifffile

from avialsync.core.imaging_display import ChannelView, ImagingView
from avialsync.core.pyramid import PyramidBuilder
from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.stimulus_grid_bands import (
    OVERLAY_LIMIT,
    GridBand,
    GridStream,
    area_height,
    event_mean,
    stack_height,
)
from avialsync.engine.stimulus_grid_export import GridVideo, export_stimulus_grid
from avialsync.engine.stimulus_grid_imaging import GridImaging, ImagingRow
from avialsync.engine.stimulus_grid_layout import GridLabels, plan_grid
from avialsync.engine.stimulus_grid_trace import GridTrace
from avialsync.engine.transcode import encode_video
from avialsync.loaders.imaging_loader import TIFFImagingLoader

_LABELS = GridLabels(
    title="Stimulus-aligned comparison",
    event="Event {index}",
    no_footage="No footage",
    ruler="{before:.2f} s    Stimulus    +{after:.2f} s",
    current="Current: {time:+.2f} s",
    no_signal="No signal",
    frame="Frame {index}",
)
#: A cell with nothing to show is filled with this, then labelled.
_EMPTY = (32, 41, 43)


def _stack(tmp_path: Path, frames: int = 10) -> Path:
    """A 10 fps stack whose frame *i* is uniformly ``1000 * i``."""
    path = tmp_path / "stack.tif"
    values = np.arange(frames, dtype=np.uint16)[:, None, None] * 1000
    tifffile.imwrite(
        path, np.broadcast_to(values, (frames, 20, 40)).copy(), photometric="minisblack"
    )
    return path


def _imaging(tmp_path: Path, crop=None) -> GridImaging:
    path = _stack(tmp_path)
    info = TIFFImagingLoader().open(path, {"fps": 10.0})
    # A fixed window, as a viewer that has measured one would hand over.
    view = ImagingView(channels=(ChannelView(color="grey", auto_low=0.0, auto_high=9000.0),))
    return GridImaging(
        path,
        "stack.tif",
        TIFFImagingLoader,
        {"fps": 10.0},
        info.frame_times,
        info.tail_duration,
        view,
        info.width,
        info.height,
        crop=crop,
    )


def _grey(image) -> int:
    return image.pixelColor(image.width() // 2, image.height() // 2).red()


def test_an_imaging_row_holds_each_frame_for_its_interval(tmp_path: Path, qapp) -> None:
    row = ImagingRow(_imaging(tmp_path))
    try:
        assert row.bounds == pytest.approx((0.0, 1.0))
        # 0.25 s lies in frame 2's interval [0.2, 0.3): the frame is held, never the next.
        assert row.index_at(0.25) == 2
        assert _grey(row.image_at(0.25)) == pytest.approx(round(2000 / 9000 * 255), abs=2)
        assert row.index_at(0.999) == 9
        assert row.image_at(1.0) is None, "past the last frame's interval there is no imaging"
        assert row.image_at(-0.01) is None
        ticks = list(row.ticks(0.5, 0.2, 0.3, 1.0, 1_000))
        assert ticks == sorted(ticks)
        assert ticks[:5] == [0, 100, 200, 300, 400]  # frames 3..7 within 0.3 .. 0.8
    finally:
        row.close()


def test_an_imaging_row_keeps_the_viewers_zoom(tmp_path: Path, qapp) -> None:
    whole = _imaging(tmp_path)
    right_half = GridImaging(**{**whole.__dict__, "crop": (0.5, 0.0, 0.5, 1.0)})
    assert right_half.aspect_ratio == pytest.approx(whole.aspect_ratio / 2)
    row = ImagingRow(right_half)
    try:
        image = row.image_at(0.05)
        assert image.width() == 20 and image.height() == 20
    finally:
        row.close()


def test_one_band_keeps_the_single_signal_layout_and_more_bands_grow_it() -> None:
    stream = GridStream(ReaderReference(Path("."), "x"), "x")
    one = (GridBand("wheel", (stream,)),)
    assert stack_height(one) == plan_grid(1, 2, 0.5, 1.0, has_signal=True).bottom_band
    three = one * 3
    layout = plan_grid(1, 2, 0.5, 1.0, bands=three)
    assert layout.bottom_band == stack_height(three) > stack_height(one)
    many = GridBand("probe", (stream,) * 32)
    assert many.stacked and not GridBand("acc", (stream,) * OVERLAY_LIMIT).stacked
    assert area_height(many) > area_height(GridBand("acc", (stream,) * 3))
    assert not GridBand("probe", (stream,) * 32, layout="overlay").stacked


def test_the_mean_is_taken_where_events_have_data_only() -> None:
    times = np.linspace(-0.5, 1.0, 16)
    low = GridTrace(times, np.full(16, 1.0), np.full(16, 1.0), np.zeros(16, dtype=bool))
    high = GridTrace(times, np.full(16, 3.0), np.full(16, 3.0), times > 0.5)
    grid, mean = event_mean([low, high], 0.5, 1.0, 31)
    assert mean[grid < 0.4] == pytest.approx(2.0)
    assert mean[grid > 0.7] == pytest.approx(1.0), "a gap contributes nothing, not a held value"
    _grid, empty = event_mean([], 0.5, 1.0, 5)
    assert np.isnan(empty).all()


def _camera(tmp_path: Path) -> Path:
    path = tmp_path / "camera.mp4"
    frame = np.full((36, 64, 3), (200, 40, 40), dtype=np.uint8)
    encode_video(path, [(frame, index / 10) for index in range(21)], rate=Fraction(10, 1))
    return path


def _sensor(tmp_path: Path, name: str, values) -> ReaderReference:
    times = np.arange(0.0, 3.0, 0.01)
    PyramidBuilder(tmp_path, name).build_and_save(times, values(times))
    return ReaderReference(tmp_path, name)


def test_a_grid_carries_cameras_imaging_and_sensor_bands(tmp_path: Path, qapp) -> None:
    """Imaging is a row of cells; sensors are full-width bands; no-data cells say so."""
    imaging = _imaging(tmp_path)
    accel = GridBand(
        "accelerometer",
        tuple(
            GridStream(_sensor(tmp_path, axis, lambda t, k=k: np.sin(t * (k + 1))), axis, colour)
            for k, (axis, colour) in enumerate(
                (("x", (230, 159, 0)), ("y", (86, 180, 233)), ("z", (0, 158, 115)))
            )
        ),
    )
    probe = GridBand(
        "probe",
        tuple(
            GridStream(_sensor(tmp_path, f"ch{k}", lambda t, k=k: np.cos(t * k)), f"ch{k}")
            for k in range(6)
        ),
    )
    destination = tmp_path / "grid.mp4"
    events = [0.5, 1.5]  # the stack covers 0 .. 1 s: the second event has no imaging
    export_stimulus_grid(
        [GridVideo(_camera(tmp_path), "Camera"), imaging],
        events,
        before=0.2,
        after=0.3,
        destination=destination,
        labels=_LABELS,
        fps=5,
        bands=[accel, probe],
    )
    layout = plan_grid(
        2,
        2,
        0.2,
        0.3,
        cell_aspect_ratios=[64 / 36, imaging.aspect_ratio],
        bands=[accel, probe],
    )
    with av.open(str(destination)) as container:
        first = next(container.decode(video=0)).to_ndarray(format="rgb24")
    assert first.shape[:2] == (layout.height, layout.width)
    shown = layout.cell_rect(1, 0)
    pixel = first[shown.y() + shown.height() // 2, shown.x() + shown.width() // 2]
    # At t = 0.5 - 0.2 the stack is on frame 3: grey 3000 / 9000.
    assert abs(int(pixel[0]) - round(3000 / 9000 * 255)) < 12
    assert abs(int(pixel[0]) - int(pixel[2])) < 6
    missing = layout.cell_rect(1, 1)
    corner = first[missing.y() + 2, missing.x() + 2]
    assert tuple(int(c) for c in corner) == pytest.approx(_EMPTY, abs=6)
    # The bands run the full width beneath the rows, with both groups drawn.
    bands = first[layout.height - layout.bottom_band :, 110 : layout.width - 28]
    orange = (bands[:, :, 0] > 180) & (bands[:, :, 1] > 120) & (bands[:, :, 2] < 80)
    assert np.count_nonzero(orange) > 30
