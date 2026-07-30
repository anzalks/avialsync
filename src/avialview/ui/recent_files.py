"""Recent-session list backed by QSettings.

This lives in ``ui/`` rather than ``core/`` because it is presentation state, not
session data: it depends on Qt and it must not pollute the ``.avv`` data file.
Architecture rule 2 — ``core/`` never imports PySide6 — is enforced by
``tests/test_headless_core.py``.
"""

from __future__ import annotations

from typing import cast

from PySide6.QtCore import QSettings

_MAX_RECENT = 10
_SETTINGS_KEY = "session/recent_files"


def _settings() -> QSettings:
    return QSettings("AvialView", "AvialView")


def add_recent(path: str) -> None:
    """Push *path* to the top of the recent-files list."""
    settings = _settings()
    recent: list[str] = cast(list[str], settings.value(_SETTINGS_KEY, [], type=list))
    if path in recent:
        recent.remove(path)
    recent.insert(0, path)
    settings.setValue(_SETTINGS_KEY, recent[:_MAX_RECENT])


def get_recent() -> list[str]:
    """Return the recent-files list, newest first."""
    return cast(list[str], _settings().value(_SETTINGS_KEY, [], type=list))


def clear_recent() -> None:
    """Clear the recent-files list."""
    _settings().setValue(_SETTINGS_KEY, [])
