"""The one place the application's ``QSettings`` store is opened.

``QSettings("AvialSync", "AvialSync")`` always uses the *native* format — the
macOS preference plist, the Windows registry — whatever
``QSettings.setDefaultFormat`` says. Only the constructors that take a format
honour it. So a sandbox (``setDefaultFormat(IniFormat)`` plus ``setPath`` to a
temporary folder) never applied to any of the thirteen places that opened the
store that way: every sandboxed run still wrote window geometry, splitter sizes
and the inspector page into the installed application's own settings.

Opening through :func:`app_settings` passes ``QSettings.defaultFormat()``
explicitly. In the shipped application that is ``NativeFormat``, so the store,
its location and its keys are exactly what they were; under a sandbox it is the
sandbox's ini file.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

__all__ = ["APPLICATION", "ORGANISATION", "app_settings", "settings_revision"]

ORGANISATION = "AvialSync"
APPLICATION = "AvialSync"
_settings_revision = 0


class _TrackedSettings(QSettings):
    """QSettings store that increments a revision counter on every mutation."""

    def setValue(self, key: str, value: object) -> None:
        global _settings_revision
        super().setValue(key, value)
        _settings_revision += 1

    def remove(self, key: str) -> None:
        global _settings_revision
        super().remove(key)
        _settings_revision += 1

    def clear(self) -> None:
        global _settings_revision
        super().clear()
        _settings_revision += 1


def settings_revision() -> int:
    """Return a monotonic revision incremented on every ``app_settings()`` mutation."""
    return _settings_revision


def app_settings() -> QSettings:
    """Open the application's settings store in the process's default format."""
    return _TrackedSettings(
        QSettings.defaultFormat(), QSettings.Scope.UserScope, ORGANISATION, APPLICATION
    )
