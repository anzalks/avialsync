"""Tests for live scrubbing coalescing behaviour in Player."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def player_with_mocks():
    """Return a Player wired to mock collaborators (no Qt event loop needed)."""
    from PySide6.QtCore import QObject

    from avialsync.core.timeline import MasterClock
    from avialsync.engine.player import Player
    from avialsync.ui.plot_pane import PlotPane
    from avialsync.ui.transport import Transport
    from avialsync.ui.video_grid import VideoGrid

    qapp_obj = QObject()  # keep Qt alive

    clock = MasterClock()
    clock.set_bounds(0.0, 10.0)

    video_grid = MagicMock(spec=VideoGrid)
    video_grid.panes = []
    video_grid.visible_panes.side_effect = lambda: list(video_grid.panes)
    video_grid.displayed_panes_changed = MagicMock()
    video_grid.displayed_panes_changed.connect = MagicMock()

    plot_pane = MagicMock(spec=PlotPane)
    transport = MagicMock(spec=Transport)
    # Prevent real signal connections from firing
    transport.play_toggled = MagicMock()
    transport.play_toggled.connect = MagicMock()
    transport.seek_requested = MagicMock()
    transport.seek_requested.connect = MagicMock()
    transport.rate_changed = MagicMock()
    transport.rate_changed.connect = MagicMock()
    transport.frame_step_requested = MagicMock()
    transport.frame_step_requested.connect = MagicMock()
    transport.ab_loop_changed = MagicMock()
    transport.ab_loop_changed.connect = MagicMock()

    player = Player(clock, video_grid, plot_pane, transport, qapp_obj)

    # Patch seeker so we control is_settled() and track seek() calls
    player.seeker = MagicMock()
    player.seeker.panes = []

    yield player, clock

    player._timer.stop()


def test_coalesce_when_seeker_busy(player_with_mocks):
    """During drag with seeker busy: only the latest target is remembered."""
    player, clock = player_with_mocks

    # Seeker appears busy for all calls
    player.seeker.is_settled.return_value = False

    seek_calls = []
    player.seeker.seek.side_effect = lambda t, exact: seek_calls.append((t, exact))

    # Simulate 5 sliderMoved events (all non-exact)
    for t in [1.0, 2.0, 3.0, 4.0, 5.0]:
        player.seek(t, exact=False)

    # Seeker.seek should NOT have been called during the busy period
    assert seek_calls == [], f"Expected no dispatches while busy, got: {seek_calls}"

    # Only the last target should be pending
    assert player._pending_scrub_t == 5.0


def test_dispatch_immediately_when_seeker_free(player_with_mocks):
    """Keyframe seek dispatches immediately when seeker is already settled."""
    player, clock = player_with_mocks

    player.seeker.is_settled.return_value = True

    dispatched = []
    player.seeker.seek.side_effect = lambda t, exact: dispatched.append((t, exact))

    player.seek(2.5, exact=False)

    assert dispatched == [(2.5, False)]
    assert player._pending_scrub_t is None


def test_exact_seek_always_dispatches(player_with_mocks):
    """Exact seek (on release) always dispatches regardless of seeker state."""
    player, clock = player_with_mocks

    player.seeker.is_settled.return_value = False  # busy

    dispatched = []
    player.seeker.seek.side_effect = lambda t, exact: dispatched.append((t, exact))

    player.seek(7.0, exact=True)

    assert dispatched == [(7.0, True)]
    assert player._pending_scrub_t is None


def test_pending_flushed_in_on_tick(player_with_mocks):
    """_on_tick dispatches the pending scrub target once seeker settles."""
    player, clock = player_with_mocks

    # First call: busy — stores pending
    player.seeker.is_settled.return_value = False
    player.seek(3.0, exact=False)
    assert player._pending_scrub_t == 3.0

    dispatched = []
    player.seeker.seek.side_effect = lambda t, exact: dispatched.append((t, exact))

    # Now seeker becomes free
    player.seeker.is_settled.return_value = True
    player._on_tick()

    assert dispatched == [(3.0, False)]
    assert player._pending_scrub_t is None


def test_pending_not_flushed_while_busy(player_with_mocks):
    """_on_tick does NOT flush while seeker is still busy."""
    player, clock = player_with_mocks

    player.seeker.is_settled.return_value = False
    player.seek(3.0, exact=False)

    dispatched = []
    player.seeker.seek.side_effect = lambda t, exact: dispatched.append((t, exact))

    # Tick with seeker still busy
    player._on_tick()

    assert dispatched == []
    assert player._pending_scrub_t == 3.0


def test_busy_video_seek_never_freezes_master_timeline(player_with_mocks, monkeypatch):
    """A stalled decoder may drop frames but cannot stop plots or 3D."""
    player, clock = player_with_mocks
    player.seeker.is_settled.return_value = False
    clock.play()
    clock.advance(100.0)
    from itertools import cycle

    monotonic_times = cycle(100.0 + step / 60.0 for step in range(1, 121))
    monkeypatch.setattr(
        "avialsync.engine.player.time.monotonic",
        lambda: next(monotonic_times),
    )

    for _ in range(120):
        player._on_tick()

    assert clock.state.t == pytest.approx(2.0, abs=1e-6)
    assert player.plot_pane.set_cursor.call_count == 120


def test_release_clears_pending(player_with_mocks):
    """Exact seek on release clears any pending coalesced target."""
    player, clock = player_with_mocks

    player.seeker.is_settled.return_value = False
    player.seek(3.0, exact=False)
    assert player._pending_scrub_t == 3.0

    player.seeker.is_settled.return_value = True
    player.seek(3.0, exact=True)

    assert player._pending_scrub_t is None


def test_readout_updated_during_drag(player_with_mocks):
    """readout_panel.set_cursor is called on every seek, including non-exact."""
    player, clock = player_with_mocks

    readout = MagicMock()
    player._readout_panel = readout
    player.seeker.is_settled.return_value = True

    player.seek(4.0, exact=False)

    readout.set_cursor.assert_called_once()
    args = readout.set_cursor.call_args[0]
    assert abs(args[0] - 4.0) < 1e-9


def test_seek_hides_and_skips_video_panes_without_master_time_coverage(player_with_mocks):
    """Out-of-range panes show No Footage and are never asked to seek a stale frame."""
    player, _clock = player_with_mocks
    active = MagicMock()
    active.has_footage_at_master.return_value = True
    inactive = MagicMock()
    inactive.has_footage_at_master.return_value = False
    player.video_grid.panes = [active, inactive]
    player.seeker.is_settled.return_value = True

    player.seek(5.0, exact=True)

    active.set_has_footage.assert_called_once_with(True)
    inactive.set_has_footage.assert_called_once_with(False)
    inactive.pause.assert_called_once()
    assert player.seeker.panes == [active]
    player.seeker.seek.assert_called_once_with(5.0, exact=True)


def test_hidden_video_is_excluded_from_seek_and_playback(player_with_mocks):
    """Unchecked videos stay loaded but consume no decoder synchronization work."""
    player, _clock = player_with_mocks
    visible = MagicMock()
    visible.has_footage_at_master.return_value = True
    hidden = MagicMock()
    player.video_grid.panes = [visible, hidden]
    player.video_grid.visible_panes.side_effect = lambda: [visible]
    player._playing_pane_ids.add(id(hidden))
    player.seeker.is_settled.return_value = True

    player.seek(3.0, exact=True)

    hidden.pause.assert_called_once()
    hidden.has_footage_at_master.assert_not_called()
    assert player.seeker.panes == [visible]


def test_newly_displayed_video_alone_is_resynchronized(player_with_mocks):
    """Showing one pane must not re-seek every already-visible camera."""
    player, _clock = player_with_mocks
    first = MagicMock()
    first.has_footage_at_master.return_value = True
    second = MagicMock()
    second.has_footage_at_master.return_value = True
    second.time_map.to_source.return_value = 3.0
    player.video_grid.panes = [first, second]
    player.video_grid.visible_panes.side_effect = lambda: [first, second]
    player._displayed_pane_ids = {id(first)}

    player._on_displayed_panes_changed()

    player.seeker.seek_pane.assert_called_once_with(second, 3.0, exact=True)


def test_play_starts_playback_for_programmatic_callers(player_with_mocks):
    """The demo launcher's public play call delegates to the normal UI path."""
    player, _clock = player_with_mocks
    player.set_playing = MagicMock()

    player.play()

    player.set_playing.assert_called_once_with(True)


