"""Named window layouts (WP-11).

A session is looked at in more than one way -- aligning wants tall plots,
checking an overlay wants a large video, reading messages wants a wide
inspector -- and rearranging the splitters each time is friction enough to stop
people doing it.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.ui import recovery, workspaces
from avialsync.ui.main_window import MainWindow


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


# ── capture and apply ────────────────────────────────────────────────


def test_capturing_takes_the_whole_arrangement(window: MainWindow) -> None:
    captured = workspaces.capture(window)
    assert captured.geometry
    assert captured.splitters, "every splitter contributes to a layout"
    assert isinstance(captured.inspector_tab, int)


def test_a_layout_round_trips(window: MainWindow) -> None:
    window._left_tabs.setCurrentIndex(2)
    captured = workspaces.capture(window)

    window._left_tabs.setCurrentIndex(0)
    workspaces.apply(window, captured)

    assert window._left_tabs.currentIndex() == 2


def test_applying_repairs_a_collapsed_pane(window: MainWindow) -> None:
    """restoreState also restores the collapsible flag, so this is not optional."""
    captured = workspaces.capture(window)
    workspaces.apply(window, captured)
    for name in ("_h_splitter", "_v_splitter", "_media_splitter", "_content_splitter"):
        splitter = getattr(window, name, None)
        if splitter is None:
            continue
        assert all(size >= 0 for size in splitter.sizes())


def test_a_stale_tab_index_is_clamped(window: MainWindow) -> None:
    """A layout saved when there were more tabs must not select past the end."""
    captured = workspaces.capture(window)
    stale = workspaces.Workspace(
        geometry=captured.geometry, splitters=captured.splitters, inspector_tab=99
    )
    workspaces.apply(window, stale)
    assert window._left_tabs.currentIndex() < window._left_tabs.count()


# ── storage ──────────────────────────────────────────────────────────


def test_nothing_is_saved_initially() -> None:
    assert workspaces.names() == []


def test_a_saved_layout_is_listed(window: MainWindow) -> None:
    workspaces.save("Aligning", workspaces.capture(window))
    assert "Aligning" in workspaces.names()


def test_a_saved_layout_loads_back(window: MainWindow) -> None:
    window._left_tabs.setCurrentIndex(1)
    workspaces.save("Reviewing", workspaces.capture(window))

    loaded = workspaces.load("Reviewing")
    assert loaded is not None
    assert loaded.inspector_tab == 1


def test_an_unknown_layout_loads_as_none() -> None:
    assert workspaces.load("never saved") is None


def test_saving_the_same_name_replaces_it(window: MainWindow) -> None:
    window._left_tabs.setCurrentIndex(0)
    workspaces.save("One", workspaces.capture(window))
    window._left_tabs.setCurrentIndex(2)
    workspaces.save("One", workspaces.capture(window))

    assert workspaces.names().count("One") == 1
    assert workspaces.load("One").inspector_tab == 2


def test_an_empty_name_saves_nothing(window: MainWindow) -> None:
    workspaces.save("   ", workspaces.capture(window))
    assert workspaces.names() == []


def test_removing_forgets_it(window: MainWindow) -> None:
    workspaces.save("Temporary", workspaces.capture(window))
    workspaces.remove("Temporary")
    assert "Temporary" not in workspaces.names()


def test_several_layouts_coexist(window: MainWindow) -> None:
    for index, name in enumerate(("Aligning", "Reviewing", "Messages")):
        window._left_tabs.setCurrentIndex(index)
        workspaces.save(name, workspaces.capture(window))

    assert set(workspaces.names()) == {"Aligning", "Reviewing", "Messages"}
    assert workspaces.load("Messages").inspector_tab == 2


# ── the menu ─────────────────────────────────────────────────────────


def test_the_menu_says_when_there_are_none(window: MainWindow) -> None:
    labels = [action.text() for action in window._workspace_menu.actions()]
    assert any("no saved layouts" in label for label in labels)


def test_the_menu_lists_saved_layouts(window: MainWindow) -> None:
    workspaces.save("Aligning", workspaces.capture(window))
    window._rebuild_workspace_menu()
    labels = [action.text() for action in window._workspace_menu.actions()]
    assert "Aligning" in labels


def test_delete_is_only_offered_when_there_is_something(window: MainWindow) -> None:
    labels = [action.text() for action in window._workspace_menu.actions()]
    assert not any("Delete" in label for label in labels)

    workspaces.save("Aligning", workspaces.capture(window))
    window._rebuild_workspace_menu()
    labels = [action.text() for action in window._workspace_menu.actions()]
    assert any("Delete" in label for label in labels)


def test_applying_a_vanished_layout_reports_it(window: MainWindow) -> None:
    """Stored settings are shared; another window may have removed it."""
    window._apply_workspace("never existed")
    assert "no longer stored" in window.notifications.message


# ── layout is not session data ───────────────────────────────────────


def test_layouts_are_not_written_to_the_session(window: MainWindow) -> None:
    """A layout belongs to the person and their screen, not the recording."""
    workspaces.save("Aligning", workspaces.capture(window))
    state = window._build_session_state().to_dict()
    assert "workspaces" not in state
    assert "geometry" not in state


# ── deleting a layout is reversible, and says so (D-107) ─────────────


def _accept_deleting(monkeypatch, name: str) -> None:
    """Answer the "which layout?" prompt with *name*."""
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: (name, True)))


def test_deleting_a_layout_says_it_happened(window: MainWindow, monkeypatch) -> None:
    """Saving a layout reported; deleting one said nothing at all.

    That is the wrong way round -- the destructive half is the one that needs
    an answer.
    """
    workspaces.save("Rig A", workspaces.capture(window))
    window._rebuild_workspace_menu()
    _accept_deleting(monkeypatch, "Rig A")

    window._delete_workspace()

    assert "Rig A" in window.notifications.message
    assert workspaces.load("Rig A") is None


def test_deleting_a_layout_offers_it_back(window: MainWindow, monkeypatch) -> None:
    """An Undo offer rather than an "are you sure?" gate in front of it.

    Never block, always inform: the deletion happens, and the layout is held
    until the message is dismissed. The same shape as the recovery offer, for
    the same reason.
    """
    workspaces.save("Rig A", workspaces.capture(window))
    window._rebuild_workspace_menu()
    _accept_deleting(monkeypatch, "Rig A")
    window._delete_workspace()
    assert window.notifications.action_label == "Undo"

    window.notifications.action_button.click()

    assert workspaces.load("Rig A") is not None, "Undo did not put the layout back"
    assert "Rig A" in workspaces.names()


def test_declining_the_undo_leaves_it_deleted(window: MainWindow, monkeypatch) -> None:
    """Dismiss declines the offer; it does not re-delete or restore anything."""
    workspaces.save("Rig A", workspaces.capture(window))
    window._rebuild_workspace_menu()
    _accept_deleting(monkeypatch, "Rig A")
    window._delete_workspace()

    window.notifications.clear()

    assert workspaces.load("Rig A") is None


def test_cancelling_the_prompt_deletes_nothing(window: MainWindow, monkeypatch) -> None:
    from PySide6.QtWidgets import QInputDialog

    workspaces.save("Rig A", workspaces.capture(window))
    window._rebuild_workspace_menu()
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("Rig A", False)))

    window._delete_workspace()

    assert workspaces.load("Rig A") is not None
