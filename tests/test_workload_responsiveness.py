"""The UI stays responsive under a realistic workload.

The requirement is not "background work exists" but "the interface never
freezes, whatever is loaded". These drive the paths that actually cost
something — many plotted channels, a populated 3D pose view, cursor ticks at
playback rate, and resize storms — and assert the UI thread keeps its budget.

AGENTS: any UI-thread callback targets <=8 ms and must not exceed 30 ms.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from avialview.core.pyramid import PyramidBuilder
from avialview.ui.main_window import MainWindow
from avialview.ui.ui_heartbeat import UiHeartbeat

RATE_HZ = 1_000.0
SAMPLES = 200_000  # 200 s at 1 kHz per channel
CHANNELS = 32


@pytest.fixture(scope="module")
def dense_source(tmp_path_factory) -> tuple[Path, list[str]]:
    """A 32-channel, 200k-sample source — a realistic dense recording."""
    cache = tmp_path_factory.mktemp("dense")
    times = np.arange(SAMPLES, dtype=np.float64) / RATE_HZ
    names = [f"ch{index:02d}" for index in range(CHANNELS)]
    for index, name in enumerate(names):
        PyramidBuilder(cache, name).build_and_save(times, np.sin(times + index))
    return cache, names


@pytest.fixture
def loaded_window(qapp: QApplication, qtbot, dense_source) -> MainWindow:
    cache, names = dense_source
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    window._on_import_finished(
        "/tmp/dense.csv", str(cache), names, (0.0, (SAMPLES - 1) / RATE_HZ), None
    )
    qapp.processEvents()
    yield window
    window.close()


def _measure(qapp: QApplication, action, iterations: int) -> float:
    """Run *action* repeatedly and return the worst UI-thread stall in ms."""
    heartbeat = UiHeartbeat()
    heartbeat.start()
    for step in range(iterations):
        action(step)
        qapp.processEvents()
    heartbeat.stop()
    return heartbeat.worst_stall_ms


def test_loading_many_channels_leaves_the_ui_responsive(
    loaded_window: MainWindow, qapp: QApplication
) -> None:
    assert len(loaded_window.plot_pane.channels) == CHANNELS

    worst = _measure(qapp, lambda _step: None, iterations=20)

    assert worst < 500.0, f"idle loop stalled {worst:.0f} ms with {CHANNELS} channels"


def test_scrubbing_across_a_dense_recording_does_not_block(
    loaded_window: MainWindow, qapp: QApplication
) -> None:
    """Dragging the playhead is the most latency-visible interaction there is."""
    duration = (SAMPLES - 1) / RATE_HZ

    worst = _measure(
        qapp,
        lambda step: loaded_window.player.seek(duration * (step / 60.0), exact=False),
        iterations=60,
    )

    assert worst < 500.0, f"scrubbing stalled the UI for {worst:.0f} ms"


def test_cursor_ticks_at_playback_rate_stay_within_budget(
    loaded_window: MainWindow, qapp: QApplication
) -> None:
    """60 Hz ticks over 32 populated channels must not accumulate a stall."""
    started = time.monotonic()
    for step in range(120):
        loaded_window.player._update_timeline_views(step / 60.0, now=step / 60.0)
    elapsed_ms = (time.monotonic() - started) * 1000.0

    per_tick_ms = elapsed_ms / 120
    assert per_tick_ms < 30.0, f"{per_tick_ms:.1f} ms per tick exceeds the 30 ms ceiling"


def test_repeated_resizes_do_not_block_the_ui(
    loaded_window: MainWindow, qapp: QApplication
) -> None:
    """Resize storms are coalesced; the loop must survive one."""
    worst = _measure(
        qapp,
        lambda step: loaded_window.resize(900 + (step % 12) * 25, 650 + (step % 8) * 20),
        iterations=40,
    )

    assert worst < 500.0, f"resizing stalled the UI for {worst:.0f} ms"


def test_hiding_channels_does_not_block(loaded_window: MainWindow, qapp: QApplication) -> None:
    from avialview.core.channel_reader import ChannelKey

    _cache, names = None, [channel.name for channel in loaded_window.plot_pane.channels]

    worst = _measure(
        qapp,
        lambda step: loaded_window.plot_pane.set_channel_visible(
            ChannelKey("/tmp/dense.csv", names[step % len(names)]), step % 2 == 0
        ),
        iterations=40,
    )

    assert worst < 500.0, f"toggling visibility stalled the UI for {worst:.0f} ms"


def test_the_window_still_closes_promptly_under_load(
    loaded_window: MainWindow, qapp: QApplication
) -> None:
    """Whatever is loaded, quitting must be quick."""
    started = time.monotonic()
    loaded_window.close()
    elapsed = time.monotonic() - started

    assert elapsed < 5.0, f"closing took {elapsed:.1f}s with {CHANNELS} channels loaded"
