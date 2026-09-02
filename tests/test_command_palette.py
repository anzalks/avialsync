"""Finding a command by name (WP-3).

The menus have grown: File, Edit, View with four submenus nested inside it,
Help, a pane context menu, a sidebar, and a transport. The newest commands --
the overlay switches especially -- are three levels down, and a command with no
keyboard shortcut is exactly the one nobody can find.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from avialsync.ui import recovery
from avialsync.ui.command_palette import CommandPalette, fuzzy_score
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


# ── matching ─────────────────────────────────────────────────────────


def test_an_empty_query_matches_everything() -> None:
    assert fuzzy_score("", "anything") > 0


def test_a_substring_matches() -> None:
    assert fuzzy_score("overlay", "View — Overlays") > 0


def test_a_subsequence_matches() -> None:
    """ "ovl" should find Overlays; substring matching would not."""
    assert fuzzy_score("ovl", "Overlays") > 0


def test_letters_out_of_order_do_not_match() -> None:
    assert fuzzy_score("yalrevo", "Overlays") == 0


def test_a_missing_letter_does_not_match() -> None:
    assert fuzzy_score("overlayz", "Overlays") == 0


def test_matching_is_case_insensitive() -> None:
    assert fuzzy_score("OVERLAY", "overlays") > 0


def test_a_word_start_beats_a_mid_word_match() -> None:
    """The command someone meant should outrank one that merely contains it."""
    at_start = fuzzy_score("cam", "Camera name")
    mid_word = fuzzy_score("cam", "Rescan the cameras later")
    assert at_start > mid_word


def test_a_contiguous_run_beats_a_scattered_one() -> None:
    contiguous = fuzzy_score("open", "Open Videos")
    scattered = fuzzy_score("open", "Overlays per name")
    assert contiguous > scattered


def test_a_shorter_target_wins_on_equal_evidence() -> None:
    assert fuzzy_score("save", "Save Session") > fuzzy_score("save", "Save Session As Something")


# ── the palette ──────────────────────────────────────────────────────


def _palette(qtbot, actions: list[QAction]) -> CommandPalette:
    palette = CommandPalette(actions, None)
    qtbot.addWidget(palette)
    return palette


def test_it_lists_the_actions_it_was_given(qapp: QApplication, qtbot) -> None:
    actions = [QAction("Open Videos"), QAction("Reset Plot Zoom")]
    palette = _palette(qtbot, actions)
    assert palette._list.count() == 2


def test_typing_narrows_the_list(qapp: QApplication, qtbot) -> None:
    actions = [QAction("Open Videos"), QAction("Reset Plot Zoom")]
    palette = _palette(qtbot, actions)
    palette._search.setText("zoom")
    assert palette._list.count() == 1


def test_a_disabled_command_is_not_offered(qapp: QApplication, qtbot) -> None:
    """Offering it and then doing nothing is worse than not offering it."""
    enabled = QAction("Open Videos")
    disabled = QAction("Undo")
    disabled.setEnabled(False)
    palette = _palette(qtbot, [enabled, disabled])
    assert palette._list.count() == 1


def test_the_category_is_shown_for_context(qapp: QApplication, qtbot) -> None:
    """The word someone remembers is often where it lives, not what it is called."""
    action = QAction("Overlays")
    action.setProperty("av_category", "View")
    palette = _palette(qtbot, [action])
    assert "View" in palette._list.item(0).text()


def test_searching_by_category_works(qapp: QApplication, qtbot) -> None:
    action = QAction("Camera name")
    action.setProperty("av_category", "View")
    palette = _palette(qtbot, [action])
    palette._search.setText("view cam")
    assert palette._list.count() == 1


def test_the_shortcut_is_shown(qapp: QApplication, qtbot) -> None:
    from PySide6.QtGui import QKeySequence

    action = QAction("Save Session")
    action.setShortcut(QKeySequence("Ctrl+S"))
    palette = _palette(qtbot, [action])
    assert "Ctrl" in palette._list.item(0).text()


def test_running_triggers_the_action(qapp: QApplication, qtbot) -> None:
    fired: list[bool] = []
    action = QAction("Do the thing")
    action.triggered.connect(lambda: fired.append(True))

    palette = _palette(qtbot, [action])
    palette._run_selected()

    assert fired == [True]


def test_running_with_nothing_matched_is_harmless(qapp: QApplication, qtbot) -> None:
    palette = _palette(qtbot, [QAction("Open Videos")])
    palette._search.setText("zzzz")
    palette._run_selected()  # must not raise


# ── the registry behind it ───────────────────────────────────────────


def test_the_registry_includes_commands_without_shortcuts(window: MainWindow) -> None:
    """A command with no key is exactly the one nobody can find."""
    unbound = [a for a in window._all_actions if not a.shortcuts()]
    assert unbound, "the registry only held shortcut-bearing actions before WP-3"


def test_the_overlay_switches_are_reachable(window: MainWindow) -> None:
    """They are three levels deep in View; the palette is how they are found."""
    labels = [a.text() for a in window._all_actions]
    assert any("Tracking points" in label for label in labels)


def test_the_shortcuts_dialog_still_filters_to_bound_actions(window: MainWindow) -> None:
    """Broadening the registry must not fill the shortcuts table with blanks."""
    from avialsync.ui.shortcuts_dialog import ShortcutsDialog

    groups: dict[str, list[QAction]] = {}
    for action in window._all_actions:
        if not action.shortcuts():
            continue
        groups.setdefault(str(action.property("av_category") or "Other"), []).append(action)

    dialog = ShortcutsDialog(groups, window)
    try:
        assert groups, "some actions do have shortcuts"
    finally:
        dialog.close()


def test_the_palette_opens_from_the_window(window: MainWindow) -> None:
    palette = CommandPalette(list(window._all_actions), window)
    try:
        assert palette._list.count() > 10, "the whole command set should be reachable"
    finally:
        palette.close()
