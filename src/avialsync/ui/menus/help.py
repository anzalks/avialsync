"""Build the Help menu from live actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu, QMenuBar

from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

Register = Callable[[QAction, str], QAction]


def build_help_menu(window: MainWindow, menu: QMenuBar, _reg: Register) -> QMenu:
    """Create this menu and connect its actions to the window."""
    # ── Help ──────────────────────────────────────────────────────
    help_menu = menu.addMenu(tr("Help"))

    window._act_review_workflow = help_menu.addAction(tr("Review Workflow…"))
    window._act_review_workflow.setToolTip(
        tr("Open a task guide for checking timing, alignment, and observations")
    )
    window._act_review_workflow.triggered.connect(window._help_controller.show_review_workflow)
    _reg(window._act_review_workflow, "View")

    # Shortcuts dialog: F1 primary (HelpContents); "?" alias added in _setup_shortcuts
    # Commands — searchable by name. The menus are deep enough now that
    # finding a command is the problem, not typing it (WP-3).
    act = help_menu.addAction(tr("Commands…"))
    act.setShortcut(QKeySequence("Ctrl+Shift+P"))
    act.setToolTip(tr("Search every command by name"))
    act.triggered.connect(window._show_command_palette)
    _reg(act, "View")

    window._act_shortcuts = help_menu.addAction(tr("Keyboard Shortcuts…"))
    window._act_shortcuts.setShortcut(QKeySequence(QKeySequence.StandardKey.HelpContents))
    window._act_shortcuts.triggered.connect(window._show_shortcuts)
    _reg(window._act_shortcuts, "View")

    act = help_menu.addAction(tr("Documentation"))
    act.triggered.connect(
        lambda _checked=False: window._help_controller.open_project_url("Documentation")
    )
    act = help_menu.addAction(tr("Report a Problem…"))
    act.triggered.connect(window._help_controller.report_a_problem)
    act = help_menu.addAction(tr("Check for Updates"))
    act.setToolTip(tr("The installers are not code-signed and do not update themselves"))
    act.triggered.connect(
        lambda _checked=False: window._help_controller.open_project_url("Changelog")
    )
    help_menu.addSeparator()

    act = help_menu.addAction(tr("Cite AvialSync…"))
    act.triggered.connect(window._help_controller.show_citation)

    act = help_menu.addAction(tr("Diagnostics…"))
    act.triggered.connect(window._help_controller.show_diagnostics)

    # About — macOS AboutRole moves this to the app menu (D-022.3)
    act = help_menu.addAction(tr("About AvialSync"))
    act.setMenuRole(QAction.MenuRole.AboutRole)
    act.triggered.connect(window._help_controller.show_about)

    return help_menu
