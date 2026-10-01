"""Compose the main menu while deriving command metadata from live QActions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QAction

from avialsync.ui.menus.align import build_align_menu
from avialsync.ui.menus.edit import build_edit_menu
from avialsync.ui.menus.file import build_file_menu
from avialsync.ui.menus.help import build_help_menu
from avialsync.ui.menus.view import build_view_menu

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


def build_menus(window: MainWindow) -> None:
    """Build menus in order and keep each action as its sole identity source."""
    window._all_actions.clear()
    window._letter_shortcuts.clear()
    window._action_preconditions.clear()

    def register(action: QAction, category: str) -> QAction:
        """Tag one live action for shortcuts, palette, and enablement."""
        action.setProperty("av_category", category)
        action.setAutoRepeat(False)
        window._all_actions.append(action)
        return action

    menu = window.menuBar()
    file_menu = build_file_menu(window, menu, register)
    build_edit_menu(window, menu, register)
    align_menu = build_align_menu(window, menu, register)
    view_menu = build_view_menu(window, menu, register)
    help_menu = build_help_menu(window, menu, register)

    for opened in (file_menu, align_menu, view_menu, help_menu):
        opened.aboutToShow.connect(window._refresh_action_availability)
    window._refresh_action_availability()
