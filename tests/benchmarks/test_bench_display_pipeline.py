"""Performance guards for the display pipeline (WP-9, D-093).

AGENTS rule 9: a timing feature needs a ground-truth fixture and a benchmark
before it ships. This is the benchmark, and it exists to answer one specific
open question from D-093 -- whether converting at a source's native depth costs
more than the ``rgb24`` path it replaces.

The claim being checked is that windowed greyscale is *not* slower: the lookup
table adds a gather, but emitting one plane instead of three removes swscale's
grey-to-RGB triplication, which is two thirds of the bytes written.

Run with ``pytest --benchmark-only``; CI does not certify speed
(BLUEPRINT.md "Performance budgets"), so these are excluded from the CI run.
"""

from __future__ import annotations

import av
import numpy as np
import pytest

from avialsync.engine.display_pipeline import (
    DisplayLevels,
    SourceFormat,
    build_lut,
    probe_format,
    to_display_array,
)

#: The measured baseline's frame size, so these numbers sit beside the scrub
#: figures in BLUEPRINT rather than describing a different picture.
_WIDTH, _HEIGHT = 1440, 1080

#: Per-frame conversion budget. Generous against the 250 ms exact-seek budget
#: it sits inside; it exists to catch an order-of-magnitude regression, not to
#: certify a millisecond.
_CONVERSION_BUDGET_S = 0.030


def _grey_frame(pix_fmt: str, bits: int):
    peak = (1 << bits) - 1
    dtype = np.uint8 if bits <= 8 else np.uint16
    data = np.linspace(0, peak, _WIDTH * _HEIGHT, dtype=dtype).reshape(_HEIGHT, _WIDTH)
    return av.VideoFrame.from_ndarray(data, format=pix_fmt)


def _colour_frame():
    data = np.zeros((_HEIGHT, _WIDTH, 3), dtype=np.uint8)
    data[..., 1] = 128
    return av.VideoFrame.from_ndarray(data, format="rgb24")


@pytest.mark.benchmark(group="display-pipeline")
def test_bench_colour_path_is_unchanged(benchmark) -> None:
    """8-bit colour must pay nothing for this module existing."""
    frame = _colour_frame()
    result = benchmark(lambda: to_display_array(frame, DisplayLevels()))
    assert result[1] is False
    assert benchmark.stats.stats.median < _CONVERSION_BUDGET_S


@pytest.mark.benchmark(group="display-pipeline")
def test_bench_windowed_twelve_bit(benchmark) -> None:
    """The path the feature exists for."""
    frame = _grey_frame("gray12le", 12)
    levels = DisplayLevels(black=0.2, white=0.8)
    result = benchmark(lambda: to_display_array(frame, levels))
    assert result[1] is True
    assert benchmark.stats.stats.median < _CONVERSION_BUDGET_S


@pytest.mark.benchmark(group="display-pipeline")
def test_bench_rgb24_of_the_same_frame(benchmark) -> None:
    """The comparison arm: what the same 12-bit frame cost before.

    Recorded so the two medians can be read side by side. D-093 predicts the
    windowed path is not slower, because one plane is a third of the bytes of
    three -- if that is ever false, this pair is where it shows.
    """
    frame = _grey_frame("gray12le", 12)
    benchmark(lambda: frame.to_ndarray(format="rgb24"))
    assert benchmark.stats.stats.median < _CONVERSION_BUDGET_S


@pytest.mark.benchmark(group="display-pipeline")
def test_bench_lut_build(benchmark) -> None:
    """Built once per levels change, not per frame; a drag coalesces to 20 Hz."""
    source = SourceFormat("gray16le", 16, 1)
    benchmark(lambda: build_lut(source, DisplayLevels(black=0.1, white=0.9, gamma=2.2)))
    # The largest table this can produce is 65536 entries; if the widest case
    # is not comfortably sub-millisecond, a levels drag would stutter.
    assert benchmark.stats.stats.median < 0.005


@pytest.mark.benchmark(group="display-pipeline")
def test_bench_format_probe(benchmark) -> None:
    """Runs once per source, but must not be expensive enough to notice."""
    frame = _grey_frame("gray12le", 12)
    benchmark(lambda: probe_format(frame))
    assert benchmark.stats.stats.median < 0.001
