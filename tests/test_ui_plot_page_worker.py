"""Plot pages are prepared off the UI thread and installed whole (D-201).

Measured rather than assumed: a heartbeat timer on the UI thread records the
longest gap between its ticks while many channels load cold and then reload
warm, which bounds every callback that ran in between. Page-flip consistency is
checked from the data itself -- every row carries a ramp, so the samples a row
shows say which page they came from.
"""

from __future__ import annotations

import functools
import time
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QTimer, Slot

from avialsync.core.pyramid import PyramidBuilder
from avialsync.ui.plot_pane import PlotPane

CHANNELS = 48
DURATION_S = 120.0
SAMPLES = 120_000
#: Generous for a loaded CI runner. The 30 ms UI-callback ceiling itself is
#: certified by `tests/benchmarks/test_bench_plot_pane.py`, which CI does not run.
PAGE_CALLBACK_S = 0.1


@pytest.fixture(scope="module")
def ramp_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Channel *i* reads ``t + 1000 i``: a sample's value names its own time."""
    cache = tmp_path_factory.mktemp("pages") / "cache"
    cache.mkdir()
    times = np.linspace(0.0, DURATION_S, SAMPLES)
    for index in range(CHANNELS):
        PyramidBuilder(cache, f"ch{index}").build_and_save(times, times + 1000.0 * index)
    return cache


class _Heartbeat:
    """The longest the UI thread went without running a 1 ms timer."""

    def __init__(self) -> None:
        self._last = time.perf_counter()
        self.longest = 0.0
        self._timer = QTimer()
        self._timer.setInterval(1)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        now = time.perf_counter()
        self.longest = max(self.longest, now - self._last)
        self._last = now

    def __enter__(self) -> _Heartbeat:
        self._last = time.perf_counter()
        self._timer.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._timer.stop()


def _settled(pane: PlotPane) -> bool:
    return pane._page_worker is None and pane._last_installed_generation == pane._page_generation


