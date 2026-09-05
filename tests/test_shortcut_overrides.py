"""Rebindable keyboard shortcuts (WP-3).

Shortcuts were fixed. The dialog listed them accurately and offered no way to
change one, so a user whose muscle memory came from another tool had to
relearn. Every editor, DAW and IDE this competes with allows rebinding.

The listing still derives from live QActions (D-022.6) -- editing was added to
that, not substituted for it -- and :func:`test_the_listing_still_comes_from_live_actions`
is what holds that.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.ui import recovery
from avialsync.ui.main_window import MainWindow
from avialsync.ui.shortcut_overrides import (
    action_id,
    apply_overrides,
    clear_override,
    conflicting_action,
    default_for,
    load_override,
    remember_default,
    store_override,
)
from avialsync.ui.shortcuts_dialog import ShortcutsDialog


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = QSettings("AvialSync", "AvialSync")
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


@pytest.fixture(autouse=True)
def application(qapp: QApplication) -> QApplication:
    """Every test here builds QActions, and one with no QApplication aborts.

    Autouse rather than requested per test: constructing a QAction without an
    application is an access violation, not an exception, so forgetting it
    takes the whole run down rather than failing one case.
    """
    return qapp


def _action(text: str, category: str = "File", key: str = "") -> QAction:
    action = QAction(text)
    action.setProperty("av_category", category)
    if key:
        action.setShortcut(QKeySequence(key))
    return action


# ── identity ─────────────────────────────────────────────────────────


def test_an_id_is_derived_from_the_action() -> None:
    """Not a hand-maintained table -- that is the one that goes stale."""
    assert action_id(_action("Open Videos…", "File")) == "file_open_videos"


def test_ids_are_stable_across_equivalent_actions() -> None:
    assert action_id(_action("Save Session", "File")) == action_id(_action("Save Session", "File"))


def test_different_categories_give_different_ids() -> None:
    """Two commands can share a label and must not share an override."""
    assert action_id(_action("Reset", "File")) != action_id(_action("Reset", "View"))


def test_an_unnamed_action_still_has_an_id() -> None:
    assert action_id(QAction(""))


# ── storing and layering ─────────────────────────────────────────────


def test_no_override_reads_as_none() -> None:
    assert load_override(_action("Open Videos")) is None


def test_an_override_round_trips() -> None:
    action = _action("Open Videos")
    store_override(action, "Ctrl+Alt+O")
    assert load_override(action) == "Ctrl+Alt+O"


def test_an_empty_override_is_distinct_from_absent() -> None:
    """Deliberately unbinding a command must not fall back to its default."""
    action = _action("Open Videos", key="Ctrl+O")
    store_override(action, "")
    assert load_override(action) == ""


def test_clearing_restores_the_default() -> None:
    action = _action("Open Videos", key="Ctrl+O")
    store_override(action, "Ctrl+Alt+O")
    clear_override(action)
    assert load_override(action) is None


def test_applying_overrides_rebinds() -> None:
    action = _action("Open Videos", key="Ctrl+O")
    store_override(action, "Ctrl+Alt+O")
    apply_overrides([action])
    assert action.shortcut() == QKeySequence("Ctrl+Alt+O")


def test_applying_leaves_unoverridden_actions_alone() -> None:
    """A later release changing a default still reaches anyone who never chose."""
    action = _action("Open Videos", key="Ctrl+O")
    apply_overrides([action])
    assert action.shortcut() == QKeySequence("Ctrl+O")


def test_the_default_is_remembered_before_it_is_replaced() -> None:
    action = _action("Unique Reset Test Action", key="Ctrl+9")
    remember_default(action)
    store_override(action, "Ctrl+8")
    apply_overrides([action])
    assert default_for(action) == QKeySequence("Ctrl+9").toString()


# ── conflicts are reported, not refused ──────────────────────────────


def test_a_free_key_has_no_conflict() -> None:
    actions = [_action("A", key="Ctrl+1"), _action("B", key="Ctrl+2")]
    assert conflicting_action(actions, "Ctrl+3") is None


def test_a_taken_key_names_its_owner() -> None:
    taken = _action("Already Bound", key="Ctrl+1")
    assert conflicting_action([taken], "Ctrl+1") is taken


def test_an_action_does_not_conflict_with_itself() -> None:
    action = _action("A", key="Ctrl+1")
    assert conflicting_action([action], "Ctrl+1", exclude=action) is None


def test_an_empty_sequence_conflicts_with_nothing() -> None:
    assert conflicting_action([_action("A", key="Ctrl+1")], "") is None


# ── the dialog ───────────────────────────────────────────────────────


def _dialog(qtbot, actions: list[QAction]) -> ShortcutsDialog:
    dialog = ShortcutsDialog({"File": actions}, None)
    qtbot.addWidget(dialog)
    return dialog


def test_unbound_commands_are_listed(qapp: QApplication, qtbot) -> None:
    """One with no key is exactly the one somebody wants to give a key."""
    dialog = _dialog(qtbot, [_action("No Key Yet")])
    assert dialog._table.rowCount() == 1


def test_editing_a_key_rebinds_the_action(qapp: QApplication, qtbot) -> None:
    action = _action("Open Videos", key="Ctrl+O")
    dialog = _dialog(qtbot, [action])
    dialog._table.item(0, 1).setText("Ctrl+Alt+O")
    assert action.shortcut() == QKeySequence("Ctrl+Alt+O")


def test_editing_a_key_persists_it(qapp: QApplication, qtbot) -> None:
    action = _action("Open Videos", key="Ctrl+O")
    dialog = _dialog(qtbot, [action])
    dialog._table.item(0, 1).setText("Ctrl+Alt+O")
    assert load_override(action) == "Ctrl+Alt+O"


def test_nonsense_is_rejected_without_changing_anything(qapp: QApplication, qtbot) -> None:
    action = _action("Open Videos", key="Ctrl+O")
    dialog = _dialog(qtbot, [action])
    dialog._table.item(0, 1).setText("not a key")
    assert action.shortcut() == QKeySequence("Ctrl+O")
    assert "not a key sequence" in dialog._notice.text()


def test_a_clash_is_reported_and_still_applied(qapp: QApplication, qtbot) -> None:
    """Reported, not refused: rebinding a set passes through clashing states."""
    first = _action("First", key="Ctrl+1")
    second = _action("Second", key="Ctrl+2")
    dialog = _dialog(qtbot, [first, second])

    dialog._table.item(1, 1).setText("Ctrl+1")

    assert second.shortcut() == QKeySequence("Ctrl+1"), "the user's choice is honoured"
    assert "also bound" in dialog._notice.text()
    assert "First" in dialog._notice.text(), "it names which command already has it"


def test_reset_restores_the_default(qapp: QApplication, qtbot) -> None:
    action = _action("Open Videos", key="Ctrl+O")
    remember_default(action)
    dialog = _dialog(qtbot, [action])

    dialog._table.item(0, 1).setText("Ctrl+Alt+O")
    dialog._table.selectRow(0)
    dialog._reset_selected()

    assert action.shortcut() == QKeySequence("Ctrl+O")
    assert load_override(action) is None


def test_the_category_column_is_not_editable(qapp: QApplication, qtbot) -> None:
    dialog = _dialog(qtbot, [_action("Open Videos", key="Ctrl+O")])
    assert not (dialog._table.item(0, 0).flags() & Qt.ItemFlag.ItemIsEditable)


# ── the property that must not be lost ───────────────────────────────


def test_the_listing_still_comes_from_live_actions(window: MainWindow) -> None:
    """D-022.6: it cannot drift from the real bindings because it *is* them."""
    action = next(a for a in window._all_actions if a.text())
    dialog = ShortcutsDialog({"File": [action]}, window)
    try:
        held = dialog._table.item(0, 1).data(Qt.ItemDataRole.UserRole)
        assert held is action
    finally:
        dialog.close()


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


def test_the_window_applies_overrides_at_startup(qapp: QApplication, qtbot) -> None:
    """A rebinding has to survive a restart to be worth anything."""
    probe = MainWindow()
    qtbot.addWidget(probe)
    target = next(a for a in probe._all_actions if a.text() and a.shortcuts())
    identifier = action_id(target)
    probe.close()

    QSettings("AvialSync", "AvialSync").setValue(f"shortcuts/{identifier}", "Ctrl+Alt+Shift+K")

    fresh = MainWindow()
    qtbot.addWidget(fresh)
    try:
        rebound = next(a for a in fresh._all_actions if action_id(a) == identifier)
        assert rebound.shortcut() == QKeySequence("Ctrl+Alt+Shift+K")
    finally:
        fresh.close()
