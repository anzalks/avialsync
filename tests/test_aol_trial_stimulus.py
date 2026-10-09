"""The stimulus TTL a trial commanded, rebuilt from the controller's saved settings (D-211)."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.stimulus_grid_bands import GridBand, GridStream
from avialsync.loaders.aol_microscope_session import AOLMicroscopeTrialSource
from avialsync.loaders.aol_trial_encoder import (
    SPEED_CHANNEL,
    STIMULUS_CHANNEL,
    AOLTrialEncoderSource,
)
from avialsync.loaders.aol_trial_stimulus import StimulusSchedule, read_stimulus, ttl_trace
from tests.test_aol_microscope_trial import _trial


def _settings(group: h5py.Group, enabled: float, delay: float, width: float, n=0.0, period=0.0):
    for name, value in (
        ("EnableInFuncProtocol", enabled),
        ("EnableInLiveProtocol", 0.0),
        ("Delay", delay),
        ("PulseWidth", width),
        ("N_Stims", n),
        ("Period", period),
    ):
        group.create_dataset(name, data=[[value]])


def _stimulus(folder: Path, *, delay=4.0, width=1.0, enabled=1.0, n=0.0, period=0.0) -> Path:
    """The controller object's copy, plus the DAQ struct's inert default copy beside it."""
    with h5py.File(folder / "params.mat", "a") as handle:
        refs = handle.require_group("#refs#")
        _settings(refs.create_group("Qh"), enabled, delay, width, n, period)
        _settings(refs.create_group("G8").create_group("StimulusTrigger"), 0.0, 0.0, 0.001)
    return folder


def _channel(item, channel: str) -> tuple[np.ndarray, np.ndarray]:
    source = AOLTrialEncoderSource()
    source.open(item.path, dict(item.config))
    chunks = list(source.read_chunks(channel))
    return np.concatenate([c[0] for c in chunks]), np.concatenate([c[1] for c in chunks])


def test_the_controller_objects_settings_are_read_not_the_daq_default(tmp_path: Path) -> None:
    folder = _stimulus(_trial(tmp_path / "12-00-00"), delay=0.004, width=0.01)
    assert read_stimulus(folder) == StimulusSchedule(0.004, 0.01, 0, 0.0)
    plain = _trial(tmp_path / "12-01-00")
    assert read_stimulus(plain) is None
    off = _stimulus(_trial(tmp_path / "12-02-00"), enabled=0.0)
    assert read_stimulus(off) is None


def test_disagreeing_settings_give_no_stimulus_rather_than_a_guess(tmp_path: Path) -> None:
    folder = _stimulus(_trial(tmp_path / "12-00-00"))
    with h5py.File(folder / "params.mat", "a") as handle:
        _settings(handle["#refs#"].create_group("Jh"), 1.0, 2.0, 1.0)
    assert read_stimulus(folder) is None


def test_pulses_follow_count_and_period() -> None:
    assert StimulusSchedule(4.0, 1.0, 0, 0.0).pulses() == [(4.0, 5.0)]
    assert StimulusSchedule(4.0, 1.0, 3, 0.0).pulses() == [(4.0, 5.0)], "no period, one pulse"
    assert StimulusSchedule(1.0, 0.5, 3, 2.0).pulses() == [(1.0, 1.5), (3.0, 3.5), (5.0, 5.5)]


def test_the_trace_has_exact_edges_and_is_zero_without_a_stimulus() -> None:
    times, level = ttl_trace(StimulusSchedule(0.0045, 0.002), 0.01)
    assert np.all(np.diff(times) > 0)
    assert level[times == 0.0045] == 1.0 and level[times == 0.0065] == 0.0
    assert level[(times >= 0.0045) & (times < 0.0065)].all()
    assert not level[(times < 0.0045) | (times >= 0.0065)].any()
    flat_times, flat = ttl_trace(None, 0.01)
    assert len(flat_times) == 10 and not flat.any()


def test_an_edge_beside_a_regular_sample_stays_one_instant_after_joining() -> None:
    """0.7 and 0.7000000000000001 are the same time once 2.636... s is added."""
    times, level = ttl_trace(StimulusSchedule(0.5, 0.2), 2.0)
    placed = 2.636363636363636 + times
    assert np.all(np.diff(placed) > 0)
    assert level[np.isclose(times, 0.7)].tolist() == [0.0]


def test_a_trial_offers_its_stimulus_ttl_as_a_plot_channel(tmp_path: Path) -> None:
    folder = _stimulus(_trial(tmp_path / "12-00-00", duration=0.022), delay=0.004, width=0.01)
    layout = AOLMicroscopeTrialSource().scan(folder, None)
    item = next(item for item in layout.items if item.loader is AOLTrialEncoderSource)
    assert item.label.endswith("stimulus TTL")  # this fixture has no wheel
    source = AOLTrialEncoderSource()
    source.open(item.path, dict(item.config))
    assert [channel.name for channel in source.channels()] == [STIMULUS_CHANNEL]
    times, level = _channel(item, STIMULUS_CHANNEL)
    assert times[0] == 0.0 and times[-1] < 0.022
    assert times[np.argmax(level > 0)] == pytest.approx(0.004)
    assert times[len(level) - np.argmax(level[::-1] > 0)] == pytest.approx(0.014)


def test_joined_trials_place_each_pulse_at_its_trials_joined_start(tmp_path: Path) -> None:
    experiment = tmp_path / "experiment_1"
    experiment.mkdir()
    _trial(experiment / "12-00-00")  # no stimulus: flat
    _stimulus(_trial(experiment / "12-10-00", start_ms=1_700_000_600_000), delay=0.004, width=0.01)
    layout = AOLMicroscopeTrialSource().scan(experiment, None)
    item = next(item for item in layout.items if item.loader is AOLTrialEncoderSource)
    start = item.config["trial_starts"][1]
    times, level = _channel(item, STIMULUS_CHANNEL)
    assert not level[times < start].any()
    assert times[np.argmax(level > 0)] == pytest.approx(start + 0.004)
    assert np.all(np.diff(times) > 0)


def test_wheel_speed_and_ttl_come_from_one_source(tmp_path: Path) -> None:
    from tests.test_aol_trial_encoder import _wheel

    folder = _stimulus(_trial(tmp_path / "12-00-00"), delay=0.004, width=0.01)
    _wheel(folder, np.array([0.0, 0.01, 0.02]), np.array([1.0, 2.0, 3.0]))
    item = next(
        item
        for item in AOLMicroscopeTrialSource().scan(folder, None).items
        if item.loader is AOLTrialEncoderSource
    )
    assert item.label.endswith("wheel speed and stimulus TTL")
    source = AOLTrialEncoderSource()
    source.open(item.path, dict(item.config))
    assert [c.name for c in source.channels()] == [SPEED_CHANNEL, STIMULUS_CHANNEL]


def test_streams_of_different_units_never_share_an_axis(tmp_path: Path) -> None:
    def stream(name: str, unit: str) -> GridStream:
        return GridStream(ReaderReference(tmp_path, name), name, unit=unit)

    assert GridBand("trial", (stream("speed", "rpm"), stream("ttl", ""))).stacked
    assert not GridBand("acc", (stream("x", "g"), stream("y", "g"))).stacked
    assert not GridBand(
        "trial", (stream("speed", "rpm"), stream("ttl", "")), layout="overlay"
    ).stacked


def test_the_stimulus_ttl_is_plotted(qapp, qtbot, tmp_path: Path) -> None:
    from shiboken6 import isValid

    from avialsync.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    folder = _stimulus(_trial(tmp_path / "12-00-00", duration=0.022), delay=0.004, width=0.01)
    item = next(
        item
        for item in AOLMicroscopeTrialSource().scan(folder, None).items
        if item.loader is AOLTrialEncoderSource
    )
    window._route_import_candidate(item.path, item.loader, dict(item.config))
    qtbot.waitUntil(
        lambda: STIMULUS_CHANNEL in {row.reader.channel_id for row in window.plot_pane.channels},
        timeout=10_000,
    )
    rows = {row.reader.channel_id: row for row in window.plot_pane.channels}
    assert rows[STIMULUS_CHANNEL].visible
    if isValid(window):
        window.close()
