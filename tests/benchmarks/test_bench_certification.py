"""Opt-in local measurements of imports, interactions and rendered frame identity."""

from __future__ import annotations

import gc
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QObject, QRect, QTimer
from PySide6.QtGui import QImage

from avialsync.core.pyramid import PyramidReader
from avialsync.engine.importer import ImportWorker
from avialsync.ui.job_manager import on_ui_thread
from avialsync.ui.main_window import MainWindow
from tests.benchmarks.test_bench_plot_pane import _populated_pane, _settled_page
from tests.util_framestrip import decode_frame_strip

pytestmark = pytest.mark.skipif(
    not os.environ.get("AVIALSYNC_CERTIFICATION_ROOT"),
    reason="Run tools/certify_engineering.py for isolated local certification.",
)


class Heartbeat(QObject):
    """Record every delivered timer gap, including healthy sub-30-ms gaps."""

    def __init__(self, owner: QObject) -> None:
        super().__init__(owner)
        self.timer = QTimer(self)
        self.timer.setInterval(2)
        self.timer.timeout.connect(self.tick)
        self.last = time.perf_counter()
        self.maximum_ms = 0.0
        self.timer.start()

    def tick(self) -> None:
        now = time.perf_counter()
        self.maximum_ms = max(self.maximum_ms, (now - self.last) * 1000)
        self.last = now


