"""The 60 Hz tick keeps authoritative time but does not repaint everything.

P3.5 P1 hot path.  Formatting every readout label and resampling a 128-point
pose sixty times a second costs more than a person can read, and timeline
evidence paint used to scan every event on every frame.  Authoritative time
still advances at 60 Hz; presentation is rate-limited, hidden consumers are
skipped, and event lanes are indexed by time.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from avialview.engine import player as player_module
from avialview.engine.player import _PRESENTATION_INTERVAL_S, Player
from avialview.ui.transport import TimelineOverview


@pytest.fixture
def rigged_player(qapp: QApplication) -> tuple[Player, MagicMock, MagicMock, MagicMock]:
    """A Player whose observers are all mocks, so calls can be counted."""
    clock = MagicMock()
    clock.state.t = 0.0
    plot_pane = MagicMock()
    transport = MagicMock()
    readout = MagicMock()
    readout.isVisible.return_value = True
    pose = MagicMock()
    pose.isVisible.return_value = True

    player = Player.__new__(Player)
    player.plot_pane = plot_pane
    player.transport = transport
    player.tracking_3d_pane = pose
    player._readout_panel = readout
    player._last_presentation_at = 0.0
    return player, plot_pane, readout, pose


# ── Rate limiting ─────────────────────────────────────────────────────


def test_cursor_and_seek_bar_see_every_tick(rigged_player) -> None:
    """Authoritative time must not be throttled — only presentation is."""
    player, plot_pane, _readout, _pose = rigged_player

    for step in range(60):
        player._update_timeline_views(step / 60.0, now=step / 60.0)

    assert plot_pane.set_cursor.call_count == 60


def test_readout_is_rate_limited_below_the_tick_rate(rigged_player) -> None:
    player, _plot, readout, _pose = rigged_player

    # One simulated second of 60 Hz ticks.
    for step in range(60):
        player._update_timeline_views(step / 60.0, now=step / 60.0)

    expected_max = int(1.0 / _PRESENTATION_INTERVAL_S) + 1
    assert readout.set_cursor.call_count <= expected_max
    assert readout.set_cursor.call_count >= 1


def test_forced_update_bypasses_the_rate_limit(rigged_player) -> None:
    """A seek or pause must show a truthful readout immediately."""
    player, _plot, readout, _pose = rigged_player

    player._update_timeline_views(0.0, now=0.0, force=True)
    player._update_timeline_views(0.001, now=0.001, force=True)
    player._update_timeline_views(0.002, now=0.002, force=True)

    assert readout.set_cursor.call_count == 3


def test_presentation_never_samples_the_clock_itself(rigged_player, monkeypatch) -> None:
    """Sampling monotonic here would perturb the tick's own drift accounting."""
    player, _plot, _readout, _pose = rigged_player
    monkeypatch.setattr(
        player_module.time,
        "monotonic",
        lambda: pytest.fail("_update_timeline_views must use the caller's timestamp"),
    )

    player._update_timeline_views(1.0, now=1.0)


# ── Hidden consumers ──────────────────────────────────────────────────


def test_a_hidden_readout_is_not_formatted(rigged_player) -> None:
    player, _plot, readout, _pose = rigged_player
    readout.isVisible.return_value = False

    for step in range(60):
        player._update_timeline_views(step / 60.0, now=step)

    readout.set_cursor.assert_not_called()


def test_a_hidden_pose_view_is_not_resampled(rigged_player) -> None:
    player, _plot, _readout, pose = rigged_player
    pose.isVisible.return_value = False

    for step in range(60):
        player._update_timeline_views(step / 60.0, now=step)

    pose.set_cursor.assert_not_called()


def test_an_absent_pose_view_is_tolerated(rigged_player) -> None:
    player, _plot, _readout, _pose = rigged_player
    player.tracking_3d_pane = None

    player._update_timeline_views(1.0, now=1.0, force=True)


# ── Timeline evidence indexing ────────────────────────────────────────


@pytest.fixture
def overview(qapp: QApplication, qtbot) -> TimelineOverview:
    widget = TimelineOverview()
    qtbot.addWidget(widget)
    widget.resize(800, 120)
    widget.set_bounds(0.0, 100.0)
    return widget


def test_events_are_stored_sorted_for_binary_search(overview: TimelineOverview) -> None:
    overview.set_ttl_events([5.0, 1.0, 3.0])

    assert [time for time, _ in overview._ttl_events] == [1.0, 3.0, 5.0]
    assert np.all(np.diff(overview._event_times["ttl"]) > 0)


def test_visible_columns_are_bounded_by_pixels_not_event_count(
    overview: TimelineOverview,
) -> None:
    """100 000 events inside the window must collapse to at most one per column."""
    overview.set_gap_events(list(np.linspace(0.0, 100.0, 100_000)))

    columns = overview._visible_event_x("gap", 0.0, 100.0)

    assert len(columns) <= overview.width()
    assert len(columns) == len(set(columns))


def test_only_events_inside_the_window_are_drawn(overview: TimelineOverview) -> None:
    overview.set_ttl_events([1.0, 50.0, 99.0])

    inside = overview._visible_event_x("ttl", 40.0, 60.0)
    everything = overview._visible_event_x("ttl", 0.0, 100.0)

    assert len(inside) == 1
    assert len(everything) == 3


def test_an_empty_lane_yields_no_columns(overview: TimelineOverview) -> None:
    assert overview._visible_event_x("ttl", 0.0, 100.0) == []


def test_nearest_event_lookup_finds_the_closest_within_tolerance(
    overview: TimelineOverview,
) -> None:
    overview.set_gap_events([(10.0, "gap A"), (20.0, "gap B")])

    assert overview._nearest_event("gap", 19.9, tolerance=0.5) == (20.0, "gap B")
    assert overview._nearest_event("gap", 10.2, tolerance=0.5) == (10.0, "gap A")


def test_nearest_event_lookup_respects_tolerance(overview: TimelineOverview) -> None:
    overview.set_gap_events([(10.0, "gap A")])

    assert overview._nearest_event("gap", 15.0, tolerance=0.5) is None


def test_nearest_event_lookup_on_an_empty_lane_is_none(overview: TimelineOverview) -> None:
    assert overview._nearest_event("ttl", 1.0, tolerance=1.0) is None
