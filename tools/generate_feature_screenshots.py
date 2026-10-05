"""Capture the screenshots for features the other generators do not cover.

The Props tab (a ladder and the belt editor), the Tasks tab, the File and View
menus (including File → Cache and View → Overlays), the command palette,
Preferences, and the light appearance.

Run with ``conda run -n avialsync python tools/generate_feature_screenshots.py``.
Do **not** set ``QT_QPA_PLATFORM=offscreen`` — see ``tools/screenshot_kit.py``.

Uses the same synthetic inputs as the guide screenshots, so it is reproducible
from a clean clone and never touches private field data (AGENTS.md rule 5).
Nothing here changes a saved preference: appearance is pinned with
``persist=False`` and the dialogs are only shown, never accepted.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMenu, QTabWidget

from avialsync.ui import theme
from avialsync.ui.main_window import MainWindow

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_guide_screenshots import _load_session  # noqa: E402
from screenshot_kit import (  # noqa: E402
    capture,
    pin_appearance,
    pin_layout,
    settle,
    write_synthetic_sync_fixture,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "docs" / "_static" / "screenshots"


def _show_tab(window: MainWindow, app: QApplication, label: str) -> None:
    tabs: QTabWidget = window._left_tabs
    for index in range(tabs.count()):
        if tabs.tabText(index) == label:
            tabs.setCurrentIndex(index)
            settle(app)
            return
    raise RuntimeError(f"No sidebar tab called {label!r}.")


def _menu(window: MainWindow, title: str) -> QMenu:
    for menu in window.findChildren(QMenu):
        if menu.title().replace("&", "") == title:
            return menu
    raise RuntimeError(f"No menu called {title!r}.")


def _capture_menu(
    window: MainWindow, app: QApplication, title: str, path: Path, submenu: str | None = None
) -> None:
    """Photograph a menu, or one of its submenus, as the user sees it opened."""
    menu = _menu(window, title)
    if submenu is not None:
        menu = _menu(window, submenu)
    menu.ensurePolished()
    menu.adjustSize()
    menu.popup(window.mapToGlobal(window.rect().topLeft()))
    settle(app)
    menu.grab().save(str(path))
    menu.hide()
    settle(app)


def _capture_props(window: MainWindow, app: QApplication, out_dir: Path) -> None:
    """The Props tab holding a ladder, then the belt editor.

    The ladder is added through the panel's own Add control, so its prop file
    lands in the fixture's temporary ``pose-3d/`` and nowhere else.
    """
    panel = window.props_app.panel
    if panel is None:
        raise RuntimeError("The Props panel was not built.")
    panel.select_prop("", "ladder")
    window.props_app.create("Ladder")
    settle(app)
    capture(window, out_dir / "feature_props_tab.png", (panel.kind, panel.name))
    panel.kind.setCurrentIndex(panel.kind.findData("belt"))
    settle(app)
    capture(window, out_dir / "feature_props_belt.png", (panel.kind,))
    panel.kind.setCurrentIndex(panel.kind.findData("ladder"))
    settle(app)


def _generate(out_dir: Path, session: Path) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    pin_appearance(app)
    out_dir.mkdir(parents=True, exist_ok=True)

    window = MainWindow()
    window.resize(1280, 860)
    window.show()
    settle(app)
    pin_layout(window)
    settle(app)
    _load_session(window, app, session)
    window.transport.set_status("Ready")
    settle(app)

    try:
        _show_tab(window, app, "Props")
        _capture_props(window, app, out_dir)
        _show_tab(window, app, "Tasks")
        capture(window, out_dir / "feature_tasks_tab.png")
        _show_tab(window, app, "Sources")

        _capture_menu(window, app, "File", out_dir / "feature_menu_file.png")
        _capture_menu(window, app, "File", out_dir / "feature_menu_file_cache.png", "Cache")
        _capture_menu(window, app, "View", out_dir / "feature_menu_view.png")
        _capture_menu(window, app, "View", out_dir / "feature_menu_view_overlays.png", "Overlays")

        from avialsync.ui.command_palette import CommandPalette

        palette = CommandPalette(list(window._all_actions), window)
        palette.show()
        settle(app)
        palette.grab().save(str(out_dir / "feature_command_palette.png"))
        palette.close()

        window._help_controller.show_preferences()
        settle(app)
        dialog = window._help_controller._preferences_dialog
        dialog.grab().save(str(out_dir / "feature_preferences.png"))
        dialog.close()
        settle(app)

        theme._apply(app, theme.THEME_LIGHT, persist=False)
        settle(app)
        capture(window, out_dir / "feature_light_theme.png")
    finally:
        pin_appearance(app)
        window.close()
        settle(app)
    print(f"Wrote feature screenshots to {out_dir}")


def main(out_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    with tempfile.TemporaryDirectory() as scratch:
        _generate(out_dir, write_synthetic_sync_fixture(Path(scratch)))


if __name__ == "__main__":
    main()
