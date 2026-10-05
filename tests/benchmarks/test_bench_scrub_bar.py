"""The transport cursor tick reuses cached scrub evidence (D-170)."""

from __future__ import annotations

import pytest

from avialsync.ui.transport import Transport

_CURSOR_BUDGET_S = 0.002


def test_bench_scrub_tick_reuses_track(benchmark, qtbot) -> None:
    """A moving slider handle stays within the 2 ms UI cursor budget."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1280, 220)
    transport.show()
    qtbot.waitExposed(transport)
    transport.set_bounds(0.0, 60.0)
    transport.set_source_coverage("camera", 0.0, 60.0, "video")
    transport.set_annotation_markers([(float(index), None, "#d08040") for index in range(60)])
    transport.slider.grab()
    built = transport.slider.track_build_count
    counter = 0

    def tick() -> None:
        nonlocal counter
        counter += 1
        transport.set_time((counter % 599) / 10.0)
        transport.slider.grab()

    benchmark(tick)
    assert transport.slider.track_build_count == built
    stats = benchmark.stats
    if stats is None:
        pytest.skip("benchmark statistics unavailable")
    assert stats["mean"] <= _CURSOR_BUDGET_S