def test_3d_tracking_updated_during_drag(player_with_mocks):
    """The 3D view follows the same master time during live scrubbing."""
    player, _clock = player_with_mocks

    tracking_3d = MagicMock()
    player.tracking_3d_pane = tracking_3d
    player.seeker.is_settled.return_value = True

    player.seek(4.25, exact=False)

    tracking_3d.set_cursor.assert_called_once_with(4.25)


def test_exact_scrub_snaps_master_clock_to_accepted_frame_trigger(player_with_mocks):
    """Releasing the scrubber selects an evidence-backed frame boundary."""
    player, clock = player_with_mocks
    pane = MagicMock()
    pane.has_footage_at_master.return_value = True
    pane.time_map.has_exact_mapping = True
    pane.time_map.snap_master_time.return_value = 4.2
    player.video_grid.panes = [pane]
    player.seeker.is_settled.return_value = True

    player.seek(4.19, exact=True)

    assert clock.state.t == pytest.approx(4.2)
    player.seeker.seek.assert_called_once_with(4.2, exact=True)


def test_frame_step_uses_timestamp_target_without_fixed_delay(player_with_mocks):
    """Frame stepping seeks from the reference pane's real timestamp index immediately."""
    player, _clock = player_with_mocks
    pane = MagicMock()
    pane.has_footage_at_master.return_value = True
    pane.frame_step_master_target.return_value = 1.133
    player.video_grid.panes = [pane]
    player.seek = MagicMock()

    player.step_frame(1)

    pane.frame_step_master_target.assert_called_once()
    player.seek.assert_called_once_with(1.133, exact=True)


def test_frame_step_does_nothing_without_a_timestamp_table(player_with_mocks):
    """A pane with no decoded timestamps has no next frame to name.

    There is no fallback to a decoder's own frame-step command any more, and
    there must not be one: an opened pane always has its presentation
    timestamps, so a missing target means there is nothing open — and stepping
    by ``1/fps`` instead would invent a frame boundary that VFR and
    dropped-exposure footage do not have (D-007).
    """
    player, _clock = player_with_mocks
    pane = MagicMock()
    pane.has_footage_at_master.return_value = True
    pane.frame_step_master_target.return_value = None
    player.video_grid.panes = [pane]
    player.seek = MagicMock()

    player.step_frame(-1)

    player.seek.assert_not_called()
