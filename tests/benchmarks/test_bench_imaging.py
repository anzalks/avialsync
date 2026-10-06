"""Budgets for the imaging viewer's hot paths (D-186, BLUEPRINT performance table).

Three costs, each against its own budget: one random plane from disk, one
playback tick on the UI thread, and one render on the reader thread -- a
two-channel overlay of a 15-frame moving average, which is the heaviest picture
the viewer's default limits allow at 512x512 short of the 31-frame maximum.
"""

from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from avialsync.core.imaging_display import ChannelView, ImagingView
from avialsync.core.source import ImagingMetadata
from avialsync.core.timeline import TimeMap
from avialsync.engine.imaging_reader import ImagingReadWorker
from avialsync.loaders.imaging_loader import HDF5ImagingLoader
from avialsync.ui.imaging_pane import ImagingPane, _Stack

_RANDOM_PLANE_BUDGET_S = 0.050
_CURSOR_BUDGET_S = 0.002
#: A render must finish inside one 30 Hz acquisition frame, so playback of a
#: typical two-photon stack never waits on the overlay.
_RENDER_BUDGET_S = 0.033


@pytest.mark.benchmark(group="imaging-random-frame")
def test_bench_random_hdf5_plane_is_within_seek_budget(benchmark, tmp_path):
    """Requesting one chunked frame must not scan or decode the entire stack."""
    path = tmp_path / "chunked.h5"
    frames = np.arange(8 * 512 * 512, dtype=np.uint16).reshape(8, 512, 512)
    with h5py.File(path, "w") as handle:
        handle.create_dataset("images", data=frames, chunks=(1, 512, 512))
    reader = HDF5ImagingLoader()
    reader.open(path, {"fps": 30})
    counter = 0

    def jump():
        nonlocal counter
        counter += 3
        return reader.read_frame(counter % 8)

    frame = benchmark(jump)
    np.testing.assert_array_equal(frame, frames[counter % 8])
    assert benchmark.stats.stats.median < _RANDOM_PLANE_BUDGET_S
    reader.close()


@pytest.mark.benchmark(group="imaging-cursor")
def test_bench_million_frame_cursor_stays_submillisecond(benchmark, qtbot):
    """A 60 Hz tick must not scan the timestamp table or read pixels."""
    times = np.arange(1_000_000, dtype=np.float64) / 100.0
    info = ImagingMetadata(1_000_000, 512, 512, "uint16", times, "fixture")
    pane = ImagingPane()
    qtbot.addWidget(pane)
    pane._sources["fixture"] = _Stack(
        HDF5ImagingLoader, {}, info, TimeMap(), ImagingView.for_channels(1)
    )
    pane.source_choice.blockSignals(True)
    pane.source_choice.addItem("fixture", "fixture")
    pane.source_choice.blockSignals(False)
    pane._worker = SimpleNamespace(request=lambda _index, _view: None)
    counter = 0

    def tick():
        nonlocal counter
        counter = (counter + 997) % 1_000_000
        pane.set_cursor(float(times[counter]))

    benchmark(tick)
    assert benchmark.stats.stats.median < _CURSOR_BUDGET_S


@pytest.mark.benchmark(group="imaging-render")
def test_bench_two_channel_average_overlay_renders_within_a_frame(benchmark, tmp_path):
    """Playback slides the average by one frame: one new read per channel, then render."""
    path = tmp_path / "two_channel.h5"
    rng = np.random.default_rng(7)
    frames = rng.integers(0, 4096, size=(64, 2, 512, 512), dtype=np.uint16)
    with h5py.File(path, "w") as handle:
        handle.create_dataset("images", data=frames, chunks=(1, 1, 512, 512)).attrs["axes"] = "TCYX"
    worker = ImagingReadWorker(path, HDF5ImagingLoader, {"fps": 30}, frame_count=64)
    worker.open()
    view = ImagingView(
        channels=(
            ChannelView(color="green", auto_low=100.0, auto_high=4000.0),
            ChannelView(color="magenta", auto_low=100.0, auto_high=4000.0),
        ),
        average=15,
    )
    worker.render(8, view)  # fill the window once, as the first shown frame does
    index = 8

    def step():
        nonlocal index
        index = 8 + (index - 7) % 48
        return worker.render(index, view)

    image = benchmark(step)
    assert image is not None and image.shape == (512, 512, 3)
    assert benchmark.stats.stats.median < _RENDER_BUDGET_S
    worker.close()
