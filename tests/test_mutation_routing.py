"""Every listed mutation reaches the command bus (WP-1 step 4, D-087).

WP-1 originally shipped the bus, the commands, and the `[*]` title without
wiring a single mutation to any of them, so `document.is_dirty` was permanently
False in the running application and the modified marker was dead code. These
tests exist so that cannot happen quietly again: each one drives the widget a
user drives and asserts the session notices.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from avialsync.core.commands import (
    AddMarkerCommand,
    RelabelMarkerCommand,
    RemoveMarkerCommand,
    RemoveSourceCommand,
    ResetSessionCommand,
    SetChannelVisibleCommand,
    SetSourceMappingCommand,
    SetSourceVisibleCommand,
)
from avialsync.core.document import MutationTarget
from avialsync.ui import recovery
from avialsync.ui.main_window import MainWindow


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
    # Qt may already have deleted it: pytest-qt runs processEvents()
    # after the call phase, which executes pending deleteLater()s.
    if isValid(win):
        win.close()


class _StubPane(QWidget):
    """A pane with the one attribute the grid and session writer reach for.

    A bare ``QWidget`` is not enough: ``video_grid.set_offset`` assigns through
    ``pane.time_map``, and ``build_session_state`` reads its offset and drift on
    every save and recovery write.
    """

    def __init__(self) -> None:
        super().__init__()
        from avialsync.core.timeline import TimeMap

        self.time_map = TimeMap()

    def has_footage_at_master(self, t_master: float) -> bool:  # pragma: no cover - stub
        """Asked by the player whenever pane visibility changes."""
        return True

    def set_has_footage(self, has_footage: bool) -> None:  # pragma: no cover - stub
        """Told by the player straight after the question above."""

    #: The seeker skips a pane with no media, which is what keeps this stub out
    #: of the decode path entirely.
    has_media = False


def _fake_video(window: MainWindow, path: str = "/tmp/cam1.mp4") -> str:
    """Register a video in the sidebar and grid without decoding anything."""
    window.sidebar.add_video(path, {})
    window.video_grid.panes.append(_StubPane())
    window.video_grid._paths.append(path)
    window.video_grid._pane_enabled.append(True)
    return path


def _last(window: MainWindow):
    return list(window.document)[-1]


# ── the adapter honours the protocol ─────────────────────────────────


def test_the_window_target_satisfies_the_protocol(window: MainWindow) -> None:
    assert isinstance(window._mutations, MutationTarget)


# ── the defect this package fixes ────────────────────────────────────


def test_an_edit_makes_the_session_dirty(window: MainWindow) -> None:
    """WP-1 shipped without this: is_dirty was permanently False."""
    assert window.document.is_dirty is False
    window.annotation_store.add_point(1.0, "spike")
    assert window.document.is_dirty is True


def test_an_edit_shows_the_modified_marker(window: MainWindow) -> None:
    window._update_window_title()
    assert window.isWindowModified() is False
    window.annotation_store.add_point(1.0, "spike")
    assert window.isWindowModified() is True, "[*] must appear once something changed"


# ── annotations ──────────────────────────────────────────────────────


def test_adding_a_marker_is_recorded(window: MainWindow) -> None:
    window.annotation_store.add_point(1.0, "spike")
    assert isinstance(_last(window), AddMarkerCommand)


def test_adding_a_range_marker_is_recorded(window: MainWindow) -> None:
    window.annotation_store.add_range(1.0, 2.0, "burst")
    assert isinstance(_last(window), AddMarkerCommand)


def test_deleting_a_marker_is_recorded_and_reversible(window: MainWindow) -> None:
    window.annotation_store.add_point(1.0, "spike")
    window.annotation_store.remove(0)
    assert isinstance(_last(window), RemoveMarkerCommand)
    assert window.annotation_store.markers == []

    window.document.undo(window._mutations)
    labels = [m.label for m in window.annotation_store.markers]
    assert labels == ["spike"], "undo must bring the marker back"


def test_an_undone_deletion_keeps_the_original_marker(window: MainWindow) -> None:
    """Rebuilding from a record would drop colour index and frame snapshots."""
    window.annotation_store.add_point(1.0, "spike")
    original = window.annotation_store.markers[0]
    window.annotation_store.remove(0)
    window.document.undo(window._mutations)

    restored = window.annotation_store.markers[0]
    assert restored is original
    assert restored.color_index == original.color_index


def test_renaming_a_marker_is_recorded_and_reversible(window: MainWindow) -> None:
    window.annotation_store.add_point(1.0, "spike")
    window.annotation_store.set_label(0, "burst")
    assert isinstance(_last(window), RelabelMarkerCommand)

    window.document.undo(window._mutations)
    assert window.annotation_store.markers[0].label == "spike"


def test_renaming_to_the_same_label_records_nothing(window: MainWindow) -> None:
    window.annotation_store.add_point(1.0, "spike")
    depth = len(window.document)
    window.annotation_store.set_label(0, "spike")
    assert len(window.document) == depth


# ── offsets and drift ────────────────────────────────────────────────


def test_a_video_offset_change_is_recorded(window: MainWindow) -> None:
    path = _fake_video(window)
    window._on_video_offset_changed(path, 1.25)
    command = _last(window)
    assert isinstance(command, SetSourceMappingCommand)
    assert command.after == (1.25, 0.0)
    assert "cam1.mp4" in command.label


def test_a_video_offset_drag_is_one_undo_step(window: MainWindow) -> None:
    """200 valueChanged steps must not become 200 entries (WP-1 step 6)."""
    path = _fake_video(window)
    depth = len(window.document)
    for step in range(200):
        window._on_video_offset_changed(path, (step + 1) * 0.01)
    assert len(window.document) - depth == 1


def test_a_sensor_mapping_change_is_recorded(window: MainWindow, tmp_path) -> None:
    path = "/tmp/sensor.csv"
    window.sidebar.add_sensor(path, ["force"])
    window._sensor_cache_dirs[path] = tmp_path / "sensor.avialcache"

    window._on_sensor_mapping_changed(path, 0.5, 12.0)
    command = _last(window)
    assert isinstance(command, SetSourceMappingCommand)
    assert command.after == (0.5, 12.0)


def test_a_mapping_change_to_the_same_value_records_nothing(window: MainWindow) -> None:
    path = _fake_video(window)
    window._on_video_offset_changed(path, 1.0)
    depth = len(window.document)
    window._on_video_offset_changed(path, 1.0)
    assert len(window.document) == depth


# ── visibility ───────────────────────────────────────────────────────


def test_hiding_a_video_is_recorded_and_reversible(window: MainWindow) -> None:
    path = _fake_video(window)
    window._on_video_visibility_changed(path, False)
    command = _last(window)
    assert isinstance(command, SetSourceVisibleCommand)
    assert command.visible is False

    window.document.undo(window._mutations)
    widget = window.sidebar._video_widgets[path]
    assert widget.visibility_cb.isChecked() is True, "undo must move the checkbox back"


def test_hiding_a_channel_is_recorded(window: MainWindow) -> None:
    window._on_channel_visibility_changed("/tmp/sensor.csv", "force", False)
    command = _last(window)
    assert isinstance(command, SetChannelVisibleCommand)
    assert command.channel == "force"


# ── sources ──────────────────────────────────────────────────────────


def test_removing_a_video_is_recorded(window: MainWindow) -> None:
    path = _fake_video(window)
    window.document.clear()
    window._on_video_remove_requested(path)
    assert isinstance(_last(window), RemoveSourceCommand)


def test_removing_a_sensor_is_recorded(window: MainWindow, tmp_path) -> None:
    path = "/tmp/sensor.csv"
    window.sidebar.add_sensor(path, ["force"])
    window._sensor_cache_dirs[path] = tmp_path / "sensor.avialcache"
    window.document.clear()

    window._on_sensor_remove_requested(path)
    assert isinstance(_last(window), RemoveSourceCommand)


# ── reset session ────────────────────────────────────────────────────


def test_reset_session_is_recorded_with_its_snapshot(window: MainWindow) -> None:
    """One click clears every pane and annotation; it must be reversible."""
    _fake_video(window)
    window.annotation_store.add_point(1.0, "spike")

    window._reset_session()

    command = _last(window)
    assert isinstance(command, ResetSessionCommand)
    assert command.snapshot is not None, "the pre-reset workspace must be captured"
    assert window.annotation_store.markers == []


def test_undoing_a_reset_restores_the_annotations(window: MainWindow) -> None:
    window.annotation_store.add_point(1.0, "spike")
    window.annotation_store.add_point(2.0, "burst")
    window._reset_session()
    assert window.annotation_store.markers == []

    window.document.undo(window._mutations)
    labels = [m.label for m in window.annotation_store.markers]
    assert labels == ["spike", "burst"]


# ── the replay guard ─────────────────────────────────────────────────


def test_undo_does_not_record_itself(window: MainWindow) -> None:
    """Without the guard, replaying re-emits and the stack never unwinds."""
    path = _fake_video(window)
    window._on_video_offset_changed(path, 1.0)
    depth = len(window.document)

    window.document.undo(window._mutations)

    assert len(window.document) == depth - 1, "undo must shorten the log, not extend it"


def test_undo_then_redo_returns_the_value(window: MainWindow) -> None:
    path = _fake_video(window)
    window._on_video_offset_changed(path, 2.5)

    window.document.undo(window._mutations)
    assert window.sidebar.video_offset(path) == pytest.approx(0.0)

    window.document.redo(window._mutations)
    assert window.sidebar.video_offset(path) == pytest.approx(2.5)


def test_the_guard_is_restored_after_an_exception(window: MainWindow) -> None:
    """A raising command must not leave recording permanently suppressed."""
    with pytest.raises(RuntimeError):
        with window._mutations.replaying():
            raise RuntimeError("boom")
    assert window._recording_suspended is False


# ── session restore is not an edit ───────────────────────────────────


def test_a_restored_session_is_not_dirty(window: MainWindow) -> None:
    """A freshly loaded session coming up dirty would be a false alarm."""
    from avialsync.core.session import SessionState

    window._session_restoring = True
    window._note_source_loaded("/tmp/cam1.mp4", "video")

    assert window.document.is_dirty is False
    assert window._session_restoring is False, "the restore finished once queues drained"

    assert isinstance(SessionState(), SessionState)


def test_saving_clears_dirty(window: MainWindow, tmp_path) -> None:
    window.annotation_store.add_point(1.0, "spike")
    assert window.document.is_dirty is True

    window._session_path = Path(tmp_path / "s.avv")
    window._mark_session_saved()

    assert window.document.is_dirty is False
    assert window.isWindowModified() is False
