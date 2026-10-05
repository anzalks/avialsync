"""A status message is coloured by its own severity, never by the one before it.

The Data Streams status label carries a ``follow_palette`` stylesheet so its
severity colour tracks the theme. ``set_status`` used to build the next sheet
from the label's *own* palette, which the previous sheet had pinned, so an info
message shown after a busy one came out in the busy amber: "Status: Ready" in
the caution colour, in the published Dark screenshot (INTERFACE_DESIGN_PLAN
F-04).
"""

from __future__ import annotations

import re

import pytest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from avialsync.ui.theme import THEME_DARK, THEME_LIGHT, _apply, status_color
from avialsync.ui.transport import Transport


@pytest.fixture(autouse=True)
def _restore_appearance():
    """Put the application palette and theme flag back, so later tests see no switch."""
    app = QApplication.instance()
    palette = QPalette(app.palette())
    dark = app.property("avialsync_theme_dark")
    yield
    app.setPalette(palette)
    app.setProperty("avialsync_theme_dark", dark)


def _sheet_colour(widget) -> QColor:
    match = re.search(r"color:\s*(#[0-9a-fA-F]{6})", widget.styleSheet())
    assert match, widget.styleSheet()
    return QColor(match.group(1))


@pytest.mark.parametrize("theme_id", [THEME_DARK, THEME_LIGHT])
def test_info_after_busy_uses_the_info_colour(qtbot, theme_id: str) -> None:
    app = QApplication.instance()
    _apply(app, theme_id, persist=False)
    transport = Transport()
    qtbot.addWidget(transport)
    transport.show()
    qtbot.waitExposed(transport)
    label = transport.evidence._status_label

    transport.set_status("Loading camera_1.mp4", "busy")
    qtbot.wait(20)  # polish: a shown widget's sheet writes its colour into its palette
    busy = _sheet_colour(label)
    transport.set_status("Ready")

    window_text = QApplication.palette().color(QPalette.ColorRole.WindowText)
    assert _sheet_colour(label).name() == window_text.name()
    assert _sheet_colour(label).name() != busy.name()


@pytest.mark.parametrize("severity", ["busy", "warning", "error"])
def test_every_severity_after_another_is_its_own_colour(qtbot, severity: str) -> None:
    app = QApplication.instance()
    _apply(app, THEME_DARK, persist=False)
    transport = Transport()
    qtbot.addWidget(transport)
    transport.show()
    qtbot.waitExposed(transport)
    label = transport.evidence._status_label

    transport.set_status("first", "error" if severity != "error" else "busy")
    qtbot.wait(20)
    transport.set_status("second", severity)

    expected = status_color(QApplication.palette(), severity)
    assert _sheet_colour(label).name() == expected.name()
