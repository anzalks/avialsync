"""The inspector as a dock, and the one-time move from splitter state (D-180).

The inspector was the left pane of a horizontal splitter. As a dock it can sit
on either side, float onto a second display, or be closed and brought back from
View → Inspector, and the window remembers where it was with
``QMainWindow.saveState``.

Only the inspector moved. The workspace column -- videos, 3D, plots, Data
Streams, transport -- keeps its three splitters, because they carry the
proportional resize and minimum-size contracts (D-049, D-061, D-098) and the
empty-window layout (D-127) that docks do not express.

A layout saved before this change stored the inspector's width inside
``splitter/horizontal``. That width is read once through a throwaway splitter
and handed to ``resizeDocks``, then the old key is removed.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QDataStream, QSettings, Qt
from PySide6.QtWidgets import QDockWidget, QMainWindow

from avialsync.ui.i18n import tr
from avialsync.ui.inspector_nav import InspectorNav

__all__ = [
    "DEFAULT_INSPECTOR_WIDTH",
    "apply_dock_state",
    "default_dock_width",
    "dock_state",
    "install_inspector_dock",
    "inspector_width_from_splitter_state",
    "restore_dock_state",
    "save_dock_state",
]

#: The first-run width of an inspector *page* (it was the splitter's first
#: size); the dock adds the page rail to it, so the page keeps all 280 px.
DEFAULT_INSPECTOR_WIDTH = 280
#: Where the dock arrangement lives; separate from the window geometry.
DOCK_STATE_KEY = "window/dock_state"
#: The pre-D-180 splitter state that held the inspector's width.
LEGACY_SPLITTER_KEY = "splitter/horizontal"
#: Bumped if the set of docks changes, so an old state is not misapplied.
_STATE_VERSION = 1
#: First int of every ``QSplitter.saveState``.
_SPLITTER_MARKER = 0xFF


def default_dock_width(nav: InspectorNav, page_width: int = DEFAULT_INSPECTOR_WIDTH) -> int:
    """The dock width that leaves *page_width* for the page beside the rail."""
    return page_width + nav.rail_width()


def install_inspector_dock(window: QMainWindow, nav: InspectorNav) -> QDockWidget:
    """Put *nav* in a dock on the window's left, movable, floatable, closable."""
    dock = QDockWidget(tr("Inspector"), window)
    dock.setObjectName("inspector_dock")  # saveState keys docks by object name
    dock.setAccessibleName(tr("Inspector panel"))
    dock.setAllowedAreas(
        Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
    )
    dock.setFeatures(
        QDockWidget.DockWidgetFeature.DockWidgetMovable
        | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        | QDockWidget.DockWidgetFeature.DockWidgetClosable
    )
    dock.setWidget(nav)
    window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
    toggle = dock.toggleViewAction()
    toggle.setText(tr("Show Inspector Panel"))
    toggle.setToolTip(tr("Show or hide the inspector, docked or floating"))
    return dock


def inspector_width_from_splitter_state(state: QByteArray) -> int | None:
    """The inspector width a pre-D-180 ``splitter/horizontal`` state recorded.

    Read from the bytes, not by restoring into a probe splitter: an unsized
    splitter redistributes what it restores, so the probe reported its own
    share, not the width the user had dragged to. The layout is QSplitter's:
    a 0xff marker, a version, then the list of pane sizes.
    """
    stream = QDataStream(state)
    stream.setByteOrder(QDataStream.ByteOrder.BigEndian)
    marker, version = stream.readInt32(), stream.readInt32()
    if marker != _SPLITTER_MARKER or version < 0:
        return None
    count = stream.readInt32()
    if count < 1 or stream.status() != QDataStream.Status.Ok:
        return None
    first = stream.readInt32()
    return first if first > 0 and stream.status() == QDataStream.Status.Ok else None


def restore_dock_state(window: QMainWindow, dock: QDockWidget, settings: QSettings) -> None:
    """Restore the dock arrangement, migrating a splitter-era width once."""
    state = settings.value(DOCK_STATE_KEY)
    if isinstance(state, QByteArray) and not state.isEmpty():
        window.restoreState(state, _STATE_VERSION)
    else:
        legacy = settings.value(LEGACY_SPLITTER_KEY)
        width = (
            inspector_width_from_splitter_state(legacy) if isinstance(legacy, QByteArray) else None
        )
        nav = dock.widget()
        page = width or DEFAULT_INSPECTOR_WIDTH
        target = default_dock_width(nav, page) if isinstance(nav, InspectorNav) else page
        window.resizeDocks([dock], [target], Qt.Orientation.Horizontal)
        settings.remove(LEGACY_SPLITTER_KEY)
    # A floating dock restored onto a display that is no longer attached would
    # be unreachable; dock it again rather than leave it off screen.
    if dock.isFloating() and window.screen() is not None:
        on_screen = any(
            screen.availableGeometry().intersects(dock.frameGeometry())
            for screen in window.screen().virtualSiblings()
        )
        if not on_screen:
            dock.setFloating(False)


def save_dock_state(window: QMainWindow, settings: QSettings) -> None:
    settings.setValue(DOCK_STATE_KEY, window.saveState(_STATE_VERSION))


def dock_state(window: QMainWindow) -> QByteArray:
    """The current dock arrangement, for a named workspace."""
    return window.saveState(_STATE_VERSION)


def apply_dock_state(window: QMainWindow, dock: QDockWidget, state: QByteArray | None) -> None:
    """Apply a workspace's dock arrangement; a splitter-era one sets only the width."""
    if state is not None and not state.isEmpty():
        window.restoreState(state, _STATE_VERSION)