def _peak_rss_mb() -> float:
    if sys.platform != "win32":
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_bytes = peak if sys.platform == "darwin" else peak * 1024
        return peak_bytes / 1_000_000
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("faults", wintypes.DWORD),
            *(
                (name, ctypes.c_size_t)
                for name in (
                    "peak",
                    "working",
                    "peak_paged",
                    "paged",
                    "peak_nonpaged",
                    "nonpaged",
                    "pagefile",
                    "peak_pagefile",
                )
            ),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    process = kernel.GetCurrentProcess
    process.restype = wintypes.HANDLE
    query = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not query(process(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.peak / 1_000_000


def _new_window(qtbot) -> MainWindow:
    gc.collect()
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    return window


def _import(qtbot, window: MainWindow, source: Path, progress: list[int] | None = None) -> tuple:
    worker = ImportWorker(source, {"time_col": "time", "time_format": "numeric", "time_unit": "s"})
    results, failures = [], []

    def wire(thread):
        if progress is not None:
            worker.progress.connect(progress.append)
        worker.finished.connect(window._on_import_finished)
        worker.finished.connect(on_ui_thread(lambda *args: results.append(args), window))
        worker.error.connect(on_ui_thread(failures.append, window))

    window._run_job(worker, label="Certification import", configure=wire)
    qtbot.waitUntil(lambda: bool(results or failures), timeout=180_000)
    assert not failures, failures
    qtbot.waitUntil(lambda: len(window.plot_pane.channels) == 4, timeout=30_000)
    _settled_page(qtbot, window.plot_pane)
    assert not window.plot_pane.grab().isNull()
    assert results[0][2] == ["ch0", "ch1", "ch2", "ch3"]
    return results[0]


def test_certification_cold_import_and_warm_reopen(benchmark, qtbot) -> None:
    root = Path(os.environ["AVIALSYNC_CERTIFICATION_ROOT"])
    metadata = json.loads((root / "fixture.json").read_text())
    assert metadata["bytes"] >= 1_000_000_000
    window = _new_window(qtbot)
    heartbeat = Heartbeat(window)
    progress: list[int] = []
    started = time.perf_counter()
    result = _import(qtbot, window, root / "fixture.csv", progress)
    cold_seconds = time.perf_counter() - started
    heartbeat.timer.stop()
    assert cold_seconds <= 60
    assert progress and max(progress) == 100
    directory = Path(result[1])
    with_reader = PyramidReader(directory, "ch2")
    assert with_reader.sample_at(9)[1] == 0
    assert with_reader.sample_at(11)[1] == 32000
    with_reader.close()
    cold_gap = heartbeat.maximum_ms
    window.close()

    def reopen():
        warm = _new_window(qtbot)
        beat = Heartbeat(warm)
        started = time.perf_counter()
        _import(qtbot, warm, root / "fixture.csv")
        for index in range(1, 4):
            warm.video_grid.add_pane(str(Path("tests/fixtures/videos") / f"camera_{index}.mp4"))
        qtbot.waitUntil(
            lambda: (
                len(warm.video_grid.panes) == 3 and all(p.has_media for p in warm.video_grid.panes)
            ),
            timeout=15_000,
        )
        elapsed = time.perf_counter() - started
        warm.plot_pane.grab()
        beat.timer.stop()
        warm.close()
        assert elapsed <= 3
        return elapsed

    benchmark.pedantic(reopen, rounds=5, iterations=1)
    benchmark.extra_info.update(
        {
            "cold_import_seconds": cold_seconds,
            "cold_maximum_heartbeat_gap_ms": cold_gap,
            "peak_rss_mb": _peak_rss_mb(),
            "source_bytes": metadata["bytes"],
            "sample_count": metadata["samples"],
            "progress_updates": len(progress),
        }
    )
    assert _peak_rss_mb() <= 2500


def _painted_index(pane) -> int:
    surface = pane.surface
    scale, x, y = surface.frame_geometry()
    width, height = surface.video_size
    pixmap = surface.grab()
    ratio = pixmap.devicePixelRatio()
    image = (
        pixmap.toImage()
        .copy(
            QRect(
                round(x * ratio),
                round(y * ratio),
                round(width * scale * ratio),
                round(height * scale * ratio),
            )
        )
        .scaled(width, height)
    )
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = (
        np.frombuffer(image.bits(), dtype=np.uint8)
        .reshape(height, image.bytesPerLine())[:, : width * 4]
        .reshape(height, width, 4)
    )
    return decode_frame_strip(pixels[..., :3])


def test_certification_three_camera_painted_seek(benchmark, qtbot) -> None:
    window = _new_window(qtbot)
    for index in range(1, 4):
        window.video_grid.add_pane(str(Path("tests/fixtures/videos") / f"camera_{index}.mp4"))
    qtbot.waitUntil(
        lambda: (
            len(window.video_grid.panes) == 3 and all(p.has_media for p in window.video_grid.panes)
        ),
        timeout=15_000,
    )
    heartbeat = Heartbeat(window)
    counter = 0

    def seek_and_paint():
        nonlocal counter
        frame = 20 + counter % 60
        counter += 1
        window.player.seek((frame + 0.25) / 30, exact=True)
        qtbot.waitUntil(
            lambda: all(
                not pane.is_seeking and abs(pane.time_pos - frame / 30) < 0.5 / 30
                for pane in window.video_grid.panes
            ),
            timeout=5_000,
        )
        assert [_painted_index(pane) for pane in window.video_grid.panes] == [frame] * 3

    benchmark.pedantic(seek_and_paint, rounds=60, iterations=1)
    heartbeat.timer.stop()
    benchmark.extra_info.update(
        {
            "maximum_heartbeat_gap_ms": heartbeat.maximum_ms,
            "peak_rss_mb": _peak_rss_mb(),
            "evidence": "frame strip decoded from rendered widget grabs",
        }
    )
    window.close()
    assert benchmark.stats.stats.mean <= 0.250


@pytest.mark.parametrize("channels", [4, 32, 128])
def test_certification_populated_interactions(benchmark, qtbot, qapp, tmp_path, channels) -> None:
    gc.collect()
    pane = _populated_pane(qtbot, tmp_path, channels)
    pane.set_timeline_bounds(0, 60)
    pane.set_window_duration(10)
    _settled_page(qtbot, pane)
    heartbeat = Heartbeat(pane)
    samples = {"cursor": [], "zoom": [], "resize": [], "paint": []}
    counter = 0

    def interact():
        nonlocal counter
        counter += 1
        start = time.perf_counter()
        pane.set_cursor(float(counter % 60))
        samples["cursor"].append(time.perf_counter() - start)
        start = time.perf_counter()
        pane.set_window_duration((5.0, 10.0, 20.0, 40.0)[counter % 4])
        samples["zoom"].append(time.perf_counter() - start)
        start = time.perf_counter()
        pane.resize((1280, 1400, 1100, 1600)[counter % 4], 800)
        qapp.processEvents()
        samples["resize"].append(time.perf_counter() - start)
        _settled_page(qtbot, pane)
        start = time.perf_counter()
        assert not pane.grab().isNull()
        samples["paint"].append(time.perf_counter() - start)

    benchmark.pedantic(interact, rounds=60, iterations=1)
    heartbeat.timer.stop()
    distributions = {
        name: {
            **{f"p{p}_ms": float(np.percentile(values, p) * 1000) for p in (50, 95, 99)},
            "mean_ms": float(np.mean(values) * 1000),
            "maximum_ms": max(values) * 1000,
        }
        for name, values in samples.items()
    }
    benchmark.extra_info.update(
        {
            "channels": channels,
            "operations": distributions,
            "maximum_heartbeat_gap_ms": heartbeat.maximum_ms,
            "peak_rss_mb": _peak_rss_mb(),
        }
    )
    pane.shutdown()
    assert np.mean(samples["cursor"]) <= 0.002
    assert np.mean(samples["zoom"]) <= 0.030
    assert np.mean(samples["paint"]) <= 0.016
