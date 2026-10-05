"""Status ink follows the live palette and severity after D-170's move."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QPalette
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


@pytest.mark.parametrize("theme_id", [THEME_DARK, THEME_LIGHT])
def test_info_after_busy_uses_the_info_colour(qtbot, theme_id: str) -> None:
    """The status bar's painted ink cannot inherit the previous busy amber."""
    app = QApplication.instance()
    _apply(app, theme_id, persist=False)
    transport = Transport()
    qtbot.addWidget(transport)
    transport.show()
    qtbot.waitExposed(transport)
    line = transport.status_line

    transport.set_status("Loading camera_1.mp4", "busy")
    busy = line.ink_color()
    transport.set_status("Ready")

    window_text = QApplication.palette().color(QPalette.ColorRole.WindowText)
    assert line.ink_color().name() == window_text.name()
    assert line.ink_color().name() != busy.name()
    assert not line.styleSheet()


@pytest.mark.parametrize("severity", ["busy", "warning", "error"])
def test_every_severity_after_another_is_its_own_colour(qtbot, severity: str) -> None:
    """D-170: each status is painted using its own severity and live palette."""
    app = QApplication.instance()
    _apply(app, THEME_DARK, persist=False)
    transport = Transport()
    qtbot.addWidget(transport)
    transport.show()
    qtbot.waitExposed(transport)
    line = transport.status_line

    transport.set_status("first", "error" if severity != "error" else "busy")
    transport.set_status("second", severity)

    expected = status_color(QApplication.palette(), severity)
    assert line.ink_color().name() == expected.name()
