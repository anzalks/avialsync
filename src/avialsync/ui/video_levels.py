"""Each camera's display levels: the one place a change is made and shown (D-209).

Three controls edit the same thing -- the inspector's Display Levels panel for
the focused camera, the levels popover on every pane, and undo -- and the
session saves it. All of them come here, so the panel, the popover, the pane's
"adjusted" marker and the decoder can never disagree (AGENTS rule 15). A user
change is a :class:`~avialsync.core.commands.SetVideoLevelsCommand` on the
bus, so it is undoable and marks the session changed like any other edit.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING, Any

from avialsync.core.commands import SetVideoLevelsCommand
from avialsync.engine.display_pipeline import DisplayLevels

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

#: What the Edit menu calls a change of each part of the window.
_ASPECTS = {"black": "black point", "white": "white point", "gamma": "gamma"}


def to_dict(levels: DisplayLevels) -> dict[str, float]:
    return {key: float(value) for key, value in dataclasses.asdict(levels).items()}


def from_dict(data: Any) -> DisplayLevels:
    """Levels from a session or a command, ignoring anything it does not know."""
    if not isinstance(data, dict):
        return DisplayLevels()
    try:
        return DisplayLevels(
            black=float(data.get("black", 0.0)),
            white=float(data.get("white", 1.0)),
            gamma=float(data.get("gamma", 1.0)),
        ).normalised()
    except (TypeError, ValueError):
        return DisplayLevels()


def current(window: MainWindow, path: str) -> DisplayLevels:
    """The levels camera *path* is shown through now."""
    return window._display_levels.get(path, DisplayLevels())


def _aspect(before: DisplayLevels, after: DisplayLevels) -> str:
    """Which control moved, so a drag merges into one undo step and two drags stay two.

    Going back to full range is a step of its own rather than the end of the
    last drag, so undoing it restores what it replaced.
    """
    if after.is_identity:
        return "display levels (full range)"
    changed = [
        name for name in _ASPECTS if abs(getattr(before, name) - getattr(after, name)) > 1e-9
    ]
    return _ASPECTS[changed[0]] if len(changed) == 1 else "display levels"


def request(
    window: MainWindow, path: str | None, levels: object, aspect: str | None = None
) -> None:
    """A user's change to camera *path*: recorded on the bus, then shown everywhere."""
    if path is None or not isinstance(levels, DisplayLevels):
        return
    before = current(window, path)
    after = levels.normalised()
    if after == before:
        return
    if window._recording_suspended:
        apply(window, path, after)
        return
    window.document.execute(
        SetVideoLevelsCommand(
            path,
            to_dict(before),
            to_dict(after),
            aspect or _aspect(before, after),
            Path(path).name,
        ),
        window._mutations,
    )


def request_auto(window: MainWindow, path: str | None) -> None:
    """Ask camera *path* to measure levels from its frame; the answer arrives as a change."""
    pane = window._pane_for(path) if path is not None else None
    measure = getattr(pane, "request_auto_levels", None)
    if callable(measure):
        measure()


def apply(window: MainWindow, path: str, levels: DisplayLevels) -> None:
    """Show *levels* for *path*: decoder, pane marker and popover, inspector panel."""
    levels = levels.normalised()
    if levels.is_identity:
        window._display_levels.pop(path, None)
    else:
        window._display_levels[path] = levels
    window.video_grid.set_display_levels(path, levels)
    if path == window._focused_video_path():
        window.levels_panel.set_levels(levels)


def show_focused(window: MainWindow) -> None:
    """Point the inspector panel at the focused camera: its depth and its levels."""
    path = window._focused_video_path()
    pane = window._pane_for(path) if path is not None else None
    window.levels_panel.set_source_format(getattr(pane, "source_format", None))
    window.levels_panel.set_levels(current(window, path) if path is not None else DisplayLevels())


def reset(window: MainWindow) -> None:
    """Forget every camera's levels, as a session reset forgets its cameras."""
    window._display_levels.clear()
    show_focused(window)


def restore(window: MainWindow, saved: dict[str, Any]) -> None:
    """Take up a session's levels, kept until each camera's pane opens and applies its own."""
    window._display_levels = {
        path: levels
        for path, data in (saved or {}).items()
        if not (levels := from_dict(data)).is_identity
    }


def connect_pane(window: MainWindow, pane: Any, path: str) -> None:
    """Wire a camera that has just opened, and give it the levels the session holds.

    The pane reports what the recording turned out to be once it has decoded
    a frame, and the panel labels itself from that rather than guessing; its
    own popover edits this camera, whichever camera is focused.
    """
    pane.source_format_detected.connect(lambda fmt: window._on_source_format_detected(path, fmt))
    pane.levels_requested.connect(lambda levels: request(window, path, levels))
    pane.levels_measured.connect(
        lambda levels: request(window, path, levels, "display levels (Auto)")
    )
    levels = window._display_levels.get(path)
    if levels is not None:
        window.video_grid.set_display_levels(path, levels)


def saved(window: MainWindow) -> dict[str, dict[str, float]]:
    """The levels to write into a session: only cameras that are adjusted."""
    return {path: to_dict(levels) for path, levels in window._display_levels.items()}
