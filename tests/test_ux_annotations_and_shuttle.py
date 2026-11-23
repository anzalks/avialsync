"""Tests for J/K/L shuttle, range annotations, draggable markers, and ethogram coding."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.commands import MoveMarkerCommand
from avialsync.core.document import Document
from avialsync.core.timeline import MasterClock
from avialsync.ui import ethogram_bar, recovery
from avialsync.ui.app_settings import app_settings
from avialsync.ui.ethogram_bar import EthogramSlot
from avialsync.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = app_settings()
    store.clear()
    store.sync()
    yield
    store.clear()
    store.sync()


@pytest.fixture(autouse=True)
def isolated_recovery_dir(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    yield target


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    if isValid(win):
        win.close()


def test_master_clock_reverse_direction_and_clamping() -> None:
    clock = MasterClock()
    clock.set_bounds(0.0, 10.0)
    clock.seek(5.0)
    assert clock.state.direction == 1

    clock.set_direction(-1)
    assert clock.state.direction == -1
    clock.set_rate(2.0)
    clock.play()
    clock.advance(10.0)  # anchor
    clock.advance(11.0)  # -2.0s
    assert clock.state.t == pytest.approx(3.0)

    clock.advance(13.0)  # -4.0s -> clamps to 0.0 and pauses
    assert clock.state.t == pytest.approx(0.0)
    assert not clock.state.playing

    clock.set_direction(1)
    assert clock.state.direction == 1


def test_jkl_shuttle_reverse_pause_and_forward_speed_steps(window: MainWindow) -> None:
    window.transport.set_bounds(0.0, 20.0)
    window.clock.set_bounds(0.0, 20.0)
    window.player.seek(10.0, exact=True)

    # Trigger J -> reverse at 1.0x
    window.transport.shuttle_reverse()
    assert window.clock.state.playing
    assert window.clock.state.direction == -1
    assert window.clock.state.rate == pytest.approx(1.0)

    # Second J -> reverse at 2.0x
    window.transport.shuttle_reverse()
    assert window.clock.state.direction == -1
    assert window.clock.state.rate == pytest.approx(2.0)

    # Trigger L while reversing -> switches to forward at 1.0x
    window.transport.shuttle_forward()
    assert window.clock.state.playing
    assert window.clock.state.direction == 1
    assert window.clock.state.rate == pytest.approx(1.0)

    # Second L -> forward at 2.0x
    window.transport.shuttle_forward()
    assert window.clock.state.rate == pytest.approx(2.0)

    # Trigger K -> pauses unconditionally and resets direction to +1
    window.transport.shuttle_pause()
    assert not window.clock.state.playing
    assert window.transport.direction == 1


def test_move_marker_command_headless_merge_and_labels() -> None:
    doc = Document()
    target = MagicMock()

    pt_cmd = MoveMarkerCommand(index=0, before=(1.0, None), after=(2.5, None))
    assert pt_cmd.label == "Move marker to 2.500 s"
    doc.execute(pt_cmd, target)
    target.set_marker_span.assert_called_with(0, 2.5, None)

    # Consecutive move on same marker merges
    pt_cmd2 = MoveMarkerCommand(index=0, before=(2.5, None), after=(3.2, None))
    doc.record(pt_cmd2)
    assert pt_cmd.merge_with("other") is None
    assert (
        pt_cmd.merge_with(MoveMarkerCommand(index=1, before=(0.0, None), after=(1.0, None))) is None
    )

    doc.undo(target)
    target.set_marker_span.assert_called_with(0, 1.0, None)

    rng_cmd = MoveMarkerCommand(index=1, before=(1.0, 2.0), after=(1.5, 3.5))
    assert rng_cmd.label == "Adjust range marker to 1.500–3.500 s"
    doc.execute(rng_cmd, target)
    target.set_marker_span.assert_called_with(1, 1.5, 3.5)


def test_mark_ab_range_prev_next_marker_and_undoable_span_move(window: MainWindow) -> None:
    window.transport.set_bounds(0.0, 20.0)
    window.clock.set_bounds(0.0, 20.0)
    window._refresh_action_availability()
    assert not window._act_mark_range.isEnabled()

    window.transport.set_ab_region(2.0, 5.5)
    window._refresh_action_availability()
    assert window._act_mark_range.isEnabled()
    assert window._act_mark_range.shortcut() == QKeySequence("Shift+M")

    window._act_mark_range.trigger()
    assert len(window.annotation_store.markers) == 1
    m = window.annotation_store.markers[0]
    assert (m.t_start, m.t_end) == pytest.approx((2.0, 5.5))

    # Add a point marker at 9.0s and navigate with Previous / Next Marker
    window.annotation_store.add_point(9.0, "poke")
    window.player.seek(0.5, exact=True)
    window._act_next_marker.trigger()
    assert window.clock.state.t == pytest.approx(2.0)
    window._act_next_marker.trigger()
    assert window.clock.state.t == pytest.approx(5.5)
    window._act_next_marker.trigger()
    assert window.clock.state.t == pytest.approx(9.0)
    window._act_prev_marker.trigger()
    assert window.clock.state.t == pytest.approx(5.5)

    # Move range marker and undo/redo via command bus
    window.annotation_store.set_span(0, 3.0, 6.0)
    assert (
        window.annotation_store.markers[0].t_start,
        window.annotation_store.markers[0].t_end,
    ) == (
        3.0,
        6.0,
    )
    assert window.document.undo(window._mutations)
    assert (
        window.annotation_store.markers[0].t_start,
        window.annotation_store.markers[0].t_end,
    ) == (
        2.0,
        5.5,
    )


def test_ethogram_point_and_bout_coding_focus_guard_and_changes_filter(
    window: MainWindow, qtbot
) -> None:
    window.transport.set_bounds(0.0, 30.0)
    window.clock.set_bounds(0.0, 30.0)
    bar = window.changes_panel.ethogram_bar
    bar.set_slots(
        [
            EthogramSlot(digit=1, label="Grooming", mode="bout"),
            EthogramSlot(digit=2, label="Lick", mode="point"),
        ]
    )

    # Typing digits inside timecode field must NOT trigger ethogram markers!
    window.transport._time_edit.setFocus()
    ethogram_bar.trigger_ethogram_slot(window, 2)
    assert len(window.annotation_store.markers) == 0

    # Move focus to playback surface and code a point + a bout
    window.transport.setFocus()
    window.player.seek(4.0, exact=True)
    ethogram_bar.trigger_ethogram_slot(window, 2)
    assert len(window.annotation_store.markers) == 1
    assert window.annotation_store.markers[0].label == "Lick"
    assert window.annotation_store.markers[0].t_end is None

    # Bout start at 6.0s, bout end at 10.5s
    window.player.seek(6.0, exact=True)
    ethogram_bar.trigger_ethogram_slot(window, 1)
    assert bar.active_bout_digits() == (1,)
    window.player.seek(10.5, exact=True)
    ethogram_bar.trigger_ethogram_slot(window, 1)
    assert bar.active_bout_digits() == ()
    assert len(window.annotation_store.markers) == 2
    bout = window.annotation_store.markers[1]
    assert bout.label == "Grooming"
    assert (bout.t_start, bout.t_end) == pytest.approx((6.0, 10.5))

    # Filter ChangesPanel by kind and search text
    panel = window.changes_panel
    assert len(panel.rows) == 2
    panel.kind_filter.setCurrentIndex(panel.kind_filter.findData("Range"))
    assert [r.label for r in panel.rows] == ["Grooming"]
    panel.kind_filter.setCurrentIndex(0)
    panel.search_edit.setText("lick")
    assert [r.label for r in panel.rows] == ["Lick"]
    panel.search_edit.clear()
    assert len(panel.rows) == 2
