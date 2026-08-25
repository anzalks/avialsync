"""The playback clock is ``time.perf_counter``, and must stay that way.

``MasterClock.advance`` integrates *deltas between successive samples* of
whatever clock the player hands it, so the clock's resolution is not a detail of
reporting — it is the step size of the playhead itself.

Through Python 3.12 — and ``pyproject.toml`` pins ``requires-python <3.13`` — the
Windows ``time.monotonic`` is ``GetTickCount64``, which advances on the system
tick: 15.625 ms, delivered as whole-millisecond steps of 15, 16, 16, 15, 16 …
The trap is that 15.625 ms is not *coarser* than the 16 ms tick — it is very
slightly finer, which is what makes the number look harmless. It is the same
*size*, and a clock can only measure an interval it is much finer than. At a
ratio of 16 / 15.625 = 1.024 every tick spans either one lattice cell or two, so
the delta handed to ``advance`` is 15.625 ms or 31.25 ms and never the ~16 ms
that really elapsed. The playhead alternately dawdles at 0.94x and leaps at
1.88x while the wall clock runs evenly — see
``test_a_coarse_clock_makes_the_playhead_lurch`` for that stated as an
assertion. CPython moved ``monotonic`` onto ``QueryPerformanceCounter`` in 3.13
(gh-88494); this project cannot wait for that, and pinning it here means a later
3.13 bump cannot quietly make the choice look arbitrary.

Two dead ends worth not re-walking:

* Raising the global timer resolution does **not** fix it. ``timeBeginPeriod``
  moves the timer interrupt, not ``GetTickCount64``'s published tick. Measured
  on the development machine: ``NtQueryTimerResolution`` reported 1.0 ms current
  resolution while ``time.monotonic`` still stepped 64 times a second.
* "Every other tick advances nothing" overstates it, and measuring is cheaper
  than assuming: a real 16 ms ``QTimer`` on the development machine produced a
  zero delta on 1 tick out of 299, not half of them. Zero deltas need the timer
  to fire *faster* than the lattice, which only jitter does at 16 ms. The
  routine damage is the lurch, not the stall — and it lands on every tick.

``perf_counter`` is ``QueryPerformanceCounter`` on Windows (~100 ns) and is
monotonic on every platform this ships to, which is the only property
``advance`` actually requires of it.
"""

from __future__ import annotations

import ast
import sys
import time
from pathlib import Path

import pytest

from avialsync.core.timeline import MasterClock
from avialsync.engine import player as player_module
from avialsync.ui import diagnostics as diagnostics_module
from avialsync.ui import plot_pane as plot_pane_module
from avialsync.ui import ui_heartbeat as ui_heartbeat_module
from avialsync.ui import video_pane as video_pane_module

#: ``GetTickCount64``'s step, and the whole problem: 1 / 64 s.
COARSE_GRID_S = 0.015625

