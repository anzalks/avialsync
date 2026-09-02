"""User-chosen keyboard shortcuts, layered over the defaults (WP-3).

Every editor, DAW and IDE this competes with for muscle memory lets its
shortcuts be rebound. AvialSync's were fixed: the shortcuts dialog listed them
accurately and offered no way to change one, so a user whose habits came from
another tool had to relearn rather than adjust.

Overrides are stored per action, layered over the defaults, so a later release
that changes a default still reaches everyone who never expressed a preference
— the same reasoning as the overlay registry and the settings schema.

An action's identity is derived from its category and text. That is stable
across runs and readable in the stored settings, and it means the id comes from
the action rather than a second table nobody remembers to update (D-092).
"""

from __future__ import annotations

import re

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QKeySequence

__all__ = [
    "action_id",
    "load_override",
    "store_override",
    "clear_override",
    "apply_overrides",
    "conflicting_action",
    "default_for",
]

_SETTINGS_GROUP = "shortcuts"

#: Defaults, captured before any override is applied, so "reset" has something
#: to reset to. Keyed by action id; populated the first time an action is seen.
_DEFAULTS: dict[str, str] = {}


def _store() -> QSettings:
    return QSettings("AvialSync", "AvialSync")


def action_id(action: QAction) -> str:
    """A stable, readable id for *action*.

    Derived rather than declared. A hand-maintained id table is a second place
    an action is named, and the one that goes stale when a label changes.
    """
    category = str(action.property("av_category") or "general")
    text = action.text().replace("&", "").strip()
    slug = re.sub(r"[^a-z0-9]+", "_", f"{category}_{text}".lower()).strip("_")
    return slug or "unnamed"


def remember_default(action: QAction) -> None:
    """Record an action's built-in shortcut, before any override replaces it."""
    identifier = action_id(action)
    if identifier not in _DEFAULTS:
        _DEFAULTS[identifier] = action.shortcut().toString()


def default_for(action: QAction) -> str:
    """The built-in shortcut for *action*, as a portable string."""
    return _DEFAULTS.get(action_id(action), "")


def load_override(action: QAction) -> str | None:
    """The user's shortcut for *action*, or ``None`` if they have not set one.

    An empty stored value is meaningful and distinct from absent: it means the
    user deliberately unbound the action, which must not be undone by falling
    back to the default.
    """
    stored = _store().value(f"{_SETTINGS_GROUP}/{action_id(action)}", None)
    return None if stored is None else str(stored)


def store_override(action: QAction, sequence: str) -> None:
    _store().setValue(f"{_SETTINGS_GROUP}/{action_id(action)}", sequence)


def clear_override(action: QAction) -> None:
    """Forget the user's choice, so the action follows the default again."""
    _store().remove(f"{_SETTINGS_GROUP}/{action_id(action)}")


def apply_overrides(actions: list[QAction]) -> None:
    """Apply stored shortcuts to *actions*, remembering their defaults first."""
    for action in actions:
        remember_default(action)
        override = load_override(action)
        if override is not None:
            action.setShortcut(QKeySequence(override))


def conflicting_action(
    actions: list[QAction], sequence: str, exclude: QAction | None = None
) -> QAction | None:
    """The action already bound to *sequence*, if any.

    Reported rather than refused (Law 1). Two actions in different contexts can
    legitimately share a key, and a user rebinding a whole set will pass
    through conflicting intermediate states on the way to a consistent one.
    Telling them which action already has it is useful; stopping them is not.
    """
    if not sequence:
        return None
    wanted = QKeySequence(sequence)
    for action in actions:
        if action is exclude:
            continue
        if any(existing == wanted for existing in action.shortcuts()):
            return action
    return None
