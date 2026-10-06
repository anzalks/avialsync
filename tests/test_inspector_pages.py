"""Inspector pages: empty states and no sideways scrolling (D-176, DS-8)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.ui.empty_note import EmptyNote
from avialsync.ui.main_window import MainWindow

#: The inspector's default width (main_window), which no page may need more than.
DEFAULT_INSPECTOR_PX = 280


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


def test_every_empty_page_says_what_fills_it(window: MainWindow) -> None:
    """R5: an empty page names what will appear there, and how."""
    nav = window._left_tabs
    for index in range(1, nav.count()):  # Sources leads with its own Open button
        nav.setCurrentIndex(index)
        page = nav.currentWidget()
        notes = [n for n in page.findChildren(EmptyNote) if n.isVisibleTo(page)]
        assert notes, f"the {nav.tabText(index)} page has no empty state"
        assert all(len(n.text().split()) >= 6 for n in notes), "a sentence, not a word"
    assert window.jobs_panel.empty_note.isVisibleTo(window.jobs_panel)
    assert window.sidebar.btn_open_video.action is window._act_open_video
    assert window.message_panel.findChild(EmptyNote).button.action is window._act_open_sensor


@pytest.mark.parametrize("index", range(6))
def test_no_inspector_page_needs_sideways_scrolling(window: MainWindow, index: int) -> None:
    """R3: text wraps or elides; the horizontal bar is a backstop, not a fixture.

    A page's scroll area shows its bar only when the page's *minimum* is wider
    than the viewport, so the minimum is what is held under the 280 px default,
    for every Props kind as well as every page.
    """
    nav = window._left_tabs
    nav.setCurrentIndex(index)
    page = nav.currentWidget()
    kinds = [None]
    if page is window.props_app.tab:
        combo = window.props_app.panel.kind
        kinds = [combo.itemData(i) for i in range(combo.count())]
    for kind in kinds:
        if kind is not None:
            combo.setCurrentIndex(combo.findData(kind))
            QApplication.processEvents()
        width = page.minimumSizeHint().width()
        assert width <= DEFAULT_INSPECTOR_PX, f"{nav.tabText(index)} {kind or ''} needs {width} px"
