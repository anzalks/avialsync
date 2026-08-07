"""The scrub-latency certification behind D-075: PyAV against libmpv.

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

The libmpv arm exists so the comparison stays reproducible rather than
historical.  It skips cleanly wherever libmpv is absent — including the
``avialsync`` conda env, where it always has been absent.
"""

from __future__ import annotations

import ctypes.util
import os
import sys
from collections.abc import Callable, Iterator
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


# -------------------------------------------------------------- libmpv arm
#
# Retained so the D-075 comparison can be re-run, not because the application
# still uses libmpv.  Everything below is throwaway harness code and must never
# be read as a pattern for product code — in particular the ``find_library``
# patch, which exists only because ``conda run`` strips ``DYLD_*`` under SIP and
# so hides Homebrew's copy from conda's Python.
#
# Opt in with ``AVIALSYNC_BENCH_LIBMPV=1``.  It is off by default because it
# adds ~45 s to re-measure a backend the project is deleting, whose numbers are
# already recorded in BLUEPRINT.md and D-075.  Every wait carries a timeout:
# libmpv settles through property observation, and an observation that never
# arrives would otherwise hang the run with no output.

#: Any single libmpv operation exceeding this has stopped being slow and
#: started being stuck.  The measurement itself is ~330 ms.
_MPV_TIMEOUT_S = 20.0

_LIBMPV_CANDIDATES = (
    "/opt/homebrew/lib/libmpv.dylib",
    "/usr/local/lib/libmpv.dylib",
    "/usr/lib/x86_64-linux-gnu/libmpv.so.2",
    "/usr/lib/libmpv.so.2",
)


def _import_mpv() -> Any:
    """Import ``mpv``, pointing ctypes at a known libmpv if it cannot find one.

    ``import mpv`` raises ``OSError`` — not ``ImportError`` — when libmpv is
    missing, which ``importorskip`` would let through as an error.
    """
    if os.environ.get("AVIALSYNC_BENCH_LIBMPV") != "1":
        pytest.skip("set AVIALSYNC_BENCH_LIBMPV=1 to re-measure the libmpv baseline")
    if ctypes.util.find_library("mpv") is None:
        found = next((path for path in _LIBMPV_CANDIDATES if Path(path).exists()), None)
        if found is None and not os.environ.get("AVIALSYNC_LIBMPV_PATH"):
            pytest.skip("libmpv is not installed; the comparison arm cannot run")
        target = found or os.environ["AVIALSYNC_LIBMPV_PATH"]
        original = ctypes.util.find_library
        ctypes.util.find_library = lambda name: target if name == "mpv" else original(name)
    try:
        import mpv
    except (ImportError, OSError) as error:  # pragma: no cover - environment dependent
        pytest.skip(f"libmpv unavailable: {error}")
    return mpv


@pytest.fixture(scope="module")
def mpv_players(camera_files: list[Path]) -> Iterator[list[Any]]:
    """One headless libmpv instance per camera, seeking exactly."""
    mpv = _import_mpv()
    if sys.platform != "win32":
        import locale

        # The locale bomb: libmpv misparses float seeks in decimal-comma
        # locales unless LC_NUMERIC is C.
        locale.setlocale(locale.LC_NUMERIC, "C")

    players = []
    try:
        for path in camera_files:
            player = mpv.MPV(vo="null", hwdec="no", keep_open="yes", pause=True)
            players.append(player)
            player.play(str(path))
            player.wait_until_playing(timeout=_MPV_TIMEOUT_S)
    except TimeoutError:
        for player in players:
            player.terminate()
        pytest.skip("libmpv never reached a playing state; the comparison arm cannot run")
    yield players
    for player in players:
        player.terminate()


def _mpv_fanout(players: list[Any], t: float) -> None:
    """Seek every player exactly to ``t`` and wait for the frame to settle.

    Settle is detected by property observation, never by sleeping: "the seek
    command returned" is not "the frame is on screen".
    """

    def seek(player: Any) -> None:
        player.seek(t, reference="absolute", precision="exact")
        player.wait_for_property("seeking", lambda value: not value, timeout=_MPV_TIMEOUT_S)

    with ThreadPoolExecutor(max_workers=len(players)) as pool:
        list(pool.map(seek, players))


def _bench_mpv(benchmark: Any, players: list[Any], targets: Callable[[], float]) -> None:
    def setup() -> tuple[tuple[Any, ...], dict[str, Any]]:
        return (players, targets()), {}

    benchmark.pedantic(_mpv_fanout, setup=setup, rounds=15, iterations=1)


def test_bench_libmpv_jump_to_a_new_time(benchmark: Any, mpv_players: list[Any]) -> None:
    """The libmpv baseline D-075 measured 330 ms for."""
    targets = _jump_targets()
    _bench_mpv(benchmark, mpv_players, lambda: next(targets))


def test_bench_libmpv_drag_the_slider(benchmark: Any, mpv_players: list[Any]) -> None:
    """Measured 338 ms — a drag costs libmpv the same as a jump."""
    cursor = {"frame": 0}

    def next_target() -> float:
        cursor["frame"] = (cursor["frame"] + 1) % (COVERED_SPAN_FRAMES * 2)
        return 300 / FPS + cursor["frame"] / FPS

    _bench_mpv(benchmark, mpv_players, next_target)


def test_bench_libmpv_rescrub_a_covered_span(benchmark: Any, mpv_players: list[Any]) -> None:
    """Measured 333 ms — mpv holds no memory of the span it just covered."""
    cursor = {"frame": 0}

    def next_target() -> float:
        cursor["frame"] = (cursor["frame"] + 1) % COVERED_SPAN_FRAMES
        return 300 / FPS + cursor["frame"] / FPS

    _bench_mpv(benchmark, mpv_players, next_target)