#: What ``Player`` asks its ``QTimer`` for -- ``1000 // 60`` ms.
TICK_S = (1000 // 60) / 1000.0

#: Every module that times something shorter than the coarse clock's step, and
#: the name each one binds its clock to. They are listed rather than discovered
#: so that adding a fourth is a deliberate act: a module doing sub-second timing
#: with no seam at all is exactly the regression this cannot see.
TIMING_SEAMS = (
    (player_module, "_now"),
    (plot_pane_module, "_elapsed"),
    (video_pane_module, "_elapsed"),
    (ui_heartbeat_module, "_elapsed"),
    (diagnostics_module, "_elapsed"),
)


@pytest.mark.parametrize(("module", "seam"), TIMING_SEAMS, ids=lambda v: getattr(v, "__name__", v))
def test_every_timing_module_samples_perf_counter(module: object, seam: str) -> None:
    """The seams the rest of the suite fakes, pinned to their real clock."""
    assert getattr(module, seam) is time.perf_counter


@pytest.mark.parametrize(("module", "seam"), TIMING_SEAMS, ids=lambda v: getattr(v, "__name__", v))
def test_no_timing_module_reaches_for_time_monotonic(module: object, seam: str) -> None:
    """Fail loudly if ``time.monotonic`` is put back into a sub-second budget.

    All five modules made the same mistake independently, which is why this is
    a matrix and not a note in one file: the playback tick lurched, the plot's
    8 ms row-build slice read as 0 ms and never yielded, the 50 ms OSD throttle
    ran at 16 Hz while re-arming a timer it could not resolve, the stall
    detector policed a 30 ms threshold with a 15.625 ms clock, and the disk
    probe reported a 1600 MB/s drive as either 1032 or 2000.

    ``job_manager`` and ``__main__`` are deliberately absent: their budgets are
    20 s and 110 s, where the lattice is rounding error rather than a defect.

    Checked against the parsed module rather than by grepping, so the prose in
    these files -- which names ``time.monotonic`` repeatedly, as does this one
    -- cannot be mistaken for a use of it.
    """
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))  # type: ignore[attr-defined]

    offenders: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "monotonic"
            and isinstance(node.value, ast.Name)
            and node.value.id == "time"
        ):
            offenders.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            offenders.extend(node.lineno for alias in node.names if alias.name == "monotonic")

    assert not offenders, (
        f"{module.__name__} reads time.monotonic at line(s) {offenders}: on "  # type: ignore[attr-defined]
        f"Windows through Python 3.12 that clock steps in "
        f"{COARSE_GRID_S * 1000:.3f} ms, which no sub-second budget in this app "
        f"can resolve. Use the module's `{seam}` alias."
    )


def _playhead_per_tick(sample_at: object, ticks: int = 240) -> list[float]:
    """Return how far the playhead moved on each tick, given a clock.

    ``sample_at`` maps a tick's true elapsed time to whatever the clock under
    test would report at that instant.
    """
    clock = MasterClock()
    clock.set_bounds(0.0, 3600.0)
    clock.play()

    read = sample_at  # type: ignore[assignment]
    clock.advance(read(0.0))  # type: ignore[operator]

    moves: list[float] = []
    previous = clock.state.t
    for step in range(1, ticks + 1):
        clock.advance(read(step * TICK_S))  # type: ignore[operator]
        moves.append(clock.state.t - previous)
        previous = clock.state.t
    return moves


def test_a_fine_clock_moves_the_playhead_by_one_tick_per_tick() -> None:
    """The control case: a clock finer than the tick just works."""
    moves = _playhead_per_tick(lambda elapsed: elapsed)

    assert all(move == pytest.approx(TICK_S, abs=1e-9) for move in moves)


