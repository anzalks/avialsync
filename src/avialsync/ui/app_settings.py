"""The one place the application's ``QSettings`` store is opened.

``QSettings("AvialSync", "AvialSync")`` always uses the *native* format — the
macOS preference plist, the Windows registry — whatever
``QSettings.setDefaultFormat`` says. Only the constructors that take a format
honour it. So the sandbox the test suite and the screenshot tools set up
(``setDefaultFormat(IniFormat)`` plus ``setPath`` to a temporary folder) never
applied to any of the thirteen places that opened the store that way: every test
run and every documentation capture wrote window geometry, splitter sizes and
the inspector page into the developer's installed application
(INTERFACE_DESIGN_PLAN F-36).

Opening through :func:`app_settings` passes ``QSettings.defaultFormat()``
explicitly. In the shipped application that is ``NativeFormat``, so the store,
its location and its keys are exactly what they were; under a sandbox it is the
sandbox's ini file. ``tests/test_app_settings.py`` keeps any other construction
out of ``src/`` and ``tests/``.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

__all__ = ["APPLICATION", "ORGANISATION", "app_settings"]

ORGANISATION = "AvialSync"
APPLICATION = "AvialSync"


def app_settings() -> QSettings:
    """Open the application's settings store in the process's default format."""
    return QSettings(
        QSettings.defaultFormat(), QSettings.Scope.UserScope, ORGANISATION, APPLICATION
    )
