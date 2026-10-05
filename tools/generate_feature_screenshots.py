"""Capture the screenshots for features the other generators do not cover.

The Props tab (ladder, belt and ball steps), the Tasks tab, the File and View
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
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMenu, QTabWidget

from avialsync.ui import theme
from avialsync.ui.main_window import MainWindow
from avialsync.ui.wheel_dialogs import _WheelSetupDialog

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
    """The Props tab's declared geometry and evidence controls.

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
    assert window.props_app.tab is not None
    tab = window.props_app.tab
    tab.ensureWidgetVisible(panel.save_step)
    settle(app)
    capture(
        window,
        out_dir / "feature_props_ladder_steps.png",
        (panel.add_point, panel.add_rung, panel.save_step),
        crop=window._left_tabs,
    )
    panel.kind.setCurrentIndex(panel.kind.findData("belt"))
    panel.name.setText("Example belt")
    panel.belt_units.setCurrentIndex(panel.belt_units.findData("mm"))
    for point in ((0.0, 0.0, 70.0), (10.0, 0.0, 70.0)):
        for field, value in zip(panel.belt_point_fields, point, strict=True):
            field.setValue(value)
        panel.belt_add_vertex.click()
    panel.belt_direction_fields[0].setValue(1.0)
    panel.save_belt.click()
    tab.verticalScrollBar().setValue(0)
    settle(app)
    capture(window, out_dir / "feature_props_belt.png", (panel.kind,))
    tab.ensureWidgetVisible(panel.belt_add_vertex)
    settle(app)
    capture(
        window,
        out_dir / "feature_props_belt_geometry.png",
        (panel.belt_vertices, panel.belt_add_vertex, panel.belt_direction_fields[0]),
        crop=window._left_tabs,
    )
    tab.ensureWidgetVisible(panel.track_belt)
    settle(app)
    capture(
        window,
        out_dir / "feature_props_belt_evidence.png",
        (panel.belt_channel, panel.bind_belt, panel.track_belt),
        crop=window._left_tabs,
    )
    panel.kind.setCurrentIndex(panel.kind.findData("ball"))
    panel.name.setText("Example ball")
    panel.ball_centre_fields[2].setValue(70.0)
    panel.ball_radius.setValue(5.0)
    panel.ball_units.setCurrentIndex(panel.ball_units.findData("mm"))
    panel.save_ball.click()
    tab.verticalScrollBar().setValue(0)
    settle(app)
    capture(
        window,
        out_dir / "feature_props_ball_geometry.png",
        (panel.ball_centre_fields[0], panel.ball_radius, panel.ball_units),
        crop=window._left_tabs,
    )
    tab.ensureWidgetVisible(panel.track_ball)
    settle(app)
    capture(
        window,
        out_dir / "feature_props_ball_evidence.png",
        (panel.ball_visual_mark, panel.track_ball),
        crop=window._left_tabs,
    )
    panel.kind.setCurrentIndex(panel.kind.findData("ladder"))
    settle(app)

    # Show the first-use dialog even when the screenshot author's machine has
    # remembered a different wheel setup; no preference is read or changed.
    with patch("avialsync.ui.wheel_dialogs._saved_details", return_value=None):
        setup = _WheelSetupDialog((), None, (), window)
    setup.name_edit.setText("Example_wheel")
    setup.bars.setValue(36)
    setup.units.setCurrentIndex(setup.units.findData("mm"))
    setup.radius.setValue(100.0)
    setup.show()
    settle(app)
    capture(
        setup,
        out_dir / "feature_props_wheel_setup.png",
        (setup.name_edit, setup.bars, setup.units, setup.radius, setup.encoder),
        numbered=True,
    )
    setup.close()
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
    # The fixture import is setup, not a tutorial edit. Do not put its
    # temporary absolute path into the command-palette screenshot as Undo Open.
    window.document.clear()
    window.transport.set_status("Ready")
    settle(app)

    try:
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

        pin_appearance(app)
        window.raise_()
        window.activateWindow()
        pin_layout(window)
        _show_tab(window, app, "Props")
        _capture_props(window, app, out_dir)
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