def _assert_rows_show_page(pane: PlotPane) -> None:
    """Every visible row holds the current page's samples, at their own times."""
    t0 = pane.sweep_start
    assert t0 is not None
    for index, channel in enumerate(pane.channels):
        if not channel.visible:
            continue
        x, y = channel.curve.getData()
        assert channel.page_t0 == t0
        assert channel.curve.pos().x() == 0.0
        finite = np.isfinite(y)
        # Value minus channel offset is the sample's time; it must match where
        # the row draws it to within one decimation column.
        column = pane.window_duration / max(1, len(x) // 2)
        np.testing.assert_allclose(
            y[finite] - 1000.0 * index, x[finite] + t0, atol=2 * column + 1e-6
        )


def _time_page_callbacks(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[float]]:
    """Time the two UI-thread callbacks a page costs: requesting and installing it."""
    timings: dict[str, list[float]] = {"request": [], "install": []}
    request, install = PlotPane.update_plots, PlotPane._on_page_ready

    def timed_request(self: PlotPane) -> None:
        started = time.perf_counter()
        request(self)
        timings["request"].append(time.perf_counter() - started)

    # Still a slot named as the original, so the worker's signal is queued to
    # the UI thread exactly as it is in production.
    @Slot(object)
    @functools.wraps(install)
    def timed_install(self: PlotPane, page: object) -> None:
        started = time.perf_counter()
        install(self, page)
        timings["install"].append(time.perf_counter() - started)

    monkeypatch.setattr(PlotPane, "update_plots", timed_request)
    monkeypatch.setattr(PlotPane, "_on_page_ready", timed_install)
    return timings


def test_cold_and_warm_pages_never_hold_the_ui_thread(
    qtbot, ramp_cache: Path, monkeypatch: pytest.MonkeyPatch, record_property
) -> None:
    timings = _time_page_callbacks(monkeypatch)
    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(1280, 800)
    pane.show()

    loaded: list[bool] = []
    pane.channels_loaded.connect(lambda: loaded.append(True))
    with _Heartbeat() as cold:
        started = time.perf_counter()
        pane.load_channels(ramp_cache, [f"ch{index}" for index in range(CHANNELS)])
        pane.set_timeline_bounds(0.0, DURATION_S)
        pane.set_window_duration(10.0)
        qtbot.waitUntil(lambda: bool(loaded) and _settled(pane), timeout=20_000)
        cold_s = time.perf_counter() - started
    _assert_rows_show_page(pane)
    cold_install = max(timings["install"])

    timings["install"].clear()
    with _Heartbeat() as warm:
        started = time.perf_counter()
        pane.set_window_duration(20.0)
        qtbot.waitUntil(lambda: _settled(pane), timeout=20_000)
        warm_s = time.perf_counter() - started
    _assert_rows_show_page(pane)
    warm_install = max(timings["install"])

    measured = {
        "cold_load_s": cold_s,
        "cold_page_install_s": cold_install,
        "cold_longest_ui_gap_s": cold.longest,
        "warm_page_s": warm_s,
        "warm_page_install_s": warm_install,
        "warm_longest_ui_gap_s": warm.longest,
        "longest_page_request_s": max(timings["request"]),
    }
    for name, value in measured.items():
        record_property(name, round(value, 4))
    for name in ("cold_page_install_s", "warm_page_install_s", "longest_page_request_s"):
        assert measured[name] < PAGE_CALLBACK_S, f"{name} = {measured[name] * 1000:.1f} ms"
    # The longest gaps are recorded, not asserted: they include Qt's first show
    # (font aliasing, building 48 rows) and pyqtgraph propagating a span change
    # across linked views, none of which reads data. The data's own share is
    # asserted above, and isolated by the stalled-read test below.


def test_a_page_request_queries_nothing_on_the_ui_thread(
    qtbot, ramp_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from avialsync.core.channel_reader import MappedChannelReader

    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(1280, 800)
    pane.load_channels(ramp_cache, [f"ch{index}" for index in range(CHANNELS)])
    pane.wait_for_pending_rows()
    pane.set_timeline_bounds(0.0, DURATION_S)
    qtbot.waitUntil(lambda: _settled(pane), timeout=20_000)

    import threading

    ui_thread = threading.get_ident()
    original = MappedChannelReader.query
    on_ui: list[str] = []

    def watched(self: MappedChannelReader, *args: object, **kwargs: object):
        if threading.get_ident() == ui_thread:
            on_ui.append(self.channel_id)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MappedChannelReader, "query", watched)
    pane.set_window_duration(7.0)
    pane.set_cursor(50.0, immediate=True)
    pane.set_channel_visible("ch3", False)
    pane.set_channel_visible("ch3", True)
    qtbot.waitUntil(lambda: _settled(pane), timeout=20_000)

    assert on_ui == []
    _assert_rows_show_page(pane)


def test_rows_flip_together_and_stale_samples_keep_their_times(qtbot, ramp_cache: Path) -> None:
    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(1280, 800)
    pane.load_channels(ramp_cache, [f"ch{index}" for index in range(CHANNELS)])
    pane.wait_for_pending_rows()
    pane.set_timeline_bounds(0.0, DURATION_S)
    pane.set_window_duration(10.0)
    qtbot.waitUntil(lambda: _settled(pane), timeout=20_000)
    installed: list[int] = []
    pane.page_ready.connect(installed.append)

    # A burst of page flips, faster than any page can be prepared.
    for t in (15.0, 25.0, 35.0, 45.0, 55.0, 65.0):
        pane.set_cursor(t, immediate=True)
        # Before the new page lands, every row still holds the previous page's
        # samples, offset so they sit at the times they were recorded.
        for index, channel in enumerate(pane.channels):
            x, y = channel.curve.getData()
            finite = np.isfinite(y)
            shown_at = x[finite] + channel.curve.pos().x() + pane.sweep_start
            np.testing.assert_allclose(y[finite] - 1000.0 * index, shown_at, atol=0.05)
    qtbot.waitUntil(lambda: _settled(pane), timeout=20_000)

    assert len(installed) < 6, "superseded pages were installed instead of dropped"
    assert installed[-1] == pane._page_generation
    _assert_rows_show_page(pane)


def test_a_page_whose_reads_stall_never_stalls_the_ui(
    qtbot, ramp_cache: Path, monkeypatch: pytest.MonkeyPatch, record_property
) -> None:
    """Cold storage, simulated: every row read waits 15 ms, as a cold mmap page might.

    Read synchronously, this page would hold the UI thread for over 0.7 s. Read
    by the worker, the UI keeps ticking throughout.
    """
    from avialsync.core.channel_reader import MappedChannelReader

    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(1280, 800)
    pane.load_channels(ramp_cache, [f"ch{index}" for index in range(CHANNELS)])
    pane.wait_for_pending_rows()
    pane.set_timeline_bounds(0.0, DURATION_S)
    qtbot.waitUntil(lambda: _settled(pane), timeout=20_000)

    original = MappedChannelReader.query

    def slow(self: MappedChannelReader, *args: object, **kwargs: object):
        time.sleep(0.015)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MappedChannelReader, "query", slow)
    with _Heartbeat() as heartbeat:
        started = time.perf_counter()
        pane.set_cursor(80.0, immediate=True)
        qtbot.waitUntil(lambda: _settled(pane), timeout=20_000)
        page_s = time.perf_counter() - started

    record_property("stalled_page_s", round(page_s, 4))
    record_property("stalled_page_longest_ui_gap_s", round(heartbeat.longest, 4))
    assert page_s > CHANNELS * 0.015
    assert heartbeat.longest < PAGE_CALLBACK_S, f"UI held {heartbeat.longest * 1000:.0f} ms"
    _assert_rows_show_page(pane)
