"""Window composition preserves live hooks and Qt receiver ownership."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QMainWindow

from avialsync.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot) -> MainWindow:
    window = MainWindow()
    qtbot.addWidget(window)
    yield window
    window.close()


def test_feedback_keeps_instance_hooks_live(window: MainWindow, monkeypatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(window, "_refresh_action_availability", lambda: called.append("actions"))
    monkeypatch.setattr(window, "_refresh_jobs_panel", lambda: called.append("panel"))
    monkeypatch.setattr(window._job_manager, "status_text", lambda: "")
    window._on_jobs_changed()
    assert called == ["actions", "panel"]
    called.clear()
    monkeypatch.setattr(window._job_manager, "status_text", lambda: "Exporting")
    window._on_jobs_changed()
    assert called == ["actions", "panel"]


def test_feedback_and_actions_keep_window_ownership(window: MainWindow) -> None:
    assert MainWindow.__bases__ == (QMainWindow,)
    assert window._feedback.parent() is window
    assert window._feedback.thread() == window.thread()
    # Qt owns dock toggle actions through the dock. Check the keyboard actions
    # this component creates, rather than imposing a false rule on menu actions.
    shortcuts = {
        sequence.toString(QKeySequence.SequenceFormat.PortableText): action
        for action in window._all_actions
        for sequence in action.shortcuts()
    }
    for key in ("Space", "M"):
        assert shortcuts[key].parent() is window
        assert shortcuts[key].shortcutContext() == Qt.ShortcutContext.WindowShortcut


@pytest.mark.parametrize(
    "name", ["window_shortcuts.py", "window_feedback.py", "workspace_layout.py"]
)
def test_composed_components_do_not_import_the_application_window(name: str) -> None:
    """The boundary cannot quietly grow into a second window facade."""
    root = Path(__file__).resolve().parents[1] / "src" / "avialsync" / "ui" / "controllers"
    tree = ast.parse((root / name).read_text())
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(node.module == "avialsync.ui.main_window" for node in imports)


def test_workspace_keeps_one_proportion_owner(window: MainWindow) -> None:
    workspace = window._workspace
    assert window._splitters() == workspace.splitters()
    assert window._pane_proportions is workspace.proportions
    assert window._pane_resize_timer is workspace.resize_timer
    assert workspace.resize_timer.parent() is window
    assert workspace.proportions.parent() is window
    assert window.centralWidget() is workspace.central_widget


def test_legacy_layout_repair_keeps_the_live_default_hook(window: MainWindow, monkeypatch) -> None:
    applied: list[bool] = []
    monkeypatch.setattr(window, "_apply_default_splitter_sizes", lambda: applied.append(True))
    splitter = window._workspace.vertical
    child = splitter.widget(0)
    assert child is not None
    monkeypatch.setattr(child, "isVisible", lambda: True)
    monkeypatch.setattr(splitter, "sizes", lambda: [0, 100])
    window._repair_collapsed_panes()
    assert applied == [True]
