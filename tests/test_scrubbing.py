"""Tests for live scrubbing coalescing behaviour in Player."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def player_with_mocks():
    """Return a Player wired to mock collaborators (no Qt event loop needed)."""
    from PySide6.QtCore import QObject

    from kinochronix.core.timeline import MasterClock
    from kinochronix.engine.player import Player
    from kinochronix.ui.plot_pane import PlotPane
    from kinochronix.ui.transport import Transport
    from kinochronix.ui.video_grid import VideoGrid

    qapp_obj = QObject()  # keep Qt alive

    clock = MasterClock()
    clock.set_bounds(0.0, 10.0)

    video_grid = MagicMock(spec=VideoGrid)
    video_grid.panes = []

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

    return player, clock


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


def test_play_starts_playback_for_programmatic_callers(player_with_mocks):
    """The demo launcher's public play call delegates to the normal UI path."""
    player, _clock = player_with_mocks
    player.set_playing = MagicMock()

    player.play()

    player.set_playing.assert_called_once_with(True)
