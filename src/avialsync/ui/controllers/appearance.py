"""The window title, and the theme and font-size menus.

MainWindow keeps one delegator per function (D-066). The theme and font
functions take the menu's action group as an argument, so nothing here reads a
private window field (D-148).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QApplication

from avialsync.ui.i18n import tr
from avialsync.ui.theme import (
    apply_font_size,
    apply_theme,
    current_font_preference,
    current_preference,
)

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

_THEME_ORDER = ("system", "dark", "light")


def update_window_title(window: MainWindow) -> None:
    """Name the open session in the title bar, with Qt's modified marker.

    The title used to be the constant string "AvialSync", so two windows
    were indistinguishable in the taskbar and nothing showed that a session
    had unsaved changes. ``[*]`` is Qt's placeholder: it renders as the
    platform's own modified indicator when ``setWindowModified(True)`` and
    disappears otherwise, so this stays native on each OS rather than
    hardcoding an asterisk.
    """
    path = window.session_runtime.path
    name = path.stem if path is not None else "Untitled"
    window.setWindowTitle(tr("{name}[*] — AvialSync").format(name=name))
    window.setWindowModified(window.document.is_dirty)


def mark_session_saved(window: MainWindow) -> None:
    """Record that the session on disk now matches the workspace."""
    path = window.session_runtime.path
    window.document.session_path = str(path) if path else None
    window.document.mark_saved()
    update_window_title(window)


def _application() -> QApplication | None:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else None


def on_theme_selected(action: QAction) -> None:
    """Apply the theme a View menu item names."""
    if (app := _application()) is not None:
        apply_theme(app, action.data())


def _check_matching(group: QActionGroup, preference: str) -> None:
    for action in group.actions():
        if action.data() == preference:
            action.setChecked(True)
            break


def sync_theme_menu(group: QActionGroup) -> None:
    """Check the theme menu item that matches the saved preference."""
    _check_matching(group, current_preference())


def cycle_theme(group: QActionGroup) -> None:
    """Step system → dark → light → system, and keep the menu in step."""
    preference = current_preference()
    index = _THEME_ORDER.index(preference) if preference in _THEME_ORDER else 0
    if (app := _application()) is not None:
        apply_theme(app, _THEME_ORDER[(index + 1) % len(_THEME_ORDER)])
    sync_theme_menu(group)


def on_font_size_selected(action: QAction) -> None:
    """Apply the selected system-relative application font scale."""
    if (app := _application()) is not None:
        apply_font_size(app, action.data())


def sync_font_size_menu(group: QActionGroup) -> None:
    """Check the font-size menu item that matches the saved preference."""
    _check_matching(group, current_font_preference())
