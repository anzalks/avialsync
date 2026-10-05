"""The inspector dock and its migration from splitter state (D-180, DS-14)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QSplitter, QWidget
from shiboken6 import isValid

from avialsync.ui import workspaces
from avialsync.ui.app_settings import app_settings
from avialsync.ui.controllers import session_controller
from avialsync.ui.inspector_dock import (
    DOCK_STATE_KEY,
    LEGACY_SPLITTER_KEY,
    default_dock_width,
    inspector_width_from_splitter_state,
)
from avialsync.ui.main_window import MainWindow


@pytest.fixture
def window(qapp: QApplication, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1400, 900)
    win.show()
    qapp.processEvents()
    yield win
    if isValid(win):
        win.close()


def _legacy_state(inspector: int, rest: int):
    """What ``splitter/horizontal`` held before the inspector became a dock."""
    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.addWidget(QWidget())
    splitter.addWidget(QWidget())
    splitter.resize(inspector + rest + splitter.handleWidth(), 400)
    splitter.setSizes([inspector, rest])
    state = splitter.saveState()
    splitter.deleteLater()
    return state


def test_the_inspector_is_a_movable_floatable_closable_dock(window: MainWindow) -> None:
    dock = window.inspector_dock
    assert dock.widget() is window._left_tabs
    assert window.dockWidgetArea(dock) == Qt.DockWidgetArea.LeftDockWidgetArea
    assert dock.toggleViewAction() in window._all_actions, "View → Inspector reaches it"
    dock.toggleViewAction().trigger()
    assert dock.isHidden()
    window._bring_panels_back()
    assert dock.isVisible() and not dock.isFloating()


def test_a_splitter_era_layout_restores_into_the_dock(window: MainWindow, qapp) -> None:
    """DS-14 acceptance: a pre-migration QSettings layout is honoured, once."""
    assert inspector_width_from_splitter_state(_legacy_state(360, 900)) == 360
    settings = app_settings()
    settings.remove(DOCK_STATE_KEY)
    settings.setValue(LEGACY_SPLITTER_KEY, _legacy_state(360, 900))
    session_controller.restore_geometry(window)
    qapp.processEvents()
    assert abs(window.inspector_dock.width() - default_dock_width(window._left_tabs, 360)) <= 12
    assert settings.value(LEGACY_SPLITTER_KEY) is None, "migrated once, then dropped"
    session_controller.save_geometry(window)
    assert settings.value(DOCK_STATE_KEY) is not None


def test_a_workspace_round_trips_where_the_dock_is(window: MainWindow, qapp) -> None:
    dock = window.inspector_dock
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    qapp.processEvents()
    workspaces.save("right inspector", workspaces.capture(window))

    window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
    qapp.processEvents()
    loaded = workspaces.load("right inspector")
    assert loaded is not None and not loaded.dock_state.isEmpty()
    workspaces.apply(window, loaded)
    qapp.processEvents()
    assert window.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea


def test_a_splitter_era_workspace_keeps_its_inspector_width(window: MainWindow, qapp) -> None:
    store = app_settings()
    store.beginGroup("workspaces/old layout")
    store.setValue("geometry", window.saveGeometry())
    store.setValue("splitter__h_splitter", _legacy_state(330, 900))
    store.endGroup()
    loaded = workspaces.load("old layout")
    assert loaded is not None and loaded.legacy_inspector_width == 330
    workspaces.apply(window, loaded)
    qapp.processEvents()
    assert abs(window.inspector_dock.width() - default_dock_width(window._left_tabs, 330)) <= 12


def test_the_default_page_keeps_its_full_width_beside_the_rail(qapp, qtbot) -> None:
    """The dock's default width is rail plus page, so the page is not squeezed.

    The first dock took 280 px including the rail, which left the Sources page
    about 190 px against its 200 px minimum: cards clipped at the right and a
    sideways scrollbar showed on a fresh window.
    """
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1280, 800)
    win.show()
    qapp.processEvents()
    page = win._left_tabs.currentWidget()
    assert page is win.sidebar
    assert page.width() >= page.minimumWidth()
    assert win.sidebar._scroll_area.horizontalScrollBar().maximum() == 0
    win.close()
