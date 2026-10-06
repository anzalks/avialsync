"""Buttons that reach a menu command take everything from its action (D-167).

Phase 7 settled that a menu item and a button invoking the same command may not
carry independently written text (rule 15, D-092), and the sidebar kept doing
exactly the thing that rule was written about: "Open Videos" beside a menu
saying "Open Video(s)…". The plot header's "Reset plots" and View's "Reset Plot
Zoom" were one Ctrl+0 command under two names, and Reset Session had no menu
action at all, so the palette, the shortcut editor and the menu bar could not
reach it (INTERFACE_DESIGN_PLAN F-18 – F-20).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from shiboken6 import isValid

from avialsync.ui.i18n import untranslated_calls
from avialsync.ui.main_window import MainWindow
from avialsync.ui.shortcut_overrides import action_id


@pytest.fixture
def window(qapp, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    if isValid(win):
        win.close()


def test_open_and_reset_buttons_are_the_file_menus_actions(window: MainWindow) -> None:
    """D-181: every open button is its File action, visible, with the action's text."""
    sidebar = window.sidebar
    pairs = (
        (sidebar.btn_open_video, window._act_open_video),
        (sidebar.btn_open_sensor, window._act_open_sensor),
        (sidebar.btn_open_imaging, window._act_open_imaging),
        (sidebar.btn_reset_session, window._act_reset_session),
        (sidebar.btn_align, window._act_synchronize),
        (window.empty_state.open_videos_button, window._act_open_video),
        (window.empty_state.open_data_button, window._act_open_sensor),
    )
    for button, action in pairs:
        assert button.action is action
        assert button.text() == action.text()


def test_reset_session_is_a_menu_command(window: MainWindow) -> None:
    assert window._act_reset_session in window._all_actions
    assert window._act_reset_session.toolTip()


def test_the_plot_reset_button_is_the_view_menus_reset(window: MainWindow) -> None:
    assert window.plot_pane.reset_button.action is window._act_reset_zoom
    assert window._act_reset_zoom.shortcut().toString() == "Ctrl+0"


def test_renamed_actions_keep_the_id_a_remapped_shortcut_is_stored_under(
    window: MainWindow,
) -> None:
    """Ids derive from labels, so a rename pins the old one (``av_id``)."""
    assert window._act_open_video.text() == "Open Videos…"
    assert action_id(window._act_open_video) == "file_open_video_s"
    assert window._act_reset_zoom.text() == "Reset Plots"
    assert action_id(window._act_reset_zoom) == "view_reset_plot_zoom"


def test_constructor_and_entry_literals_are_found(tmp_path: Path) -> None:
    """A literal handed to a widget constructor or a combo entry is user-facing too."""
    source = tmp_path / "panel.py"
    source.write_text(
        "QLabel('Signals', self)\n"
        "combo.addItem('Comfortable', 110)\n"
        "form.addRow('Separator:', field)\n"
        "QPushButton('✕')\n"
        "QLabel('—')\n"
        "QLabel(tr('Wrapped'))\n",
        encoding="utf-8",
    )
    found = [text for _line, text in untranslated_calls(source)]
    assert found == ["Signals", "Comfortable", "Separator:"]
