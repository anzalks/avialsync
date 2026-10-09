"""The stimulus grid driven by an AOL trial's rebuilt stimulus TTL, as by any sensor (D-211).

The whole path the dialog takes: the trials load into a window, the TTL and
wheel speed become plot channels, either is scanned for rising events, and the
grid exports a camera row, the imaging row and the trial-signals band.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import av
import numpy as np
import pytest
from shiboken6 import isValid

from avialsync.engine.stimulus_grid_export import export_stimulus_grid
from avialsync.engine.stimulus_grid_layout import plan_grid
from avialsync.engine.stimulus_grid_worker import StimulusEventScanWorker
from avialsync.loaders.aol_microscope_session import AOLMicroscopeTrialSource
from avialsync.loaders.aol_trial_encoder import SPEED_CHANNEL, STIMULUS_CHANNEL
from avialsync.ui import stimulus_grid_sources as sources
from avialsync.ui.controllers import drop_controller
from avialsync.ui.main_window import MainWindow
from avialsync.ui.stimulus_grid_dialog import StimulusGridDialog
from avialsync.ui.stimulus_grid_rows import GridRowsPanel
from tests.test_aol_microscope_trial import _trial
from tests.test_aol_trial_encoder import _wheel
from tests.test_aol_trial_stimulus import _stimulus

_TIMEOUT = 15_000


@pytest.fixture
def window(qapp, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    if isValid(win):
        win.close()


def _loaded(window: MainWindow, qtbot, tmp_path: Path) -> list[float]:
    """Three 2 s trials, each with a 0.2 s stimulus 0.5 s in and a wheel turning at 0.8 s."""
    experiment = tmp_path / "2026-09-03" / "experiment_1"
    experiment.mkdir(parents=True)
    for index in range(3):
        folder = _trial(
            experiment / f"12-0{index}-00",
            start_ms=1_700_000_000_000 + index * 60_000,
            duration=2.0,
        )
        _stimulus(folder, delay=0.5, width=0.2)
        times = np.arange(0.0, 2.0, 0.01)
        _wheel(folder, times, np.where(times >= 0.8, 5.0, 0.0))
    layout = AOLMicroscopeTrialSource().scan(experiment, None)
    drop_controller.apply_session_layout(window, layout)
    for item in layout.items:
        window._route_import_candidate(item.path, item.loader, dict(item.config))
    names = lambda: {row.reader.channel_id for row in window.plot_pane.channels}  # noqa: E731
    qtbot.waitUntil(lambda: {SPEED_CHANNEL, STIMULUS_CHANNEL} <= names(), timeout=_TIMEOUT)
    qtbot.waitUntil(lambda: bool(window.imaging_pane.source_paths()), timeout=_TIMEOUT)
    # A camera from master zero, which is the first trial's start.
    video = tmp_path / "camera_1.mp4"
    shutil.copyfile(Path("tests/fixtures/videos/camera_1.mp4"), video)
    window._load_video(video)
    qtbot.waitUntil(lambda: bool(window.video_grid.panes), timeout=_TIMEOUT)
    ribbon = layout.items[0]
    return [float(start) for start in ribbon.config["trial_starts"]]


def _scan(option, threshold: float) -> tuple[float, ...]:
    found: list[object] = []
    worker = StimulusEventScanWorker(option.reference, threshold, 0.05)
    worker.finished.connect(found.append)
    worker.error.connect(lambda message: pytest.fail(message))
    worker.run()
    assert len(found) == 1
    return tuple(found[0])  # type: ignore[arg-type]


def _export(window: MainWindow, tmp_path: Path, trigger, threshold: float, events) -> Path:
    groups, _channels = sources.sensor_groups(window)
    panel = GridRowsPanel(sources.camera_rows(window) + sources.imaging_rows(window), groups)
    panel.check_group(trigger.group)
    bands = panel.bands(trigger.reference, threshold)
    assert len(bands) == 1 and bands[0].stacked, "rpm beside a 0/1 TTL never share an axis"
    labels = [stream.label for stream in bands[0].streams]
    assert bands[0].threshold == threshold
    assert labels[bands[0].threshold_stream] == trigger.label
    destination = tmp_path / f"grid_{trigger.label}.mp4"
    rows = panel.picture_rows()
    export_stimulus_grid(
        rows,
        events,
        before=0.3,
        after=0.5,
        destination=destination,
        labels=sources.grid_labels(),
        fps=5,
        bands=bands,
    )
    with av.open(str(destination)) as container:
        frames = [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]
    aspects = []
    for row in rows:
        aspects.append(getattr(row, "aspect_ratio", None) or 640 / 360)
    layout = plan_grid(len(rows), len(events), 0.3, 0.5, cell_aspect_ratios=aspects, bands=bands)
    assert frames and frames[0].shape[:2] == (layout.height, layout.width)
    band = frames[0][layout.height - layout.bottom_band :, 110 : layout.width - 28]
    drawn = np.count_nonzero(band.max(axis=2) > 120)
    assert drawn > 200, "the band's traces, trigger line and labels are drawn"
    return destination


def test_the_stimulus_ttl_drives_the_grid_like_any_sensor(window, qtbot, tmp_path) -> None:
    starts = _loaded(window, qtbot, tmp_path)
    _groups, channels = sources.sensor_groups(window)
    ttl = next(option for option in channels if option.label == STIMULUS_CHANNEL)

    events = _scan(ttl, 0.5)
    assert events == pytest.approx([start + 0.5 for start in starts], abs=1e-3)
    _export(window, tmp_path, ttl, 0.5, events)


def test_wheel_speed_still_drives_the_grid_beside_it(window, qtbot, tmp_path) -> None:
    starts = _loaded(window, qtbot, tmp_path)
    _groups, channels = sources.sensor_groups(window)
    speed = next(option for option in channels if option.label == SPEED_CHANNEL)

    events = _scan(speed, 2.5)
    assert events == pytest.approx([start + 0.8 for start in starts], abs=0.02)
    _export(window, tmp_path, speed, 2.5, events)


def test_the_dialog_offers_the_ttl_and_ticks_its_group(window, qtbot, tmp_path) -> None:
    _loaded(window, qtbot, tmp_path)
    groups, channels = sources.sensor_groups(window)
    panel = GridRowsPanel(sources.camera_rows(window) + sources.imaging_rows(window), groups)
    dialog = StimulusGridDialog(channels, window, panel)
    qtbot.addWidget(dialog)
    offered = [dialog.channel_combo.itemText(i) for i in range(dialog.channel_combo.count())]
    assert STIMULUS_CHANNEL in offered and SPEED_CHANNEL in offered
    dialog.channel_combo.setCurrentIndex(offered.index(STIMULUS_CHANNEL))
    assert [band.label for band in panel.bands()] == [groups[0].label]
    assert {s.label for s in panel.bands()[0].streams} == {SPEED_CHANNEL, STIMULUS_CHANNEL}
    dialog.set_events((0.5, 2.5))
    assert dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled()
