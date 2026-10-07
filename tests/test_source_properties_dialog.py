"""Source properties are one click away and always shown (D-183)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.source import VideoMetadata
from avialsync.ui import import_report
from avialsync.ui.main_window import MainWindow
from avialsync.ui.sidebar import SidebarPane


class _Loader:
    def video_metadata(self) -> VideoMetadata:
        return VideoMetadata(
            codec="h264", width=1440, height=1080, pixel_format="gray12le", nominal_fps=30.0
        )


def test_the_card_properties_name_resolution_and_bit_depth(qtbot) -> None:
    pane = SidebarPane()
    qtbot.addWidget(pane)
    pane.add_video("/rec/FaceCam.mp4", {"fps": 30.0, "codec": "h264"})
    pane.set_video_loader("/rec/FaceCam.mp4", _Loader())
    text = pane.properties_text("/rec/FaceCam.mp4")
    assert "1440×1080" in text and "12-bit" in text
    assert pane.properties_text("/rec/missing.mp4") == ""


@pytest.fixture
def window(qapp: QApplication, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    if isValid(win):
        win.close()


def test_properties_open_even_without_an_import_report(window: MainWindow, monkeypatch) -> None:
    """It returned silently whenever no inspection was recorded."""
    shown: list[str] = []
    monkeypatch.setattr(
        import_report.ImportReportDialog,
        "exec",
        lambda self: shown.append(self.windowTitle() + "\n" + self.as_plain_text()) or 0,
    )
    window.sidebar.add_video("/rec/FaceCam.mp4", {"fps": 30.0, "codec": "h264"})
    window.sidebar.set_video_loader("/rec/FaceCam.mp4", _Loader())
    window._inspections.pop("/rec/FaceCam.mp4", None)
    window._show_video_properties("/rec/FaceCam.mp4")
    assert shown and shown[0].startswith("Video Properties — FaceCam.mp4")
    assert "Resolution" in shown[0] and "Bit depth" in shown[0] and "12-bit" in shown[0]
