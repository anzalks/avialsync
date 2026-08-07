"""Playback must not generate work proportional to the decoded frame rate.

Each pane relays out its OSD label and composites its tracking overlay once per
*presented* frame, which without a cap scales with ``panes x fps`` on the UI
thread — what a six-camera high-frame-rate session cannot afford.  That cap is
bounded here.  These are behavioural budgets, not micro-benchmarks: they count
calls, so they are deterministic on any machine.

The other cost that used to scale this way was drift correction, and it is gone
rather than bounded (D-075).  It judged libmpv's frame-quantised ``time_pos``
against a sub-frame tolerance, so a perfectly healthy pane was declared out of
sync about half the time and had ``mpv.speed`` rewritten ~48 times a second.
The app now decodes, so it does not have to infer where a player got to: it
tells each pane which frame to show.  The first section below pins that — no
correction, and no drift for a correction to chase.
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
from avialsync.engine.seeker import SeekGroup
from avialsync.ui import video_pane as video_pane_module

FPS = 30.0
INTERVAL = 1.0 / FPS
TICK = 1.0 / 60.0


#: Names a pane must not be asked for during playback.  Every one of them is a
#: way of telling a decoder to run at its own rate, which is the model D-075
#: removed: the app decodes, so it says *which frame*, never *how fast*.
_RATE_CONTROL_NAMES = (
    "set_sync_correction",
    "sync_correction",
    "set_rate",
    "set_mapping_rate_at",
    "frame_interval_at_master",
    "mpv",
)


class DecodingPane:
    """A pane that shows the frame containing whatever time it is handed.

    It never advances on its own — that is the whole point.  A decoder with no
    clock of its own cannot drift away from one, so the only thing worth
    simulating is *latency*: how many ticks pass before the requested frame is
    actually on screen.
    """

    def __init__(self, *, decode_ticks: int = 0, offset: float = 0.0) -> None:
        self.time_map = TimeMap()
        if offset:
            self.time_map.set_mapping(offset=offset, drift_ppm=0.0)
        self.has_media = True
        self.is_seeking = False
        self.time_pos = 0.0
        self.displayed_frame: int | None = None
        self.requests: list[float] = []
        self._decode_ticks = decode_ticks
        self._busy = 0
        self._pending: float | None = None
        self._in_flight: float | None = None

    def __getattr__(self, name: str) -> object:
        if name in _RATE_CONTROL_NAMES:
            raise AssertionError(
                f"the player asked a pane for {name!r}: playback must command a "
                "frame, never a rate (D-075)"
            )
        raise AttributeError(name)

    # -- the surface Player uses --
    def has_footage_at_master(self, t_master: float) -> bool:
        return True

    def set_has_footage(self, has_footage: bool) -> None:
        pass

    def play(self) -> None:
        pass

    def pause(self) -> None:
        pass

    def seek(self, source_t: float, exact: bool = True) -> None:
        """Accept a frame request, coalescing onto the newest wanted time.

        This mirrors ``DecodeWorker``: a request arriving mid-decode does not
        restart the decode, it replaces whatever was queued behind it. Only the
        newest pending time is ever decoded, so a backlog cannot build.
        """
        self.requests.append(source_t)
        self._pending = source_t
        if self._busy == 0:
            self._start()

    # -- simulation --
    def tick(self) -> None:
        if self._busy > 0:
            self._busy -= 1
            if self._busy == 0:
                self._present()
                if self._pending is not None:
                    self._start()

    def _start(self) -> None:
        self._in_flight, self._pending = self._pending, None
        if self._decode_ticks <= 0:
            self._present()
        else:
            self.is_seeking = True
            self._busy = self._decode_ticks

    def _present(self) -> None:
        assert self._in_flight is not None
        self.displayed_frame = int(np.floor(self._in_flight / INTERVAL + 1e-9))
        self.time_pos = self.displayed_frame * INTERVAL
        self.is_seeking = False


def _rigged_player(panes: list[DecodingPane]) -> tuple[Player, MasterClock]:
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
    # The real SeekGroup, so the fanout and its per-pane time mapping are what
    # is under test rather than a mock's recollection of them.
    player.seeker = SeekGroup(panes)
    player._playing_pane_ids = {id(p) for p in panes}
    player._displayed_pane_ids = {id(p) for p in panes}
    player._last_presentation_at = 0.0
    player._last_tick_monotonic = 0.0
    player._is_scrubbing = False
    player._pending_scrub_t = None
    player._ab_in = None
    player._ab_out = None
    return player, clock


def _run(
    player: Player,
    clock: MasterClock,
    panes: list[DecodingPane],
    seconds: float,
) -> list[tuple[float, float]]:
    """Drive the real tick for *seconds* of simulated playback.

    Returns ``(master_t, lateness)`` for the first pane at every tick, so a test
    can ask whether an error *grew* rather than only how big it ended up.
    """
    clock.play()
    clock.advance(0.0)
    samples: list[tuple[float, float]] = []
    real_monotonic = time.monotonic
    try:
        for step in range(1, int(seconds / TICK) + 1):
            now = step * TICK
            for pane in panes:
                pane.tick()
            time.monotonic = lambda now=now: now  # type: ignore[assignment]
            player._on_tick()
            samples.append((clock.state.t, abs(panes[0].time_pos - clock.state.t)))
    finally:
        time.monotonic = real_monotonic  # type: ignore[assignment]
    return samples


# ── Playback commands frames, never rates ─────────────────────────────


def test_every_playing_tick_asks_each_pane_for_the_frame_at_master_time(
    qapp: QApplication,
) -> None:
    """The new playback model, stated as an assertion.

    Under libmpv the player watched where each decoder had got to and nudged it.
    Now it tells every pane which instant to show, every tick — so a pane cannot
    be anywhere other than where the master clock says.
    """
    pane = DecodingPane()
    player, clock = _rigged_player([pane])

    _run(player, clock, [pane], seconds=2.0)

    assert len(pane.requests) == pytest.approx(2.0 / TICK, rel=0.05)
    assert pane.displayed_frame == int(np.floor(clock.state.t / INTERVAL + 1e-9))


def test_a_slow_decoder_shows_an_older_frame_but_never_drifts(qapp: QApplication) -> None:
    """Lateness must not accumulate.

    A pane taking five ticks per frame is always a little behind, but it is
    behind by the same bounded amount at twenty seconds as at five — because
    each request carries an absolute time, not an increment. Under the old
    speed-nudge model this was the case that needed a controller.
    """
    decode_ticks = 5
    pane = DecodingPane(decode_ticks=decode_ticks)
    player, clock = _rigged_player([pane])

    samples = _run(player, clock, [pane], seconds=20.0)

    # Skip the first second: the pane genuinely has nothing on screen until its
    # first decode lands, and that is a start-up transient, not drift.
    steady = [lateness for t, lateness in samples if t > 1.0]
    early = steady[: len(steady) // 4]
    late = steady[-len(steady) // 4 :]

    # Everything a healthy-but-slow pane can be behind by, and nothing more:
    # the decode itself, the wait until the next decode replaces it, and the
    # frame quantisation every decoder has — the shown frame's own timestamp is
    # up to one interval below the continuous clock.
    bound = (2 * decode_ticks + 1) * TICK + INTERVAL
    assert max(early) < bound
    assert max(late) < bound, "lateness accumulated, which is drift"
    # The real assertion: bounded is not enough, it must not be *growing*.
    assert max(late) <= max(early) + TICK, "lateness grew over twenty seconds"


def test_a_pane_that_starts_behind_needs_no_correction(qapp: QApplication) -> None:
    """A position discontinuity is not a thing to converge on any more.

    The pane starts showing nothing at all; one tick later it is exactly where
    the master clock is, because it was told rather than nudged.
    """
    pane = DecodingPane()
    player, clock = _rigged_player([pane])
    assert pane.displayed_frame is None

    _run(player, clock, [pane], seconds=0.1)

    assert pane.displayed_frame == int(np.floor(clock.state.t / INTERVAL + 1e-9))


def test_each_pane_is_asked_for_its_own_source_time(qapp: QApplication) -> None:
    """A per-camera offset must reach the decoder, not just the readout.

    The direction is whatever ``TimeMap.to_source`` says; what matters here is
    that the fanout applies it per pane rather than handing every camera the
    same master instant.
    """
    aligned = DecodingPane()
    shifted = DecodingPane(offset=1.25)
    panes = [aligned, shifted]
    player, clock = _rigged_player(panes)

    _run(player, clock, panes, seconds=2.0)

    expected = shifted.time_map.to_source(clock.state.t)
    assert shifted.requests[-1] == pytest.approx(expected)
    assert shifted.requests[-1] != pytest.approx(aligned.requests[-1])


def test_one_slow_pane_does_not_disturb_its_neighbours(qapp: QApplication) -> None:
    """A struggling camera must not hold up the cameras beside it."""
    healthy = [DecodingPane() for _ in range(3)]
    struggling = DecodingPane(decode_ticks=5)
    panes = [*healthy, struggling]
    player, clock = _rigged_player(panes)

    _run(player, clock, panes, seconds=5.0)

    expected = int(np.floor(clock.state.t / INTERVAL + 1e-9))
    assert all(p.displayed_frame == expected for p in healthy)


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


# ── Painting reads a mirrored size, never a decoder ───────────────────


def test_the_overlay_scales_from_the_panes_mirrored_video_size(qapp: QApplication) -> None:
    """``paintEvent`` runs on the UI thread once per pane per frame.

    It must scale from the size the pane published at open, not by asking the
    decoder — which under libmpv took its core lock while the decode threads
    contended for it (26-34 us typical, 165 us at p99, once per pane per frame).
    The pane stand-in here has *only* ``video_size``, so a paint path that
    reaches for anything else fails rather than quietly costing that again.
    """
    from avialsync.ui.video_overlay import PaintCanvas

    canvas = PaintCanvas()
    pane = SimpleNamespace(video_size=(640, 360))
    canvas.setParent(None)
    canvas.parent = lambda: pane  # type: ignore[method-assign]
    canvas.resize(320, 240)

    scale, offset_x, offset_y = canvas._video_scale()

    assert scale == pytest.approx(0.5)
    assert offset_x == pytest.approx(0.0)
    assert offset_y == pytest.approx(30.0)


def test_the_overlay_and_the_video_surface_letterbox_identically(qapp: QApplication) -> None:
    """Two widgets draw into one cell; a divergence puts markers off their mark.

    The surface blits the frame and the canvas draws tracked points on top of
    it. They compute their geometry separately, so this pins them to the same
    answer rather than trusting that two copies of the formula stay equal.
    """
    from avialsync.ui.video_overlay import PaintCanvas
    from avialsync.ui.video_pane import VideoSurface

    surface = VideoSurface()
    surface.resize(320, 240)
    surface.set_frame(np.zeros((360, 640, 3), dtype=np.uint8))

    canvas = PaintCanvas()
    canvas.setParent(None)
    canvas.parent = lambda: SimpleNamespace(video_size=(640, 360))  # type: ignore[method-assign]
    canvas.resize(320, 240)

    image = surface._image
    assert image is not None
    surface_scale = min(surface.width() / image.width(), surface.height() / image.height())
    surface_offset_y = (surface.height() - image.height() * surface_scale) / 2.0

    scale, _, offset_y = canvas._video_scale()
    assert surface_scale == pytest.approx(scale)
    assert surface_offset_y == pytest.approx(offset_y)


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
    """Before a file is open there is nothing meaningful to scale to."""
    from avialsync.ui.video_overlay import PaintCanvas

    canvas = PaintCanvas()
    pane = SimpleNamespace(video_size=None)
    canvas.parent = lambda: pane  # type: ignore[method-assign]

    assert canvas._video_scale() is None
