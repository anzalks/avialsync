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


def test_empty_status_clears_and_hides_without_bare_prefix(qtbot) -> None:
    """Clearing status with '' or whitespace hides StatusLine instead of rendering 'Status: '."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.show()
    qtbot.waitExposed(transport)

    transport.set_status("Scanning files…")
    assert transport.status_line.isVisible()
    assert "Scanning files" in transport.status_line.text()

    transport.set_status("   ")
    assert not transport.status_line.isVisible()
    assert transport.status_line.text() == ""
    assert transport.status_text() == ""


def test_transient_stall_alert_restores_running_job_status_on_expiry(qtbot) -> None:
    """When a stall alert expires while background work continues, live job status returns."""
    from types import SimpleNamespace

    from PySide6.QtWidgets import QMainWindow

    from avialsync.ui.controllers.window_feedback import WindowFeedback
    from avialsync.ui.feedback import ActivityBar, JobsPanel, NotificationStrip

    owner = QMainWindow()
    qtbot.addWidget(owner)
    transport = Transport(owner)
    jobs: object = SimpleNamespace(
        status_text=lambda: "Importing roi_traces.mat",
        stalled_jobs=lambda: [],
        announced_jobs=lambda: [],
        jobs_changed=SimpleNamespace(connect=lambda *_: None),
        membership_changed=SimpleNamespace(connect=lambda *_: None),
        is_shutting_down=lambda: False,
        jobs=lambda: [],
    )
    feedback = WindowFeedback(
        owner,
        jobs,  # type: ignore[arg-type]
        transport,
        ActivityBar(owner),
        NotificationStrip(owner),
        JobsPanel(owner),
    )

    feedback.ui_stalled(420.0)
    assert "Interface stalled for 0.4 s" in transport.status_text()
    assert transport.status_line.text().startswith("Error:")

    transport.status_line._on_clear_timeout()
    assert transport.status_text() == "Importing roi_traces.mat"
    assert transport.status_line.text().startswith("Working:")