def test_a_coarse_clock_makes_the_playhead_lurch() -> None:
    """The defect, stated as an assertion rather than as a comment.

    Quantising the same tick sequence onto ``GetTickCount64``'s lattice means no
    tick advances by the 16 ms that actually elapsed. Every one is either short
    (15.625 ms, 0.94x speed) or a double step (31.25 ms, 1.88x) -- a playhead
    that alternately dawdles and leaps while the wall clock runs evenly. At
    30 fps a 31.25 ms jump is very nearly a whole frame skipped in one tick.

    Note what is *not* asserted: that ticks stall. At a 16 ms tick they almost
    never do (see the module docstring). Lurching is the real, every-tick
    defect, so lurching is what this pins.
    """
    moves = _playhead_per_tick(lambda elapsed: (elapsed // COARSE_GRID_S) * COARSE_GRID_S)

    assert not any(move == pytest.approx(TICK_S, abs=1e-4) for move in moves), (
        "the coarse clock is supposed to be unable to report a true 16 ms tick"
    )
    # Every step it *can* report is a whole number of lattice cells.
    assert all(
        move == pytest.approx(round(move / COARSE_GRID_S) * COARSE_GRID_S, abs=1e-9)
        for move in moves
    )
    # And it uses more than one of them: that alternation is the visible judder.
    assert {round(move / COARSE_GRID_S) for move in moves} == {1, 2}


@pytest.mark.skipif(sys.platform != "win32", reason="the coarse clock is a Windows problem")
def test_the_two_clocks_still_differ_the_way_this_file_claims() -> None:
    """Guard the premise itself, so a wrong reason cannot outlive the fix.

    If CPython ever gives Windows a fine ``monotonic`` below 3.13, or the pin
    moves to 3.13+, this fails and the docstring above needs rewriting rather
    than quietly becoming folklore.
    """
    monotonic_res = time.get_clock_info("monotonic").resolution
    perf_res = time.get_clock_info("perf_counter").resolution

    # "Resolves" means the step is a small fraction of the interval, not merely
    # a smaller number than it. 15.625 ms passes a naive `< 16 ms` test, which is
    # exactly how this clock keeps looking adequate.
    assert perf_res < TICK_S / 100, "perf_counter must comfortably resolve a playback tick"
    if sys.version_info >= (3, 13):
        pytest.skip("3.13 moved monotonic onto QueryPerformanceCounter (gh-88494)")
    assert monotonic_res > TICK_S / 2, (
        f"monotonic resolves {monotonic_res * 1000:.3f} ms against a "
        f"{TICK_S * 1000:.0f} ms tick -- the reason for `_now` may have changed"
    )


# -- The same clock, the same bug, in the OSD throttle -----------------


def _osd_pane() -> object:
    """The minimum surface ``_flush_osd_update`` touches, plus two counters."""
    import threading
    from types import SimpleNamespace

    pane = SimpleNamespace(
        _osd_lock=threading.Lock(),
        _pending_osd=(0.0, 30.0),
        _osd_event_pending=False,
        _osd_flush_timer=None,
        _last_osd_flush=0.0,
        _osd_update=SimpleNamespace(emit=lambda: None),
        paints=[],
        arms=[],
    )
    pane._update_osd = lambda t, fps: pane.paints.append(t)
    pane._arm_osd_flush_timer = lambda delay: pane.arms.append(delay)
    return pane


def _osd_rate_under(clock, qapp) -> int:
    """Return how many OSD paints one second of 120 fps delivery produces."""
    pane = _osd_pane()
    flush = video_pane_module.VideoPane._flush_osd_update
    queue = video_pane_module.VideoPane._queue_osd_update

    real = video_pane_module._elapsed
    try:
        for frame in range(120):
            now = clock(frame / 120.0)
            video_pane_module._elapsed = lambda now=now: now
            queue(pane, frame / 120.0, 120.0)
            flush(pane)
    finally:
        video_pane_module._elapsed = real
    return len(pane.paints)


def test_the_osd_throttle_meets_its_budget_on_a_fine_clock(qapp) -> None:
    """20 Hz documented, 20 Hz delivered -- the control case."""
    paints = _osd_rate_under(lambda elapsed: elapsed, qapp)

    assert paints >= video_pane_module._OSD_MAX_HZ - 1, (
        f"{paints} paints in a second, below the documented {video_pane_module._OSD_MAX_HZ:.0f} Hz"
    )


def test_a_coarse_clock_would_drop_the_osd_below_its_budget(qapp) -> None:
    """Why the OSD throttle cannot read ``time.monotonic`` either.

    A 50 ms interval measured on a 15.625 ms lattice can only come out as a
    multiple of the lattice, so the first multiple at or past 50 ms is 62.5 ms:
    16 Hz, a fifth below the rate the constant promises. Nothing warns about
    it -- the pane simply repaints more slowly on Windows than the code says.
    """
    paints = _osd_rate_under(lambda elapsed: (elapsed // COARSE_GRID_S) * COARSE_GRID_S, qapp)

    assert paints < video_pane_module._OSD_MAX_HZ - 2, (
        "the coarse clock is supposed to undershoot the budget; if this passes, "
        "recheck the lattice arithmetic rather than deleting the test"
    )


def test_a_coarse_clock_cannot_resolve_its_own_trailing_paint(qapp) -> None:
    """The deferred paint must actually come due when its timer fires.

    ``_flush_osd_update`` defers by arming a timer for exactly the time it says
    is left. On a fine clock, waiting that long makes the paint due. On the
    coarse clock the wait is shorter than one lattice step, so the clock reads
    the same value, ``remaining`` is unchanged, and the timer re-arms itself
    identically -- burning a wakeup per pane and delaying the paint until the
    lattice happens to move.
    """
    flush = video_pane_module.VideoPane._flush_osd_update
    real = video_pane_module._elapsed

    # Park the clock where a paint is close, but not quite, due.
    parked = 3 * COARSE_GRID_S
    assert 0 < video_pane_module._OSD_MIN_INTERVAL_S - parked

    try:
        # Fine clock: arm once, wait exactly that long, and it paints.
        fine = _osd_pane()
        fine._osd_event_pending = True
        video_pane_module._elapsed = lambda: parked
        flush(fine)
        assert len(fine.arms) == 1, "a paint that is not due yet must be deferred"
        waited = parked + fine.arms[0]
        video_pane_module._elapsed = lambda: waited
        flush(fine)
        assert fine.paints, "waiting the armed delay must make the paint due"

        # Coarse clock: the same wait does not move the clock at all.
        coarse = _osd_pane()
        coarse._osd_event_pending = True
        video_pane_module._elapsed = lambda: parked
        flush(coarse)
        armed = coarse.arms[0]
        assert armed < COARSE_GRID_S, "the whole trap is arming below one step"
        video_pane_module._elapsed = lambda: ((parked + armed) // COARSE_GRID_S) * COARSE_GRID_S
        flush(coarse)
        assert not coarse.paints, "the coarse clock cannot have come due"
        assert coarse.arms == [armed, armed], "it re-arms the identical delay"
    finally:
        video_pane_module._elapsed = real


# -- The same clock, hiding the stalls the detector exists to find -----


def _stalls_seen(stall_s: float, clock, qapp) -> tuple[int, float]:
    """Report a stall of *stall_s* to a fresh heartbeat, as *clock* would see it.

    Returns ``(stall_count, lateness_ms)`` -- what the detector concluded, and
    what it thought it measured.
    """
    heartbeat = ui_heartbeat_module.UiHeartbeat()
    interval_s = ui_heartbeat_module._INTERVAL_MS / 1000.0

    real = ui_heartbeat_module._elapsed
    try:
        ui_heartbeat_module._elapsed = lambda: clock(0.0)
        heartbeat.start()
        # The timer was due at `interval_s` and actually fired `stall_s` late.
        ui_heartbeat_module._elapsed = lambda: clock(interval_s + stall_s)
        heartbeat._tick()
    finally:
        ui_heartbeat_module._elapsed = real
    return heartbeat.stall_count, heartbeat.worst_stall_ms


def test_a_fine_clock_catches_a_stall_just_over_the_threshold(qapp) -> None:
    """The control case: 35 ms of blocking is over the 30 ms ceiling, so it counts."""
    stall_s = (ui_heartbeat_module.STALL_THRESHOLD_MS + 5.0) / 1000.0

    count, lateness_ms = _stalls_seen(stall_s, lambda elapsed: elapsed, qapp)

    assert count == 1
    assert lateness_ms == pytest.approx(stall_s * 1000.0, abs=0.5)


def test_a_coarse_clock_loses_a_real_stall_entirely(qapp) -> None:
    """Why the stall detector cannot read ``time.monotonic`` either.

    A 100 ms interval measured on a 15.625 ms lattice is 93.75 ms or 109.375 ms,
    so a timer that fired perfectly on time already reports several ms of
    lateness in either direction. The error is half the threshold being
    policed, and here it swallows a genuine 35 ms block whole: the detector
    concludes the UI thread is healthy and says nothing.

    This is the worst of the five, because it is the failure that *hides other
    failures* -- the tool reports a clean bill of health on the one platform
    where it cannot measure.
    """
    stall_s = (ui_heartbeat_module.STALL_THRESHOLD_MS + 5.0) / 1000.0

    count, lateness_ms = _stalls_seen(
        stall_s, lambda elapsed: (elapsed // COARSE_GRID_S) * COARSE_GRID_S, qapp
    )

    assert count == 0, "the coarse clock is supposed to miss this stall"
    assert lateness_ms < ui_heartbeat_module.STALL_THRESHOLD_MS
