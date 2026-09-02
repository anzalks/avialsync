"""Undo and the Edit menu (WP-2, D-097).

There is one undo stack, not two: the Edit menu drives
:class:`~avialsync.core.document.Document` directly rather than mirroring it
into a ``QUndoStack``. These tests hold that boundary, and check the parts a
user actually experiences -- that the menu says what it will undo, that it is
disabled when there is nothing to undo, and that destructive actions come back.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QWidget

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
    win.close()


class _StubPane(QWidget):
    def __init__(self) -> None:
        super().__init__()
        from avialsync.core.timeline import TimeMap

        self.time_map = TimeMap()

    has_media = False

    def has_footage_at_master(self, t_master: float) -> bool:  # pragma: no cover - stub
        return True

    def set_has_footage(self, has_footage: bool) -> None:  # pragma: no cover - stub
        pass


def _fake_video(window: MainWindow, path: str = "/tmp/cam1.mp4") -> str:
    window.sidebar.add_video(path, {})
    window.video_grid.panes.append(_StubPane())
    window.video_grid._paths.append(path)
    window.video_grid._pane_enabled.append(True)
    return path


# ── the menu exists at all ───────────────────────────────────────────


def test_there_is_an_edit_menu(window: MainWindow) -> None:
    """Its absence was a visible platform-conventions violation on macOS."""
    titles = [action.text() for action in window.menuBar().actions()]
    assert "Edit" in titles


def test_the_edit_menu_offers_undo_and_redo(window: MainWindow) -> None:
    # Through the retained attribute rather than `menuBar().actions()`: the
    # wrapper reached that way can outlive its C++ object, which is the reason
    # the menu is held on the window in the first place.
    labels = [action.text() for action in window._edit_menu.actions()]
    assert any(label.startswith("Undo") for label in labels)
    assert any(label.startswith("Redo") for label in labels)


def test_redo_accepts_both_conventions(window: MainWindow) -> None:
    """Ctrl+Shift+Z is standard; Ctrl+Y is what a Windows user reaches for."""
    sequences = [s.toString() for s in window._undo_actions.redo_action.shortcuts()]
    assert any("Y" in s for s in sequences)
    assert any("Z" in s for s in sequences)


def test_shortcuts_dialog_lists_the_edit_actions(window: MainWindow) -> None:
    """The dialog derives from live QActions (D-022.6); Edit must reach it."""
    edit_actions = [a for a in window._all_actions if str(a.property("av_category")) == "Edit"]
    verbs = {a.text().split()[0] for a in edit_actions}
    assert {"Undo", "Redo"} <= verbs


# ── enablement and labelling ─────────────────────────────────────────


def test_undo_is_disabled_with_no_history(window: MainWindow) -> None:
    assert window._undo_actions.undo_action.isEnabled() is False
    assert window._undo_actions.redo_action.isEnabled() is False


def test_undo_names_what_it_will_reverse(window: MainWindow) -> None:
    """ "Undo" alone tells the user nothing about what is about to happen."""
    window.annotation_store.add_point(1.0, "spike")
    assert window._undo_actions.undo_action.isEnabled() is True
    assert window._undo_actions.undo_action.text() == "Undo Add marker 'spike'"


def test_redo_names_what_it_will_reapply(window: MainWindow) -> None:
    window.annotation_store.add_point(1.0, "spike")
    window._undo_actions.undo_action.trigger()
    assert window._undo_actions.redo_action.text() == "Redo Add marker 'spike'"


def test_labels_update_on_a_second_edit(window: MainWindow) -> None:
    """A second edit while already dirty crosses no dirty transition at all."""
    window.annotation_store.add_point(1.0, "spike")
    window.annotation_store.add_point(2.0, "burst")
    assert window._undo_actions.undo_action.text() == "Undo Add marker 'burst'"


def test_an_offset_label_names_the_file_and_value(window: MainWindow) -> None:
    path = _fake_video(window)
    window._on_video_offset_changed(path, 1.24)
    assert window._undo_actions.undo_action.text() == "Undo Set offset for cam1.mp4 to 1.240 s"


# ── the menu actually works ──────────────────────────────────────────


def test_triggering_undo_reverses_the_edit(window: MainWindow) -> None:
    window.annotation_store.add_point(1.0, "spike")
    window._undo_actions.undo_action.trigger()
    assert window.annotation_store.markers == []


def test_triggering_redo_reapplies_it(window: MainWindow) -> None:
    window.annotation_store.add_point(1.0, "spike")
    window._undo_actions.undo_action.trigger()
    window._undo_actions.redo_action.trigger()
    assert [m.label for m in window.annotation_store.markers] == ["spike"]


def test_undo_reopens_a_deleted_source(window: MainWindow, monkeypatch) -> None:
    """Removal is undoable rather than confirmed -- undo is the better answer.

    The reload is asynchronous and goes through the loader registry, so this
    asserts that undo starts it rather than waiting for a pane: with a path that
    names no real file, no pane could ever land, and asserting on one would test
    the fixture rather than the wiring.
    """
    path = _fake_video(window)
    window.document.clear()

    window._on_video_remove_requested(path)
    assert path not in window.sidebar._video_widgets

    reopened: list[Path] = []
    monkeypatch.setattr(window, "_load_video", lambda p, *args, **kwargs: reopened.append(Path(p)))
    window._undo_actions.undo_action.trigger()

    assert reopened == [Path(path)], "undo must reopen the source it closed"


def test_undo_restores_a_reset_session(window: MainWindow) -> None:
    window.annotation_store.add_point(1.0, "spike")
    window._reset_session()
    assert window.annotation_store.markers == []

    window._undo_actions.undo_action.trigger()
    assert [m.label for m in window.annotation_store.markers] == ["spike"]


# ── one stack, session-scoped ────────────────────────────────────────


def test_undo_is_session_scoped(window: MainWindow) -> None:
    """Carrying history across a load would undo onto sources that are gone."""
    window.annotation_store.add_point(1.0, "spike")
    window.document.clear()
    assert window._undo_actions.undo_action.isEnabled() is False


def test_the_menu_and_the_document_never_diverge(window: MainWindow) -> None:
    """The reason there is no second QUndoStack (D-097)."""
    window.annotation_store.add_point(1.0, "spike")
    window.annotation_store.add_point(2.0, "burst")
    window.document.undo(window._mutations)

    assert window._undo_actions.undo_action.isEnabled() == window.document.can_undo()
    assert window._undo_actions.redo_action.isEnabled() == window.document.can_redo()
    assert window._undo_actions.undo_action.text() == f"Undo {window.document.undo_label()}"


def test_saving_leaves_history_intact(window: MainWindow, tmp_path) -> None:
    """A save is not an edit: it moves the clean point, it does not erase undo."""
    window.annotation_store.add_point(1.0, "spike")
    window._session_path = Path(tmp_path / "s.avv")
    window._mark_session_saved()

    assert window.document.is_dirty is False
    assert window._undo_actions.undo_action.isEnabled() is True
