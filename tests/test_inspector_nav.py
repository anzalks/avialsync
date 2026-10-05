"""The inspector page rail (D-172, INTERFACE_DESIGN_PLAN DS-6)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLabel
from shiboken6 import isValid

from avialsync.ui.app_settings import app_settings
from avialsync.ui.controllers import session_controller
from avialsync.ui.inspector_nav import InspectorNav
from avialsync.ui.main_window import MainWindow

PAGES = ("Sources", "Values", "Messages", "Changes", "Props")


@pytest.fixture
def window(qapp: QApplication, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1280, 800)
    win.show()
    qapp.processEvents()
    yield win
    if isValid(win):
        win.close()


def _nav(qtbot) -> InspectorNav:
    nav = InspectorNav()
    qtbot.addWidget(nav)
    for name in PAGES:
        nav.addTab(QLabel(name), name, icon=name.lower())
    return nav


def test_every_page_label_is_shown_whole(qapp: QApplication, qtbot) -> None:
    """F-13: no page name elides, at any font size, because the rail fits its widest label."""
    nav = _nav(qtbot)
    nav.resize(280, 600)
    nav.show()
    qapp.processEvents()
    for scale in (1.0, 1.6):
        font = nav.font()
        font.setPointSizeF(QApplication.font().pointSizeF() * scale)
        nav.setFont(font)
        qapp.processEvents()
        for index in range(nav.count()):
            button = nav.button(index)
            needed = button.fontMetrics().horizontalAdvance(button.text())
            assert button.width() >= needed, f"{button.text()!r} is cut off at scale {scale}"


def test_a_short_rail_scrolls_vertically_instead_of_cropping(qapp: QApplication, qtbot) -> None:
    """The user asked for this: a short window scrolls the pages, never crops a title."""
    nav = _nav(qtbot)
    nav.resize(280, 60)
    nav.show()
    qapp.processEvents()
    scroll = nav.rail_scroll
    assert scroll.verticalScrollBar().maximum() > 0
    assert scroll.horizontalScrollBar().maximum() == 0
    nav.setCurrentIndex(nav.count() - 1)
    qapp.processEvents()
    last = nav.button(nav.count() - 1)
    top = last.mapTo(scroll.viewport(), last.rect().topLeft()).y()
    assert 0 <= top < scroll.viewport().height(), "the selected page is scrolled into view"
    column = nav.rail_scroll.widget().sizeHint().height()
    assert scroll.minimumSizeHint().height() < column, "the rail never sets the window's minimum"


def test_click_and_arrow_keys_reach_every_page(qapp: QApplication, qtbot) -> None:
    nav = _nav(qtbot)
    nav.show()
    seen: list[int] = []
    nav.currentChanged.connect(seen.append)
    nav.button(2).click()
    assert nav.currentIndex() == 2 and nav.currentWidget() is nav.widget(2)
    for _ in range(nav.count()):
        QApplication.sendEvent(
            nav.button(nav.currentIndex()),
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier),
        )
    assert sorted(set(seen)) == list(range(nav.count()))
    assert nav.currentIndex() == 2, "Down wraps through every page back to the start"
    assert all(nav.button(i).accessibleName() == PAGES[i] for i in range(nav.count()))


def test_menu_and_palette_reach_every_page_and_tasks(window: MainWindow) -> None:
    """DS-6 step 4: one live action per page, registered for the command palette."""
    labels = [action.text() for action in window._inspector_actions]
    assert labels == [f"Show {name}" for name in PAGES] + ["Show Tasks"]
    assert all(action in window._all_actions for action in window._inspector_actions)
    window._inspector_actions[3].trigger()
    assert window._left_tabs.currentWidget() is window.changes_panel


def test_the_page_is_persisted_by_name(window: MainWindow) -> None:
    window._left_tabs.setCurrentWidget(window.message_panel)
    session_controller.save_geometry(window)
    assert app_settings().value("inspector/page") == "messages"
    window._left_tabs.setCurrentIndex(0)
    session_controller.restore_geometry(window)
    assert window._left_tabs.currentWidget() is window.message_panel


def test_a_pre_rail_tab_index_still_restores(window: MainWindow) -> None:
    settings = app_settings()
    settings.remove("inspector/page")
    settings.setValue("inspector/tab", 4)
    session_controller.restore_geometry(window)
    assert window._left_tabs.currentWidget() is window.props_app.tab


def test_show_tasks_opens_the_popover_without_blocking(window: MainWindow, qtbot) -> None:
    window._inspector_actions[-1].trigger()
    qtbot.waitUntil(window.tasks_button.popover.isVisible)
    window.tasks_button.popover.close()
