"""With nothing loaded, the drop target is the most prominent area (D-127).

The plots and Data Streams are placeholders until a recording opens: they are
held at their minimum, and the layout the user had comes back with the first
recording. Order and ratios are asserted, not pixels (fonts differ per
platform).
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from shiboken6 import isValid

from avialsync.ui.controllers import session_controller
from avialsync.ui.main_window import MainWindow


@pytest.fixture
def window(qapp, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1400, 1000)
    win.show()
    qtbot.waitExposed(win)
    win._pane_proportions.reapply()
    yield win
    if isValid(win):
        win.close()


def test_an_empty_window_gives_the_drop_target_the_room(window: MainWindow) -> None:
    videos, plots = window._v_splitter.sizes()
    upper, streams = window._content_splitter.sizes()
    assert window.empty_state.isVisible()
    assert videos > 4 * plots, (videos, plots)
    assert upper > 6 * streams, (upper, streams)
    assert plots <= window.plot_pane.minimumSizeHint().height() + 2


def test_the_users_layout_returns_with_the_first_recording(window: MainWindow, monkeypatch) -> None:
    held = window._empty_layout_saved
    assert held is not None
    wanted = held[window._v_splitter]
    assert wanted is not None and wanted[1] > 0.1, "the kept layout is a real one"

    monkeypatch.setattr(window.video_grid, "pane_paths", lambda: ["/rec/cam.mp4"])
    window._refresh_empty_state()
    window._pane_proportions.reapply()

    videos, plots = window._v_splitter.sizes()
    assert window._empty_layout_saved is None
    assert plots / (videos + plots) == pytest.approx(wanted[1], abs=0.02)


def test_the_empty_layout_is_never_saved_as_the_users(window: MainWindow) -> None:
    settings = QSettings("AvialSync", "AvialSync")
    settings.setValue("splitter/vertical", b"the user's own")

    session_controller.save_geometry(window)

    assert settings.value("splitter/vertical") == b"the user's own"
