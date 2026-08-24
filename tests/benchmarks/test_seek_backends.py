"""The scrub-latency certification behind D-075: what a slider costs the reader.

This is the file BLUEPRINT.md's "Measured scrub baseline" table is reproduced
from.  It measures the three things a user actually does to a slider, on three
cameras at once, against the budgets in that table:

===================================  ===========
Interaction                          Budget
===================================  ===========
Jump to a new time                   250 ms
Drag the slider                      50 ms
Re-scrub a span the cache covers     50 ms
===================================  ===========

The fixture is 1440x1080 with a GOP of 250 — the *worst* case, matching
long-GOP transcodes of session footage.  The lab's own all-intra recordings are
several times faster, so a pass here is a floor and not a best case.  Generating
it costs ~16 s once per session; benchmarks are opt-in and local-only, since CI
passes ``--ignore=tests/benchmarks`` on both workflows (AGENTS.md).  Speed is
certified with ``pytest tests/benchmarks/test_seek_backends.py --benchmark-only``.

The libmpv column of that table is a *record*, not something this file can
re-measure: the comparison arm was deleted with the last of libmpv (D-086).  Its
figures were taken once, on the hardware BLUEPRINT.md names, and re-running them
would have meant keeping a second video backend installable forever to re-derive
a number nothing depends on.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from tests.util_pyav_fixtures import cfr_times, write_video

pytest.importorskip("av")

from avialsync.engine.pyav_reader import PyAVReader, to_rgb_array  # noqa: E402

CAMERAS = 3
FRAME_COUNT = 600
GOP = 250
FPS = 30.0
WIDTH, HEIGHT = 1440, 1080

#: Budgets from BLUEPRINT.md, in seconds.
JUMP_BUDGET_S = 0.250
DRAG_BUDGET_S = 0.050
RESCRUB_BUDGET_S = 0.050

#: A span short enough to sit inside the reader's frame window, which is what
#: "a span the cache covers" means.  Re-scrubbing a *wider* span than the window
#: is a jump wearing a drag's clothing, and measuring it as a drag would flatter
#: the result.
COVERED_SPAN_FRAMES = 8


@pytest.fixture(scope="module")
def camera_files(tmp_path_factory: pytest.TempPathFactory) -> list[Path]:
    """Three long-GOP 1440x1080 files, one per camera."""
    directory = tmp_path_factory.mktemp("seek_backends")
    paths = []
    for camera in range(CAMERAS):
        path = directory / f"cam{camera}.mp4"
        write_video(
            path,
            frame_times=cfr_times(FRAME_COUNT),
            width=WIDTH,
            height=HEIGHT,
            gop_size=GOP,
            detail=True,
        )
        paths.append(path)
    return paths


# ---------------------------------------------------------------- PyAV arm


@pytest.fixture(scope="module")
def readers(camera_files: list[Path]) -> Iterator[list[PyAVReader]]:
    open_readers = [PyAVReader(path) for path in camera_files]
    yield open_readers
    for reader in open_readers:
        reader.close()


def _fanout(readers: list[PyAVReader], t: float) -> None:
    """Ask every camera for the frame at ``t``, in parallel.

    PyAV releases the GIL during decode, so these threads genuinely run on
    separate cores.  The RGB conversion is included because a pane cannot paint
    without it.
    """
    with ThreadPoolExecutor(max_workers=len(readers)) as pool:
        list(pool.map(lambda reader: to_rgb_array(reader.frame_at_time(t)), readers))


def _jump_targets() -> Iterator[float]:
    """Yield never-repeating mid-GOP positions.

    A benchmark that jumps to the same place every round measures the frame
    cache, not a seek.  Stepping by a stride coprime with the frame count keeps
    every round landing somewhere the reader has not just been.
    """
    step = 0
    while True:
        step += 1
        yield ((step * 137) % FRAME_COUNT) / FPS


def test_bench_pyav_jump_to_a_new_time(benchmark: Any, readers: list[PyAVReader]) -> None:
    """A jump costs one seek plus a partial GOP of decode, on every camera."""
    targets = _jump_targets()

    def setup() -> tuple[tuple[Any, ...], dict[str, Any]]:
        for reader in readers:
            reader._cache.clear()
        return (readers, next(targets)), {}

    benchmark.pedantic(_fanout, setup=setup, rounds=15, iterations=1)
    _assert_within(benchmark, JUMP_BUDGET_S)


def test_bench_pyav_drag_the_slider(benchmark: Any, readers: list[PyAVReader]) -> None:
    """A drag steps forward frame by frame; nothing should re-seek."""
    base = 300 / FPS
    cursor = {"frame": 0}

    def setup() -> tuple[tuple[Any, ...], dict[str, Any]]:
        cursor["frame"] += 1
        if cursor["frame"] > COVERED_SPAN_FRAMES * 2:
            cursor["frame"] = 1
            _fanout(readers, base)
        return (readers, base + cursor["frame"] / FPS), {}

    benchmark.pedantic(_fanout, setup=setup, rounds=30, iterations=1)
    _assert_within(benchmark, DRAG_BUDGET_S)


def test_bench_pyav_rescrub_a_covered_span(benchmark: Any, readers: list[PyAVReader]) -> None:
    """Ground the user just covered must not be decoded twice.

    This is the interaction libmpv cannot improve on, because it holds no
    memory of where it just was.
    """
    base = 300 / FPS
    for frame in range(COVERED_SPAN_FRAMES):
        _fanout(readers, base + frame / FPS)
    cursor = {"frame": 0}

    def setup() -> tuple[tuple[Any, ...], dict[str, Any]]:
        cursor["frame"] = (cursor["frame"] + 1) % COVERED_SPAN_FRAMES
        return (readers, base + cursor["frame"] / FPS), {}

    benchmark.pedantic(_fanout, setup=setup, rounds=40, iterations=1)
    _assert_within(benchmark, RESCRUB_BUDGET_S)


def test_the_frame_window_actually_covers_the_rescrub_span(
    readers: list[PyAVReader],
) -> None:
    """Guard the guard: if the window shrinks, the re-scrub result is a lie."""
    assert readers[0]._max_cached_frames >= COVERED_SPAN_FRAMES


def _assert_within(benchmark: Any, budget_s: float) -> None:
    if benchmark.stats is None:
        pytest.skip("benchmark statistics unavailable (benchmarks disabled)")
    assert benchmark.stats.stats.mean < budget_s
