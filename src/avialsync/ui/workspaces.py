"""Named window layouts (WP-11).

A session is looked at in more than one way. Aligning two recordings wants the
plots tall and the video small; checking a tracking overlay wants the opposite;
reading recorded messages wants the inspector wide. Rearranging the splitters
each time is the kind of friction that stops people doing it at all.

A workspace is the window geometry plus every splitter position and the
inspector's selected tab — exactly the state ``session_controller`` already
persists as *the* layout, stored under a name instead of as the single
implicit one.

**Layout is not session data.** These live in ``QSettings`` beside the window
geometry, not in the ``.avv`` file, because a layout belongs to the person and
their screen rather than to the recording. That boundary is already correct in
``core/session.py`` and this does not move it.

**Scope note.** WP-11 also specified converting the splitters to
``QDockWidget`` for multi-monitor use. That is not done here and it is not an
oversight: the four nested splitters carry ``PaneProportions`` tracking, a
policy re-assertion, and a collapsed-pane repair, and §3 of the plan protects
the plot behaviour that depends on them. Restructuring that is its own change
with its own evidence, not a rider on this one.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QSettings

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

__all__ = ["Workspace", "capture", "apply", "save", "load", "names", "remove"]

_GROUP = "workspaces"

#: The splitters that make up a layout, by the attribute that holds each.
_SPLITTERS = ("_h_splitter", "_v_splitter", "_media_splitter", "_content_splitter")


@dataclasses.dataclass(frozen=True)
class Workspace:
    """One saved arrangement of the window."""

    geometry: QByteArray
    splitters: dict[str, QByteArray]
    inspector_tab: int


def _store() -> QSettings:
    return QSettings("AvialSync", "AvialSync")


def capture(window: MainWindow) -> Workspace:
    """Take the window's current arrangement."""
    return Workspace(
        geometry=window.saveGeometry(),
        splitters={
            name: getattr(window, name).saveState() for name in _SPLITTERS if hasattr(window, name)
        },
        inspector_tab=window._left_tabs.currentIndex(),
    )


def apply(window: MainWindow, workspace: Workspace) -> None:
    """Put the window into *workspace*.

    The two repairs afterwards are not optional. ``restoreState`` also restores
    a splitter's collapsible flag, and a layout saved when a pane happened to
    be collapsed would otherwise come back with a zero-width pane the user
    cannot get back -- which is what ``session_controller.restore_geometry``
    already guards against for the single implicit layout.
    """
    if workspace.geometry:
        window.restoreGeometry(workspace.geometry)

    for name, state in workspace.splitters.items():
        splitter = getattr(window, name, None)
        if splitter is not None and state:
            splitter.restoreState(state)

    tab_count = window._left_tabs.count()
    window._left_tabs.setCurrentIndex(max(0, min(workspace.inspector_tab, tab_count - 1)))

    window._enforce_splitter_policy()
    window._repair_collapsed_panes()
    # The restored arrangement is now the ratio to hold, so a later resize
    # scales it rather than drifting back toward whatever preceded it.
    window._pane_proportions.record_all()


def save(name: str, workspace: Workspace) -> None:
    """Store *workspace* under *name*, replacing any previous one."""
    if not name.strip():
        return
    store = _store()
    store.beginGroup(f"{_GROUP}/{name.strip()}")
    store.setValue("geometry", workspace.geometry)
    for splitter_name, state in workspace.splitters.items():
        store.setValue(f"splitter_{splitter_name}", state)
    store.setValue("inspector_tab", workspace.inspector_tab)
    store.endGroup()


def load(name: str) -> Workspace | None:
    """The workspace stored under *name*, or ``None``."""
    store = _store()
    store.beginGroup(f"{_GROUP}/{name}")
    try:
        geometry = store.value("geometry")
        if geometry is None:
            return None
        splitters = {}
        for splitter_name in _SPLITTERS:
            state = store.value(f"splitter_{splitter_name}")
            if state is not None:
                splitters[splitter_name] = state
        # QSettings hands back a string on some platforms and an int on
        # others; a stored tab index that arrives as "2" must not become 0.
        tab = store.value("inspector_tab", 0)
        try:
            tab_index = int(str(tab))
        except (TypeError, ValueError):
            tab_index = 0
        return Workspace(geometry=geometry, splitters=splitters, inspector_tab=tab_index)
    finally:
        store.endGroup()


def names() -> list[str]:
    """Every saved workspace name, sorted."""
    store = _store()
    store.beginGroup(_GROUP)
    try:
        return sorted(store.childGroups())
    finally:
        store.endGroup()


def remove(name: str) -> None:
    _store().remove(f"{_GROUP}/{name}")
