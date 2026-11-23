"""Regression tests for session reset transient state, reset undo, and workspace layouts."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from avialsync.core.channel_reader import ChannelKey
from avialsync.core.pyramid import PyramidBuilder
from avialsync.ui import ethogram_bar, recovery, recovery_worker, workspaces
from avialsync.ui.annotations import VideoFrame
from avialsync.ui.app_settings import app_settings
from avialsync.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch) -> Iterator[MainWindow]:
    """Build an isolated MainWindow that never touches user QSettings or recovery files."""
    monkeypatch.setattr(recovery_worker, "start_recovery_check", lambda _w: None)
    monkeypatch.setattr(recovery, "clear_recovery", lambda: None)
    win = MainWindow()
    qtbot.addWidget(win)  # type: ignore[attr-defined]
    monkeypatch.setattr(win, "_save_geometry", lambda: None)
    monkeypatch.setattr(win, "_autosave_before_close", lambda: None)
    yield win
    win.close()


def _non_default_plot_mode(win: MainWindow) -> str:
    """Switch PlotPane to its non-stacked view mode and return that mode name."""
    for candidate in ("overlaid", "overlay"):
        win.plot_pane.set_view_mode(candidate)
        if win.plot_pane.view_mode == candidate:
            return candidate
    raise AssertionError(f"PlotPane rejected non-stacked modes; stayed {win.plot_pane.view_mode!r}")


def test_reset_session_clears_bouts_shuttle_ab_loop_and_suspect_cache(window: MainWindow) -> None:
    """Reset Session clears active ethogram bouts, reverse shuttle, rate, A-B loop, and suspects."""
    window._apply_bounds((0.0, 10.0))

    ethogram_bar.trigger_ethogram_slot(window, 1)
    assert window.changes_panel.ethogram_bar.active_bout_digits() == (1,)

    window.transport.shuttle_reverse()
    idx_4x = window.transport.rate_combo.findData(4.0)
    assert idx_4x >= 0
    window.transport.rate_combo.setCurrentIndex(idx_4x)
    window.transport.set_ab_region(1.0, 5.0)
    assert window.transport.direction == -1
    assert window.transport.rate_combo.currentData() == 4.0
    assert window.transport.ab_range() == (1.0, 5.0)

    _non_default_plot_mode(window)
    window._suspect_cache = (1, ["frame_0"])

    window._reset_session()

    assert window.changes_panel.ethogram_bar.active_bout_digits() == ()
    assert window.transport.direction == 1
    assert window.transport.rate_combo.currentData() == 1.0
    assert window.transport.ab_range() is None
    assert window.plot_pane.view_mode == "stacked"
    assert window._suspect_cache is None


def test_identity_swap_change_invalidates_suspect_cache(window: MainWindow) -> None:
    """Accepting or undoing an identity swap drops any cached suspect frames."""
    window._suspect_cache = (1, ["cached"])
    window._on_identity_swaps_changed("pose.csv")
    assert window._suspect_cache is None


def test_undo_after_reset_session_restores_marker_video_frames_and_view_3d(
    window: MainWindow,
) -> None:
    """Undoing Reset Session restores point marker VideoFrame snapshots and 3D orientation."""
    vf = VideoFrame(path="/tmp/cam0.mp4", frame_index=42, media_timestamp=1.4)
    window.annotation_store.add_point(1.4, "touch", video_frames=[vf])
    assert len(window.annotation_store.markers) == 1
    assert window.annotation_store.markers[0].video_frames == [vf]

    window.tracking_3d_pane.set_view_orientation(
        {"azimuth": 42.0, "elevation": 28.0, "zoom": 1.5, "distance": 5.0},
        defer_until_loaded=True,
    )
    expected_view = window.tracking_3d_pane.view_orientation()
    assert expected_view

    window._reset_session()
    assert window.annotation_store.markers == []
    assert window.tracking_3d_pane.view_orientation() != expected_view

    window.document.undo(window._mutations)

    assert len(window.annotation_store.markers) == 1
    restored = window.annotation_store.markers[0]
    assert restored.label == "touch"
    assert restored.t_start == pytest.approx(1.4)
    assert restored.t_end is None
    assert restored.video_frames == [vf]
    assert window.tracking_3d_pane.view_orientation() == expected_view


def test_workspace_round_trips_plot_view_mode_and_pinned_channels(
    window: MainWindow,
    tmp_path: Path,
) -> None:
    """Workspace capture/save/load/apply round-trips plot_view_mode and pinned_channels."""
    store = app_settings()
    store.remove("workspaces/audit_layout")

    cache_dir = tmp_path / "imu_cache"
    cache_dir.mkdir()
    times = np.linspace(0.0, 5.0, 51)
    PyramidBuilder(cache_dir, "acc_x").build_and_save(times, np.sin(times))
    PyramidBuilder(cache_dir, "acc_y").build_and_save(times, np.cos(times))
    src_id = "/tmp/imu.csv"
    window.plot_pane.set_timeline_bounds(0.0, 5.0)
    window.plot_pane.load_channels(cache_dir, ["acc_x", "acc_y"], source_id=src_id)
    window.plot_pane.wait_for_pending_rows()
    window.plot_pane.set_channel_pinned(ChannelKey(src_id, "acc_x"), True)
    target_mode = _non_default_plot_mode(window)

    captured = workspaces.capture(window)
    assert captured.plot_view_mode == target_mode
    assert captured.pinned_channels == ((src_id, "acc_x"),)

    workspaces.save("audit_layout", captured)

    window.plot_pane.set_view_mode("stacked")
    window.plot_pane.set_channel_pinned(ChannelKey(src_id, "acc_x"), False)
    window.plot_pane.set_channel_pinned(ChannelKey(src_id, "acc_y"), True)

    loaded = workspaces.load("audit_layout")
    assert loaded is not None
    assert loaded.plot_view_mode == target_mode
    assert loaded.pinned_channels == ((src_id, "acc_x"),)

    window.plot_pane.set_channel_pinned(ChannelKey(src_id, "acc_y"), False)
    workspaces.apply(window, loaded)
    assert window.plot_pane.view_mode == target_mode
    by_name = {ch.name: ch for ch in window.plot_pane.channels}
    assert by_name["acc_x"].pinned is True
    assert by_name["acc_y"].pinned is False
