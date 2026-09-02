"""One declaration of everything that is configurable (WP-7, D-092).

Real preferences already existed. They were spread across View-menu radio
groups and five separate ``QSettings("AvialSync", "AvialSync")`` construction
sites, so there was no way to see what could be changed, no way to reset one,
and no way to include them in a bug report.

This is the schema, not the storage: ``QSettings`` stays underneath. The
Preferences dialog is *generated* from these entries rather than hand-built,
because a hand-built dialog is how "Reset to default" gets forgotten for the
one setting that needed it.

Headless, like everything in ``core/``: a setting's key, type, default and help
text are facts about the application, not about Qt.
"""

from __future__ import annotations

import dataclasses
from typing import Any

__all__ = ["Setting", "SETTINGS", "setting_for", "settings_by_group", "GROUP_ORDER"]


@dataclasses.dataclass(frozen=True)
class Setting:
    """One configurable value."""

    #: ``QSettings`` key. Slash-separated, matching what already existed on
    #: disk so no user loses their preferences to this refactor.
    key: str
    label: str
    group: str
    default: Any
    #: ``bool``, ``int``, ``float``, or ``str``.
    kind: type
    help_text: str = ""
    #: For a str setting the user picks from, rather than types.
    choices: tuple[str, ...] = ()
    #: Bounds for a numeric setting.
    minimum: float | None = None
    maximum: float | None = None


#: Groups, in the order a Preferences dialog should show them: what people
#: change often first, storage last.
GROUP_ORDER = (
    "Appearance",
    "Playback",
    "Plots",
    "Overlays",
    "Video Display",
    "Storage",
)


SETTINGS: tuple[Setting, ...] = (
    # ── Appearance ───────────────────────────────────────────────────
    Setting(
        key="theme/preference",
        label="Theme",
        group="Appearance",
        default="system",
        kind=str,
        choices=("system", "light", "dark"),
        help_text=(
            "System follows the platform, including its accent colour and any "
            "later change while AvialSync is open."
        ),
    ),
    Setting(
        key="font/preference",
        label="Font size",
        group="Appearance",
        default="system",
        kind=str,
        choices=("system", "small", "medium", "large"),
        help_text="Scales every control relative to the platform's own font.",
    ),
    Setting(
        key="palette/colour_vision_safe",
        label="Colour-vision-safe trace palette",
        group="Appearance",
        default=True,
        kind=bool,
        help_text=(
            "Use a palette whose colours stay distinguishable under the common "
            "forms of colour blindness. Evenly spaced hues do not."
        ),
    ),
    # ── Playback ─────────────────────────────────────────────────────
    Setting(
        key="playback/loop_ab",
        label="Loop the A–B range",
        group="Playback",
        default=False,
        kind=bool,
        help_text="Return to A when playback reaches B, instead of continuing.",
    ),
    # ── Plots ────────────────────────────────────────────────────────
    Setting(
        key="plot/live_presentation",
        label="Live plot presentation",
        group="Plots",
        default="sweep",
        kind=str,
        choices=("sweep", "scope"),
        help_text=(
            "Sweep retains the previous page under an eraser; Scope clears and "
            "restarts at each page boundary."
        ),
    ),
    # ── Overlays ─────────────────────────────────────────────────────
    Setting(
        key="overlays/point_labels_default",
        label="Show body-part names by default",
        group="Overlays",
        default=False,
        kind=bool,
        help_text=(
            "Off by default: on a nine-point session the names cover the animal. "
            "A session's own setting overrides this."
        ),
    ),
    # ── Video Display ────────────────────────────────────────────────
    Setting(
        key="video/auto_levels_on_open",
        label="Choose display levels automatically",
        group="Video Display",
        default=False,
        kind=bool,
        help_text=(
            "For recordings deeper than 8 bits, pick black and white points "
            "from the first frame instead of showing the full range."
        ),
    ),
    # ── Storage ──────────────────────────────────────────────────────
    Setting(
        key="storage/autosave_minutes",
        label="Autosave every",
        group="Storage",
        default=2,
        kind=int,
        minimum=1,
        maximum=60,
        help_text=(
            "Minutes between automatic saves. An unsaved session is written to "
            "a recovery snapshot on the same interval."
        ),
    ),
    Setting(
        key="storage/keep_recovery",
        label="Keep a recovery snapshot",
        group="Storage",
        default=True,
        kind=bool,
        help_text=(
            "Preserve unsaved work so closing never loses it. Turning this off "
            "means an unsaved session is gone when the window closes."
        ),
    ),
)

_BY_KEY = {setting.key: setting for setting in SETTINGS}


def setting_for(key: str) -> Setting | None:
    """Return the declared setting with *key*, if any."""
    return _BY_KEY.get(key)


def settings_by_group() -> dict[str, list[Setting]]:
    """Settings grouped for display, in :data:`GROUP_ORDER`."""
    grouped: dict[str, list[Setting]] = {}
    for setting in SETTINGS:
        grouped.setdefault(setting.group, []).append(setting)
    ordered = {group: grouped[group] for group in GROUP_ORDER if group in grouped}
    # Anything in a group nobody listed still shows, at the end, rather than
    # vanishing from the dialog because the order tuple was not updated.
    for group, entries in grouped.items():
        ordered.setdefault(group, entries)
    return ordered
