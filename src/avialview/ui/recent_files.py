"""Recent-files list backed by QSettings."""

from typing import cast

from PySide6.QtCore import QSettings

_MAX_RECENT = 10
_SETTINGS_KEY = "session/recent_files"


def add_recent(path: str) -> None:
    """Push *path* to the top of the recent-files list."""
    settings = QSettings("AvialView", "AvialView")
    recent: list[str] = cast(list[str], settings.value(_SETTINGS_KEY, [], type=list))
    if path in recent:
        recent.remove(path)
    recent.insert(0, path)
    settings.setValue(_SETTINGS_KEY, recent[:_MAX_RECENT])


def get_recent() -> list[str]:
    """Return the recent-files list, newest first."""
    settings = QSettings("AvialView", "AvialView")
    return cast(list[str], settings.value(_SETTINGS_KEY, [], type=list))


def clear_recent() -> None:
    """Clear the recent-files list."""
    settings = QSettings("AvialView", "AvialView")
    settings.setValue(_SETTINGS_KEY, [])
