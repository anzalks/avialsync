"""Playback must not generate work proportional to the decoded frame rate.

Two independent costs used to scale with ``panes x fps`` on the UI thread, which
is what a six-camera high-frame-rate session cannot afford:

* the drift corrector judged libmpv's frame-quantised ``time_pos`` against a
  sub-frame tolerance, so a perfectly healthy pane was declared out of sync
  about half the time and had ``mpv.speed`` rewritten ~48 times a second; and
* each pane relaid out its OSD label and composited its tracking overlay once
  per *decoded* frame, unthrottled.

Both are bounded here.  These are behavioural budgets, not micro-benchmarks:
they count calls, so they are deterministic on any machine.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from avialsync.core.timeline import MasterClock, TimeMap
from avialsync.engine.player import Player
from avialsync.ui import video_pane as video_pane_module

FPS = 30.0
INTERVAL = 1.0 / FPS
TICK = 1.0 / 60.0


class StaircasePane:
    """A pane that reports time like libmpv actually does.

    ``time_pos`` is the timestamp of the frame *currently on screen*, so it only
    advances when a new frame is presented.  Sampled by a 60 Hz tick against a
    continuous master clock, a decoder that is exactly in sync still reads back
    as anywhere from zero to one whole frame interval behind.
    """

    def __init__(self, *, intrinsic_rate: float = 1.0, start_offset: float = 0.0) -> None:
        self.mpv = object()
        self.is_seeking = False
        self.time_map = TimeMap()
        self.sync_correction = 1.0
        self.speed_writes = 0
        self.seeks = 0
        self._intrinsic_rate = intrinsic_rate
        self._pinned = intrinsic_rate == 1.0 and start_offset == 0.0
        self.decoder_t = start_offset
        self.time_pos = start_offset

    # -- the surface Player uses --
    def has_footage_at_master(self, t_master: float) -> bool:
        return True

    def set_has_footage(self, has_footage: bool) -> None:
        pass

    def play(self) -> None:
        pass

    def pause(self) -> None:
        pass

    def set_mapping_rate_at(self, t_master: float) -> None:
        pass

    def frame_interval_at_master(self, t_master: float) -> float:
        return INTERVAL

    def set_sync_correction(self, correction: float) -> None:
        if correction != self.sync_correction:
            self.speed_writes += 1
        self.sync_correction = correction

    # -- simulation --
    def advance(self, dt: float, master_t: float) -> None:
        if self._pinned:
            self.decoder_t = master_t  # a decoder holding the clock exactly
        else:
            self.decoder_t += dt * self._intrinsic_rate * self.sync_correction
        self.time_pos = np.floor(self.decoder_t / INTERVAL) * INTERVAL

    def jump_to(self, source_t: float) -> None:
        self.seeks += 1
        self.decoder_t = source_t
        self.time_pos = np.floor(source_t / INTERVAL) * INTERVAL


def _rigged_player(panes: list[StaircasePane]) -> tuple[Player, MasterClock]:
    grid = MagicMock()
    grid.panes = panes
    grid.visible_panes.return_value = panes

    clock = MasterClock()
    clock.set_bounds(0.0, 3600.0)

    player = Player.__new__(Player)
    player.clock = clock
    player.video_grid = grid
    player.plot_pane = MagicMock()
    player.transport = MagicMock()
    player.tracking_3d_pane = None
    player._readout_panel = None
    player.seeker = MagicMock()
    player.seeker.is_settled.return_value = True
    player.seeker.seek_pane = lambda pane, source_t, exact=True: pane.jump_to(source_t)
    player._drift_counts = {}
    player._drift_estimates = {}
    player._playing_pane_ids = {id(p) for p in panes}
    player._displayed_pane_ids = {id(p) for p in panes}
    player._last_presentation_at = 0.0
    player._last_tick_monotonic = 0.0
    player._is_scrubbing = False
    player._pending_scrub_t = None
    player._queued_frame_steps = 0
    player._frame_step_reference = None
    player._ab_in = None
    player._ab_out = None
    return player, clock


def _run(player: Player, clock: MasterClock, panes: list[StaircasePane], seconds: float) -> None:
    """Drive the real tick for *seconds* of simulated playback."""
    clock.play()
    clock.advance(0.0)
    real_monotonic = time.monotonic
    try:
        for step in range(1, int(seconds / TICK) + 1):
            now = step * TICK
            for pane in panes:
                pane.advance(TICK, clock.state.t)
            time.monotonic = lambda now=now: now  # type: ignore[assignment]
            player._on_tick()
    finally:
        time.monotonic = real_monotonic  # type: ignore[assignment]


# ── Drift correction ──────────────────────────────────────────────────


def test_a_pane_holding_the_clock_is_never_corrected(qapp: QApplication) -> None:
    """The core regression: frame quantisation is not drift.

    Judging the ``time_pos`` staircase against a half-frame tolerance used to
    produce ~48 ``mpv.speed`` writes per second per pane for a decoder that was
    keeping perfect time.  Every one of those takes libmpv's core lock away from
    the decoder threads.
    """
    pane = StaircasePane()
    player, clock = _rigged_player([pane])

    _run(player, clock, [pane], seconds=10.0)

    assert pane.speed_writes == 0
    assert pane.seeks == 0


def test_a_slow_decoder_is_still_corrected(qapp: QApplication) -> None:
    """Widening the deadband must not make the corrector deaf to real drift."""
    pane = StaircasePane(intrinsic_rate=0.97)
    player, clock = _rigged_player([pane])

    _run(player, clock, [pane], seconds=20.0)

    assert pane.speed_writes > 0, "a decoder running 3% slow must be corrected"
    assert pane.sync_correction > 1.0, "correction must speed the pane up, not slow it"
    # Held to a couple of frames rather than allowed to run away.
    assert abs(pane.decoder_t - clock.state.t) < INTERVAL * 4


def test_correcting_a_slow_decoder_does_not_thrash_libmpv(qapp: QApplication) -> None:
    """Correction is smoothed and quantised, so it settles instead of rattling."""
    pane = StaircasePane(intrinsic_rate=0.97)
    player, clock = _rigged_player([pane])

    _run(player, clock, [pane], seconds=20.0)

    # The raw residual is quantised to a frame, so an unsmoothed proportional
    # law flips between adjacent speed steps on almost every tick (measured at
    # ~56/s).  A few per second is a controller tracking; dozens is thrash.
    assert pane.speed_writes < 20.0 * 5


def test_a_pane_that_starts_behind_is_seeked_once(qapp: QApplication) -> None:
    """A delayed start is a position discontinuity, not something to nudge.

    The drift estimate describes where the pane *was*; if it survives the
    corrective seek the pane stays above threshold and is re-seeked in a loop.
    """
    pane = StaircasePane(start_offset=-2.0)
    player, clock = _rigged_player([pane])

    _run(player, clock, [pane], seconds=20.0)

    assert pane.seeks == 1
    assert abs(pane.decoder_t - clock.state.t) < INTERVAL


def test_one_struggling_pane_does_not_disturb_its_neighbours(qapp: QApplication) -> None:
    """Per-pane drift state must stay per-pane in a multi-camera session."""
    healthy = [StaircasePane() for _ in range(3)]
    struggling = StaircasePane(intrinsic_rate=0.97)
    panes = [*healthy, struggling]
    player, clock = _rigged_player(panes)

    _run(player, clock, panes, seconds=10.0)

    assert all(p.speed_writes == 0 for p in healthy)
    assert all(p.seeks == 0 for p in healthy)
    assert struggling.speed_writes > 0


# ── Per-frame UI work ─────────────────────────────────────────────────


class _OsdPane(SimpleNamespace):
    """The minimum surface ``_flush_osd_update`` touches."""

    def _update_osd(self, t: float, fps: float) -> None:
        self.updates.append(t)


def _osd_pane() -> _OsdPane:
    import threading

    pane = _OsdPane(
        _osd_lock=threading.Lock(),
        _pending_osd=(0.0, 0.0),
        _osd_event_pending=False,
        _osd_flush_timer=None,
        _last_osd_flush=0.0,
        # The real signal is queued to the UI thread; these tests call the slot
        # directly so the rate limit is what is under test, not Qt delivery.
        _osd_update=SimpleNamespace(emit=lambda: None),
        updates=[],
    )
    pane._arm_osd_flush_timer = lambda delay_s: None  # no event loop in this test
    return pane


def test_osd_repaints_are_capped_below_the_frame_rate(qapp: QApplication) -> None:
    """A 120 fps pane must not relayout its OSD and overlay 120 times a second.

    Six panes of high-frame-rate footage would otherwise spend the entire UI
    tick budget on text nobody can read that fast.
    """
    pane = _osd_pane()
    flush = video_pane_module.VideoPane._flush_osd_update
    queue = video_pane_module.VideoPane._queue_osd_update

    real_monotonic = time.monotonic
    try:
        # One simulated second of 120 fps frame delivery.
        for frame in range(120):
            now = frame / 120.0
            time.monotonic = lambda now=now: now  # type: ignore[assignment]
            queue(pane, now, 120.0)
            flush(pane)
    finally:
        time.monotonic = real_monotonic  # type: ignore[assignment]

    assert len(pane.updates) <= video_pane_module._OSD_MAX_HZ + 1
    assert len(pane.updates) >= 1


def test_the_first_frame_after_a_pause_paints_immediately(qapp: QApplication) -> None:
    """A paused seek or frame step must show its result at once, not in 50 ms."""
    pane = _osd_pane()
    flush = video_pane_module.VideoPane._flush_osd_update
    queue = video_pane_module.VideoPane._queue_osd_update

    real_monotonic = time.monotonic
    try:
        time.monotonic = lambda: 100.0  # type: ignore[assignment]
        queue(pane, 4.25, 30.0)
        flush(pane)
    finally:
        time.monotonic = real_monotonic  # type: ignore[assignment]

    assert pane.updates == [4.25]


def test_a_deferred_osd_paint_keeps_the_newest_frame(qapp: QApplication) -> None:
    """Rate limiting must drop intermediate frames, never show a stale one."""
    pane = _osd_pane()
    flush = video_pane_module.VideoPane._flush_osd_update
    queue = video_pane_module.VideoPane._queue_osd_update

    real_monotonic = time.monotonic
    try:
        time.monotonic = lambda: 100.0  # type: ignore[assignment]
        queue(pane, 1.0, 30.0)
        flush(pane)  # paints immediately
        for frame in range(1, 6):  # arrive inside the rate-limit window
            queue(pane, 1.0 + frame / 120.0, 30.0)
            flush(pane)
        # The window elapses and the trailing paint runs.
        time.monotonic = lambda: 100.0 + video_pane_module._OSD_MIN_INTERVAL_S  # type: ignore[assignment]
        flush(pane)
    finally:
        time.monotonic = real_monotonic  # type: ignore[assignment]

    assert pane.updates == [1.0, pytest.approx(1.0 + 5 / 120.0)]


# ── The plot scene must not repaint at the tick rate ──────────────────


def test_the_plot_repaints_at_half_the_tick_rate(qapp: QApplication) -> None:
    """Time advances at 60 Hz; pixels do not.

    Repainting the plot scene costs ~8 ms at 16 rows and ~15 ms at 32, out of a
    16.7 ms tick budget shared with every video pane's ``paintGL``. Doing that
    60 times a second consumed 39-74% of the UI thread and starved video
    presentation, which is what made frames look choppy.
    """
    from avialsync.ui import plot_pane as plot_pane_module

    pane = plot_pane_module.PlotPane()
    repaints: list[float] = []
    pane.view_window_changed.connect(lambda *_: repaints.append(1.0))

    real_monotonic = time.monotonic
    try:
        for step in range(120):  # two seconds of 60 Hz ticks
            now = step / 60.0
            time.monotonic = lambda now=now: now  # type: ignore[assignment]
            pane.set_cursor(1.0 + now)
    finally:
        time.monotonic = real_monotonic  # type: ignore[assignment]

    expected = 2.0 * plot_pane_module._CURSOR_REPAINT_HZ
    assert len(repaints) <= expected + 1
    assert len(repaints) >= expected - 2, "the cursor must still move smoothly"


def test_a_seek_repaints_the_plot_immediately(qapp: QApplication) -> None:
    """Throttling is for playback; a discrete event must never show a stale cursor."""
    from avialsync.ui import plot_pane as plot_pane_module

    pane = plot_pane_module.PlotPane()
    repaints: list[float] = []
    pane.view_window_changed.connect(lambda *_: repaints.append(1.0))

    real_monotonic = time.monotonic
    try:
        time.monotonic = lambda: 500.0  # type: ignore[assignment]
        pane.set_cursor(1.0, immediate=True)
        pane.set_cursor(1.5, immediate=True)
        pane.set_cursor(2.0, immediate=True)
    finally:
        time.monotonic = real_monotonic  # type: ignore[assignment]

    assert len(repaints) == 3


def test_the_player_marks_discrete_events_immediate(qapp: QApplication) -> None:
    """The `force` that bypasses the readout rate limit must reach the plot too."""
    player = Player.__new__(Player)
    player.plot_pane = MagicMock()
    player.transport = MagicMock()
    player.tracking_3d_pane = None
    player._readout_panel = None
    player._last_presentation_at = 0.0

    player._update_timeline_views(1.0, now=0.0, force=True)
    player._update_timeline_views(2.0, now=0.1, force=False)

    assert player.plot_pane.set_cursor.call_args_list[0].kwargs["immediate"] is True
    assert player.plot_pane.set_cursor.call_args_list[1].kwargs["immediate"] is False


# ── Painting must never reach into libmpv ─────────────────────────────


def test_the_overlay_never_queries_mpv_while_painting(qapp: QApplication) -> None:
    """``paintEvent`` runs on the UI thread once per pane per frame.

    Reading ``dwidth``/``dheight`` there takes libmpv's core lock while the
    decoder threads are contending for it (measured at 26-34 us typical,
    165 us at p99).  The size is mirrored by a property observer instead.
    """
    from avialsync.ui.video_overlay import PaintCanvas

    class _ExplodingMpv:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"paintEvent must not read mpv.{name}")

    canvas = PaintCanvas()
    pane = SimpleNamespace(mpv=_ExplodingMpv(), video_size=(640, 360))
    canvas.setParent(None)
    canvas.parent = lambda: pane  # type: ignore[method-assign]
    canvas.resize(320, 240)

    scale, offset_x, offset_y = canvas._video_scale()

    assert scale == pytest.approx(0.5)
    assert offset_x == pytest.approx(0.0)
    assert offset_y == pytest.approx(30.0)


def test_an_empty_overlay_does_not_schedule_repaints(qapp: QApplication) -> None:
    """Most sessions have no tracking data; those panes must cost nothing."""
    from avialsync.ui.video_overlay import PaintCanvas

    canvas = PaintCanvas()
    repaints = []
    canvas.update = lambda *a: repaints.append(1)  # type: ignore[method-assign]

    for frame in range(120):
        canvas.update_time(frame / 120.0)

    assert repaints == []
    assert canvas.t == pytest.approx(119 / 120.0), "time must still advance"


def test_an_overlay_with_tracks_still_repaints(qapp: QApplication) -> None:
    """The skip must be about having nothing to draw, not about being idle."""
    from avialsync.ui.video_overlay import OverlayTrack, PaintCanvas

    canvas = PaintCanvas()
    canvas.set_tracks([OverlayTrack(label="eks", points={})])
    repaints = []
    canvas.update = lambda *a: repaints.append(1)  # type: ignore[method-assign]

    for frame in range(10):
        canvas.update_time(frame / 120.0)

    assert len(repaints) == 10


def test_the_overlay_waits_for_a_real_video_size(qapp: QApplication) -> None:
    """Before libmpv reports a size there is nothing meaningful to scale to."""
    from avialsync.ui.video_overlay import PaintCanvas

    canvas = PaintCanvas()
    pane = SimpleNamespace(video_size=None)
    canvas.parent = lambda: pane  # type: ignore[method-assign]

    assert canvas._video_scale() is None


def test_video_size_is_mirrored_from_mpv_video_out_params(qapp: QApplication) -> None:
    """The observer feeds the overlay so the paint path stays lock-free."""
    pane = SimpleNamespace(video_size=None)
    observe = video_pane_module.VideoPane._observe_video_params

    observe(pane, {"dw": 1920, "dh": 1080, "pixelformat": "yuv420p"})
    assert pane.video_size == (1920, 1080)

    # libmpv reports None between files; the last known good size is kept
    # rather than blanking the overlay mid-transition.
    observe(pane, None)
    assert pane.video_size == (1920, 1080)

    observe(pane, {"dw": 0, "dh": 0})
    assert pane.video_size == (1920, 1080)
