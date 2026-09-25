"""Performance guards for the wheel (D-113): the fit on a click, the bars on a frame.

Both run on the UI thread. The fit runs once per click while a wheel is being
placed; generating and projecting the bars runs once per frame shown, for every
camera. Budgets are the BLUEPRINT's per-callback ones: the fit must stay under
the 30 ms ceiling with more bars than anyone will click, and a frame's bars for
three cameras must fit comfortably inside the 2 ms cursor budget.
"""

from __future__ import annotations

import pytest

from avialsync.core.wheel import EncoderBinding, WheelCheck, WheelSpec, project_bars
from avialsync.core.wheel_check import settle_sign
from avialsync.core.wheel_fit import fit_wheel
from tests.wheel_fixture import CAMERAS, TRUTH, clicks_for

_FIT_BUDGET_S = 0.030
_FRAME_BUDGET_S = 0.002
_CHECK_BUDGET_S = 0.030


def _mean(benchmark) -> float:
    stats = benchmark.stats
    if stats is None:
        pytest.skip("benchmark statistics unavailable (benchmarks disabled)")
    return float(stats["mean"])


def test_bench_wheel_fit_six_bars_typed_radius(benchmark) -> None:
    """The heaviest fit a placement asks for: six bars, and a typed radius's second refine."""
    spec = WheelSpec("wheel", 36, radius=100.0, units="mm")
    clicks = clicks_for([0, 1, 2, 3, 4, 5])
    benchmark(fit_wheel, spec, clicks, CAMERAS)
    mean = _mean(benchmark)
    assert mean <= _FIT_BUDGET_S, f"wheel fit {mean * 1000:.1f} ms exceeds 30 ms"


def test_bench_wheel_bars_for_one_frame(benchmark) -> None:
    """Generate one frame's bars and project them into three cameras."""

    def frame() -> None:
        ends = TRUTH.bar_ends(123.4)
        for camera in CAMERAS.values():
            project_bars(TRUTH, ends, camera)

    benchmark(frame)
    mean = _mean(benchmark)
    assert mean <= _FRAME_BUDGET_S, f"wheel frame {mean * 1000:.2f} ms exceeds 2 ms"


def test_bench_wheel_settle_three_checks(benchmark) -> None:
    """Settling the encoder's direction from three checks, as one Verify click does."""
    camera = CAMERAS["Front"]
    checks = []
    for turn in (-47.0, -133.0, -250.0):
        pixels, in_front, facing = project_bars(TRUTH, TRUTH.bar_ends(turn), camera)
        seen = [i for i in range(len(pixels)) if in_front[i] and facing[i]]
        x, y = pixels[seen[len(seen) // 2], 0]
        checks.append(WheelCheck(0, -turn, "Front", float(x), float(y)))
    binding = EncoderBinding("e", "a", 0.0)
    benchmark(settle_sign, TRUTH, binding, CAMERAS, checks)
    mean = _mean(benchmark)
    assert mean <= _CHECK_BUDGET_S, f"settling {mean * 1000:.1f} ms exceeds 30 ms"
