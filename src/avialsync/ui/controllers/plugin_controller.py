"""Plugins in the File menu: their folder, a reload, and which ones are switched on.

Also hands each plugin its declared settings (D-220): the registry is headless
and cannot read ``QSettings``, so the window reads the values and passes them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMenu

from avialsync.core.registry import LoaderRegistry, plugin_key
from avialsync.ui.app_settings import app_settings
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

#: Where the switched-off plugins are remembered, as :func:`plugin_key` strings.
DISABLED_KEY = "plugins/disabled"


def plugin_folder() -> Path:
    """The drop-in folder every build scans, installed or from source."""
    return Path.home() / ".avialsync" / "plugins"


def disabled_plugins() -> set[str]:
    value = app_settings().value(DISABLED_KEY, [])
    if isinstance(value, str):
        return {value} if value else set()
    if isinstance(value, list | tuple):
        return {str(item) for item in value}
    return set()


def new_registry() -> LoaderRegistry:
    """The window's registry, with the plugins the user switched off left off."""
    registry = LoaderRegistry()
    apply_disabled(registry)
    return registry


def apply_disabled(registry: LoaderRegistry) -> None:
    registry.set_disabled(disabled_plugins())


def publish_plugin_settings(registry: LoaderRegistry) -> None:
    """Give every plugin the current values of the settings it declared."""
    from avialsync.ui.preferences_dialog import read_setting

    registry.configure_plugins(
        {setting.key: read_setting(setting) for setting in registry.plugin_settings()}
    )


def open_plugin_folder(window: MainWindow) -> None:
    """Show the drop-in folder, creating it so there is somewhere to put a plugin."""
    folder = plugin_folder()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        window.notifications.show_error(tr("Could not create the plugins folder"), str(error))
        return
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def reload_plugins(window: MainWindow) -> None:
    """Discover plugins again, so a file just dropped in the folder is usable now."""
    registry = window.registry
    registry.reload()
    apply_disabled(registry)
    publish_plugin_settings(registry)
    errors = registry.plugin_errors
    count = len(registry.plugins())
    if errors:
        window.notifications.show_warning(
            tr("{count} plugins loaded; {failed} could not be used.").format(
                count=count, failed=len(errors)
            ),
            details="\n".join(f"{name}: {reason}" for name, reason in errors),
        )
    else:
        window.notifications.show_success(tr("{count} plugins loaded.").format(count=count))


def _set_enabled(window: MainWindow, key: str, enabled: bool) -> None:
    disabled = disabled_plugins()
    if enabled:
        disabled.discard(key)
    else:
        disabled.add(key)
    app_settings().setValue(DISABLED_KEY, sorted(disabled))
    apply_disabled(window.registry)


def fill_plugin_menu(window: MainWindow, menu: QMenu) -> None:
    """List every plugin as a switch, after the folder and reload actions."""
    menu.clear()
    act = menu.addAction(tr("Open Plugins Folder"))
    act.setToolTip(str(plugin_folder()))
    act.triggered.connect(lambda: open_plugin_folder(window))
    act = menu.addAction(tr("Reload Plugins"))
    act.triggered.connect(lambda: reload_plugins(window))
    menu.addSeparator()
    registry = window.registry
    for kind, cls, origin in registry.plugins():
        key = plugin_key(cls)
        name = cls.display_name() if hasattr(cls, "display_name") else cls.__name__
        entry = menu.addAction(f"{name} ({tr(kind)}, {origin})")
        entry.setCheckable(True)
        entry.setChecked(registry.is_enabled(cls))
        entry.setToolTip(key)
        entry.toggled.connect(lambda on, k=key: _set_enabled(window, k, on))
