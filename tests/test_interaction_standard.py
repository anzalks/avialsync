"""D-022 interaction standard tests.

Verifies:
- New transport buttons emit the correct signals.
- A/B buttons show active (checked) state when set and clear when reset.
- plot_pane receives the SAME QAction object for reset-zoom (not a copy).
- Space shortcut is wired through transport.play_toggled (not direct engine call).
- Ctrl+V / Ctrl+D are dead (system-key reservation, D-022.7 / Trap §18).
- Ctrl+Shift+V / Ctrl+Shift+D are active.
- ShortcutsDialog derives rows from live QAction registry (not a static table).
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.ui.transport import Transport
from avialsync.ui.view_toolbar import ViewToolbar

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def transport(qtbot):
    w = Transport()
    qtbot.addWidget(w)
    w.set_bounds(0.0, 10.0)
    w.set_time(5.0)
    return w


@pytest.fixture
def main_window(qapp: QApplication, qtbot):
    """Registered with ``qtbot``, which is not decoration.

    Without it the window is never handed to pytest-qt for teardown, and this
    module's process segfaulted at interpreter exit -- reproducibly, on code
    that predates these tests. Qt tears the widget tree down after the
    interpreter has begun dropping the Python wrappers, and a menu walk that
    catches that moment reads freed QActions ("Internal C++ object already
    deleted") instead of the menu it asked for.
    """
    from avialsync.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    # Qt may already have deleted it: pytest-qt runs processEvents()
    # after the call phase, which executes pending deleteLater()s.
    if isValid(win):
        win.close()


# ── Transport signal tests ────────────────────────────────────────────────────


def test_jump_back_btn_emits_jump_requested(transport: Transport) -> None:
    received: list[float] = []
    transport.jump_requested.connect(received.append)
    transport._jump_back_btn.click()
    assert received == [-1.0], "Jump-back button must emit jump_requested(-1.0)"


def test_jump_fwd_btn_emits_jump_requested(transport: Transport) -> None:
    received: list[float] = []
    transport.jump_requested.connect(received.append)
    transport._jump_fwd_btn.click()
    assert received == [1.0], "Jump-fwd button must emit jump_requested(+1.0)"


def test_snapshot_btn_triggers_the_export_snapshot_action(qtbot) -> None:
    """D-174: the glyph button is the File menu's action, not a signal of its own."""
    toolbar = ViewToolbar()
    qtbot.addWidget(toolbar)
    action = QAction("Export Snapshot…", toolbar)
    action.setShortcut("Ctrl+E")
    fired: list[Any] = []
    action.triggered.connect(lambda: fired.append(1))
    toolbar.install_snapshot_action(action)
    toolbar.snapshot_button.click()
    assert fired, "Snapshot button must trigger Export Snapshot"
    assert toolbar.snapshot_button.text() == ""
    assert toolbar.snapshot_button.accessibleName() == "Export Snapshot"
    assert toolbar.snapshot_button.toolTip().startswith("Export Snapshot (")


def test_fullscreen_btn_triggers_the_fullscreen_action(qtbot) -> None:
    """D-174: one QAction behind View → Fullscreen and the glyph button."""
    toolbar = ViewToolbar()
    qtbot.addWidget(toolbar)
    action = QAction("Fullscreen", toolbar)
    fired: list[Any] = []
    action.triggered.connect(lambda: fired.append(1))
    toolbar.install_fullscreen_action(action)
    toolbar.fullscreen_button.click()
    assert fired, "Fullscreen button must trigger View → Fullscreen"
    assert toolbar.fullscreen_button.accessibleName() == "Fullscreen"


# ── A/B active-state tests (D-022.5) ─────────────────────────────────────────


def test_ab_in_btn_becomes_checked(transport: Transport) -> None:
    assert not transport._ab_in_btn.isChecked()
    transport._on_ab_in()
    assert transport._ab_in_btn.isChecked(), "A/B in button must be checked after set"


def test_ab_out_btn_becomes_checked(transport: Transport) -> None:
    assert not transport._ab_out_btn.isChecked()
    transport._on_ab_out()
    assert transport._ab_out_btn.isChecked(), "A/B out button must be checked after set"


def test_ab_clear_unchecks_both_buttons(transport: Transport) -> None:
    transport._on_ab_in()
    transport._on_ab_out()
    transport._on_ab_clear()
    assert not transport._ab_in_btn.isChecked(), "In-btn must be unchecked after clear"
    assert not transport._ab_out_btn.isChecked(), "Out-btn must be unchecked after clear"


def test_ab_loop_changed_emitted_on_in(transport: Transport) -> None:
    events: list[tuple] = []
    transport.ab_loop_changed.connect(lambda a, b: events.append((a, b)))
    transport._on_ab_in()
    assert events, "ab_loop_changed must be emitted when in-point is set"


def test_step_rate_up_advances_combo(transport: Transport) -> None:
    start = transport.rate_combo.currentIndex()
    transport.step_rate_up()
    assert transport.rate_combo.currentIndex() == min(start + 1, transport.rate_combo.count() - 1)


def test_step_rate_up_at_max_stays_at_max(transport: Transport) -> None:
    transport.rate_combo.setCurrentIndex(transport.rate_combo.count() - 1)
    transport.step_rate_up()
    assert transport.rate_combo.currentIndex() == transport.rate_combo.count() - 1


# ── QAction identity test (D-022) ─────────────────────────────────────────────


def test_plot_pane_receives_same_reset_zoom_action(main_window) -> None:
    """The reset-zoom action in the plot context menu must be the same object
    as the View-menu QAction — not a copy (D-022.1)."""
    assert main_window.plot_pane._extra_context_actions, (
        "plot_pane._extra_context_actions must not be empty after setup"
    )
    assert main_window.plot_pane._extra_context_actions[0] is main_window._act_reset_zoom, (
        "Context-menu reset-zoom must be the SAME QAction object as the menu-bar action"
    )


# ── System-key safety (D-022.7 / Trap §18) ────────────────────────────────────


def _all_shortcuts(win) -> list[str]:
    """Collect the NativeText of every shortcut registered on the window."""
    result: list[str] = []
    for act in getattr(win, "_all_actions", []):
        for seq in act.shortcuts():
            result.append(seq.toString(QKeySequence.SequenceFormat.NativeText))
    return result


def test_ctrl_v_is_not_bound(main_window) -> None:
    """Ctrl+V must never be bound (system Paste, D-022.7)."""
    shorts = _all_shortcuts(main_window)
    assert "Ctrl+V" not in shorts, "Ctrl+V is a reserved system key and must not be bound"


def test_ctrl_d_is_not_bound(main_window) -> None:
    """Ctrl+D must never be bound (platform dock/bookmark key, D-022.7)."""
    shorts = _all_shortcuts(main_window)
    assert "Ctrl+D" not in shorts, "Ctrl+D is a reserved system key and must not be bound"


def test_ctrl_shift_v_is_bound(main_window) -> None:
    """Ctrl+Shift+V must open video (D-022.7)."""
    for act in getattr(main_window, "_all_actions", []):
        for seq in act.shortcuts():
            if "Ctrl+Shift+V" in seq.toString():
                return

    # Also check menu bar actions that _reg skips (actions without shortcuts initially)
    def _walk_menu(m):
        for a in m.actions():
            if a.menu():
                yield from _walk_menu(a.menu())
            else:
                yield a

    for bar_act in main_window.menuBar().actions():
        if bar_act.menu():
            for a in _walk_menu(bar_act.menu()):
                for seq in a.shortcuts():
                    if "Ctrl+Shift+V" in seq.toString():
                        return
    pytest.fail("Ctrl+Shift+V is not bound to any action")


def test_ctrl_shift_d_is_bound(main_window) -> None:
    """Ctrl+Shift+D must open sensor/ephys data (D-022.7)."""

    def _walk_menu(m):
        for a in m.actions():
            if a.menu():
                yield from _walk_menu(a.menu())
            else:
                yield a

    for bar_act in main_window.menuBar().actions():
        if bar_act.menu():
            for a in _walk_menu(bar_act.menu()):
                for seq in a.shortcuts():
                    if "Ctrl+Shift+D" in seq.toString():
                        return
    pytest.fail("Ctrl+Shift+D is not bound to any action")


# ── Space shortcut wired to transport signal (D-022.1) ────────────────────────


def test_space_action_exists_in_all_actions(main_window) -> None:
    """Space must appear in _all_actions (window QAction, not a direct engine call)."""
    space_key = QKeySequence(QKeySequence.StandardKey.MoveToNextChar)  # just a ref
    space_key = QKeySequence("Space")
    space_acts = [
        act
        for act in main_window._all_actions
        if any(
            seq.matches(space_key) == QKeySequence.SequenceMatch.ExactMatch
            for seq in act.shortcuts()
        )
    ]
    assert space_acts, "Space must be registered as a QAction in _all_actions"


def test_space_action_emits_play_toggled(main_window) -> None:
    """Triggering the Space QAction must emit transport.play_toggled."""
    received: list[bool] = []
    main_window.transport.play_toggled.connect(received.append)

    space_key = QKeySequence("Space")
    for act in main_window._all_actions:
        if any(
            seq.matches(space_key) == QKeySequence.SequenceMatch.ExactMatch
            for seq in act.shortcuts()
        ):
            act.trigger()
            break

    assert received, "Space QAction.trigger() must emit transport.play_toggled"


@pytest.mark.parametrize("editor_name", ["plot_limit", "transport_time"])
def test_entered_time_editor_returns_focus_to_playback_surface(
    main_window,
    qtbot,
    editor_name: str,
) -> None:
    """Accepting a time value returns focus to a playback surface.

    This used to also assert that Space *inside* the editor did nothing. That
    was the defect, not the contract: a numeric editor holding focus silently
    disabled every playhead key until the user happened to press Return, which
    is what "the key bindings stop working after some operations" meant. Space
    is now a playback command from anywhere in the window — no timecode or
    number contains one (D-059). Returning focus on accept still matters, and
    is what this test guards.
    """
    received: list[bool] = []
    main_window.transport.play_toggled.connect(received.append)
    if editor_name == "plot_limit":
        editor = main_window.plot_pane.window_limit_spin
        expected_focus = main_window.plot_pane
    else:
        editor = main_window.transport._time_edit
        editor.selectAll()
        qtbot.keyClicks(editor, "2.5")
        expected_focus = main_window.transport

    editor.setFocus()
    qtbot.keyClick(editor, Qt.Key.Key_Space)
    assert received == [True], "Space must reach playback even from an editor"

    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert QApplication.focusWidget() is expected_focus

    qtbot.keyClick(expected_focus, Qt.Key.Key_Space)
    assert received == [True, False], "and must keep toggling once focus returns"


# ── Shortcuts dialog derives from registry (D-022.6) ──────────────────────────


def test_shortcuts_dialog_shows_registered_actions(main_window, qtbot) -> None:
    """ShortcutsDialog must show rows derived from live _all_actions, not a static table."""
    from avialsync.ui.shortcuts_dialog import ShortcutsDialog

    groups: dict[str, list[QAction]] = {}
    for act in main_window._all_actions:
        if not act.shortcuts():
            continue
        cat = str(act.property("av_category") or "Other")
        groups.setdefault(cat, []).append(act)

    dlg = ShortcutsDialog(groups, main_window)
    qtbot.addWidget(dlg)

    # Find the table widget
    from PySide6.QtWidgets import QTableWidget

    tables = dlg.findChildren(QTableWidget)
    assert tables, "ShortcutsDialog must contain a QTableWidget"
    table = tables[0]
    assert table.rowCount() > 0, (
        "ShortcutsDialog must have at least one row from the live action registry"
    )


def test_shortcuts_dialog_includes_every_registered_action(main_window, qtbot) -> None:
    """Every action in _all_actions with shortcuts must appear in the dialog."""
    from PySide6.QtWidgets import QTableWidget

    from avialsync.ui.shortcuts_dialog import ShortcutsDialog

    groups: dict[str, list[QAction]] = {}
    for act in main_window._all_actions:
        if not act.shortcuts():
            continue
        cat = str(act.property("av_category") or "Other")
        groups.setdefault(cat, []).append(act)

    n_expected = sum(len(v) for v in groups.values())
    dlg = ShortcutsDialog(groups, main_window)
    qtbot.addWidget(dlg)

    tables = dlg.findChildren(QTableWidget)
    assert tables
    assert tables[0].rowCount() == n_expected, (
        f"Expected {n_expected} rows (one per action), got {tables[0].rowCount()}"
    )


# -- K-while-paused test (D-022.4) -------------------------------------------


def test_k_while_paused_stays_paused(main_window) -> None:
    """K key while paused must emit play_toggled(False) and keep the transport paused (D-022.4).

    D-022.4 specifies K = pause unconditionally; pressing it when already paused
    must be a no-op in terms of state (never toggle to playing).
    """
    received: list[bool] = []
    main_window.transport.play_toggled.connect(received.append)

    # Ensure we start paused
    main_window.transport.set_playing(False)

    # Simulate K key: find the Pause QAction and trigger it
    k_seq = QKeySequence("K")
    k_acts = [
        act
        for act in main_window._all_actions
        if any(
            seq.matches(k_seq) == QKeySequence.SequenceMatch.ExactMatch for seq in act.shortcuts()
        )
    ]
    assert k_acts, "K key must be registered as a QAction in _all_actions"
    k_acts[0].trigger()

    assert received, "K action must emit play_toggled"
    assert received[-1] is False, (
        "K while paused must emit play_toggled(False) \u2014 never play_toggled(True)"
    )
    # Transport must remain showing paused state
    assert not main_window.transport.play_btn.isChecked(), (
        "Transport play button must remain unchecked (paused) after K"
    )


# ── Preferences stays where the user (and the docs) look (D-135) ──────────────


def _file_menu(window):
    """Return the File menu *and the action that owns it*, both to be held.

    Two references, deliberately. A helper that returns only the menu, or only
    a list of its actions, hands the caller objects whose owner it has already
    dropped: PySide deletes the real ``QMenu`` when the last wrapper referring
    to it is collected, so every action in the list then answers "Internal C++
    object already deleted" -- which reads like a torn-down window and is
    really a dropped reference.
    """
    for bar_act in window.menuBar().actions():
        if bar_act.text() == "File":
            return bar_act, bar_act.menu()
    pytest.fail("the window has no File menu")


def test_preferences_is_in_the_file_menu(main_window) -> None:
    """`PreferencesRole` moved it into the macOS application menu.

    That menu is named after the running process, so anyone starting AvialSync
    from a terminal or a conda env found it under a menu called "python" --
    while the File menu, the command palette and the user guide all said File.
    Quit and About keep their roles; this one is ours (D-135).
    """
    _owner, menu = _file_menu(main_window)
    texts = [action.text() for action in menu.actions()]
    assert "Preferences…" in texts, texts


def test_preferences_is_not_relocated_by_a_menu_role(main_window) -> None:
    _owner, menu = _file_menu(main_window)
    actions = [a for a in menu.actions() if a.text() == "Preferences…"]
    assert actions, "no Preferences action in the File menu"
    assert actions[0].menuRole() == QAction.MenuRole.NoRole, (
        "any role but NoRole moves the item out of the File menu on macOS"
    )
    assert actions[0].shortcut() == QKeySequence(QKeySequence.StandardKey.Preferences), (
        "the platform shortcut stays whatever menu holds the item"
    )


def test_quit_and_about_keep_their_platform_roles(main_window) -> None:
    """The exception proves the rule: those two belong in the app menu (D-022.3)."""
    roles = {}
    for bar_act in main_window.menuBar().actions():
        menu = bar_act.menu()
        if menu is None:
            continue
        for action in menu.actions():
            if action.text() in ("Quit", "About AvialSync"):
                roles[action.text()] = action.menuRole()
    assert roles.get("Quit") == QAction.MenuRole.QuitRole
    assert roles.get("About AvialSync") == QAction.MenuRole.AboutRole
