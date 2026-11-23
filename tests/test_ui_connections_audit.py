"""End-to-end audit of menus, ActionButtons, preconditions, detached shortcuts, and Preferences."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QMetaMethod, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu
from shiboken6 import isValid

from avialsync.core.pyramid import PyramidBuilder
from avialsync.core.settings_schema import setting_for
from avialsync.engine.display_pipeline import SourceFormat
from avialsync.ui import recovery
from avialsync.ui.action_button import ActionButton, ActionCheckBox
from avialsync.ui.app_settings import app_settings
from avialsync.ui.command_palette import CommandPalette
from avialsync.ui.main_window import MainWindow
from avialsync.ui.preferences_dialog import PreferencesDialog, write_setting


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = app_settings()
    store.clear()
    store.sync()
    yield
    store.clear()
    store.sync()


@pytest.fixture(autouse=True)
def isolated_recovery(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    yield target


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1200, 800)
    win.show()
    qapp.processEvents()
    yield win
    if isValid(win):
        win.close()


def _walk_menu_actions(menu: QMenu):
    for act in menu.actions():
        if act.isSeparator():
            continue
        sub = act.menu()
        if sub is not None:
            yield from _walk_menu_actions(sub)
        else:
            yield menu, act


def test_every_menu_action_is_connected_and_reachable_in_command_palette(
    window: MainWindow,
) -> None:
    """Every leaf menu item must have a signal receiver (or action group) and be registered."""
    trig_sig = QMetaMethod.fromSignal(window._act_open_video.triggered)
    tog_sig = QMetaMethod.fromSignal(window._act_fix_tracker.toggled)

    # Dynamic submenus populate on aboutToShow; radio groups connect via QActionGroup.triggered.
    radio_Titles = {"Theme", "Font Size", "Time Display"}
    all_registered = set(window._all_actions)

    for top_act in window.menuBar().actions():
        top_menu = top_act.menu()
        assert top_menu is not None
        top_menu.aboutToShow.emit()
        for parent_menu, act in _walk_menu_actions(top_menu):
            menu_title = parent_menu.title().replace("&", "")
            if menu_title in {"Recent Sessions", "Plugins", "Workspace"}:
                continue
            assert act.text().strip(), f"Blank menu item in {menu_title}"
            if menu_title in radio_Titles:
                assert act.actionGroup() is not None, f"{act.text()} missing QActionGroup"
                continue
            if not act.isEnabled() and act in window._overlay_actions.values():
                # Locked overlay layer (e.g. No Footage placeholder) is intentionally non-toggleable
                assert act in all_registered
                continue
            connected = act.isSignalConnected(trig_sig) or act.isSignalConnected(tog_sig)
            assert connected, f"Menu action '{menu_title} -> {act.text()}' has no slot connected!"
            assert act in all_registered, (
                f"Menu action '{menu_title} -> {act.text()}' missing from _all_actions!"
            )

    registered_labels = {act.text() for act in window._all_actions}
    for expected in (
        "Export Changes…",
        "Export Trimmed Video Clip…",
        "Export Data Slice…",
        "Generate Proxy…",
        "Diagnostics…",
        "Cite AvialSync…",
        "About AvialSync",
    ):
        assert expected in registered_labels, f"{expected} missing from _all_actions"

    # CommandPalette shows enabled commands; adding a marker immediately surfaces Export Changes…
    window.annotation_store.add_point(0.0)
    palette = CommandPalette(list(window._all_actions), window)
    palette_labels = {act.text() for act in palette._actions}
    for expected in ("Export Changes…", "Diagnostics…", "Cite AvialSync…", "About AvialSync"):
        assert expected in palette_labels, f"{expected} missing from CommandPalette"
    window.annotation_store.clear()


def test_every_action_button_and_checkbox_is_bound_to_a_live_action(window: MainWindow) -> None:
    """No ActionButton or ActionCheckBox in MainWindow may be left unbound after startup."""
    from avialsync.ui.empty_note import EmptyNote

    for btn in window.findChildren(ActionButton):
        if type(btn) is not ActionButton and btn.isHidden():
            # Prose-only EmptyNote pages keep their optional _ElidingActionButton hidden.
            continue
        assert btn.action is not None, f"Unbound ActionButton: {btn.objectName() or btn}"
    for box in window.findChildren(ActionCheckBox):
        assert box.action is not None, f"Unbound ActionCheckBox: {box.objectName() or box}"

    # EmptyNote pages with a filling command bind directly to the live menu QAction.
    assert window.readout_panel.empty_note.button.action is window._act_open_sensor
    msg_note = window.message_panel.findChild(EmptyNote)
    assert msg_note is not None and msg_note.button.action is window._act_open_sensor


def test_edit_menu_about_to_show_and_ab_clip_precondition_require_complete_loop(
    window: MainWindow,
) -> None:
    """Setting only I keeps clip export & Mark A-B Range disabled; setting I+O enables both."""
    clip_act = next(a for a in window._all_actions if a.text() == "Export Trimmed Video Clip…")
    window.video_grid._paths.append("/tmp/fake.mp4")
    window.transport.set_bounds(0.0, 10.0)
    window.clock.set_bounds(0.0, 10.0)

    # Set only In-point (I): neither Mark A-B Range nor Export Trimmed Video Clip should enable
    window.player.seek(2.0, exact=True)
    window.transport.ab_in()
    assert not window._act_mark_range.isEnabled()
    assert not clip_act.isEnabled()

    # Set Out-point (O): both enable immediately
    window.player.seek(5.0, exact=True)
    window.transport.ab_out()
    window._edit_menu.aboutToShow.emit()
    assert window._act_mark_range.isEnabled()
    assert clip_act.isEnabled()
    window.video_grid._paths.clear()


def test_detached_windows_receive_playhead_shuttle_and_ethogram_shortcuts(
    window: MainWindow, qapp: QApplication, tmp_path: Path
) -> None:
    """Shortcuts reach the window when a detached Plots or Pop-Out Inspector window has focus."""
    times = np.linspace(0.0, 10.0, 101)
    PyramidBuilder(tmp_path, "sig").build_and_save(times, np.sin(times))
    window.clock.set_bounds(0.0, 10.0)
    window.transport.set_bounds(0.0, 10.0)
    window.plot_pane.set_timeline_bounds(0.0, 10.0)
    window.plot_pane.load_channels(tmp_path, ["sig"])
    window.plot_pane.wait_for_pending_rows()
    window.player.seek(4.0, exact=True)

    # Detach Plots and focus its Return button
    window._act_detach_plots.setChecked(True)
    qapp.processEvents()
    plot_win = window._detached_plot_window
    assert plot_win is not None and plot_win.isVisible()
    assert plot_win.property("av_workspace_window") is True
    assert len(plot_win.actions()) >= len(window._all_actions)

    plot_win.activateWindow()
    plot_win.return_button.setFocus(Qt.FocusReason.MouseFocusReason)
    qapp.processEvents()

    # Press M on the detached plot window -> adds point marker!
    before_count = len(window.annotation_store.markers)
    window._act_detach_plots.parent()  # sanity
    QTest.keyClick(plot_win.return_button, Qt.Key.Key_M)
    qapp.processEvents()
    assert len(window.annotation_store.markers) == before_count + 1

    # Pop out Values inspector page and confirm it shares live actions too
    window.panel_detachment.pop_out_inspector_page(1)
    qapp.processEvents()
    pop_win = window.panel_detachment.inspector_windows[1]
    assert pop_win.property("av_workspace_window") is True
    assert len(pop_win.actions()) >= len(window._all_actions)

    # Modal/non-workspace dialogs (e.g. PreferencesDialog) do NOT carry av_workspace_window
    prefs = PreferencesDialog(window)
    assert not bool(prefs.property("av_workspace_window"))
    prefs.close()
    window.panel_detachment.bring_panels_back()


def test_preferences_live_wiring_for_loop_ab_autosave_point_labels_palette_and_auto_levels(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every Preferences setting updates its live subsystem immediately without a restart."""
    hc = window._help_controller

    # 1. storage/autosave_minutes updates _autosave_timer interval immediately
    write_setting(setting_for("storage/autosave_minutes"), 7)
    hc.on_setting_changed("storage/autosave_minutes")
    assert window._autosave_timer.interval() == 7 * 60_000

    # 2. playback/loop_ab toggles Player._loop_ab_enabled immediately
    assert window.player._loop_ab_enabled is True
    write_setting(setting_for("playback/loop_ab"), False)
    hc.on_setting_changed("playback/loop_ab")
    assert window.player._loop_ab_enabled is False

    # Verify Player does NOT wrap at B when playback/loop_ab is False
    window.transport.set_bounds(0.0, 10.0)
    window.clock.set_bounds(0.0, 10.0)
    window.transport.set_ab_region(2.0, 4.0)
    window.player.seek(3.95, exact=True)
    window.player.set_playing(True)
    window.clock.seek(4.5)
    window.player._on_tick()
    assert window.clock.state.t >= 4.5
    window.player.set_playing(False)

    # Restore loop_ab = True
    write_setting(setting_for("playback/loop_ab"), True)
    hc.on_setting_changed("playback/loop_ab")
    assert window.player._loop_ab_enabled is True

    # 3. overlays/point_labels_default updates overlay_state & View -> Overlays action
    write_setting(setting_for("overlays/point_labels_default"), True)
    hc.on_setting_changed("overlays/point_labels_default")
    assert window.overlay_state.is_visible("tracking.point_labels") is True
    assert window._overlay_actions["tracking.point_labels"].isChecked() is True

    # 4. palette/colour_vision_safe refreshes PlotPane palette without error
    times = np.linspace(0.0, 2.0, 21)
    PyramidBuilder(tmp_path, "ch0").build_and_save(times, np.cos(times))
    window.plot_pane.load_channels(tmp_path, ["ch0"])
    window.plot_pane.wait_for_pending_rows()
    write_setting(setting_for("palette/colour_vision_safe"), False)
    hc.on_setting_changed("palette/colour_vision_safe")

    # 5. theme/preference and font/preference sync View menu radio groups
    write_setting(setting_for("theme/preference"), "light")
    hc.on_setting_changed("theme/preference")
    checked_theme = next(a for a in window._theme_group.actions() if a.isChecked())
    assert checked_theme.data() == "light"

    # 6. video/auto_levels_on_open triggers request_auto for >8-bit video on first format detection
    auto_calls: list[str | None] = []
    from avialsync.ui import video_levels

    monkeypatch.setattr(video_levels, "request_auto", lambda _win, path: auto_calls.append(path))
    write_setting(setting_for("video/auto_levels_on_open"), True)
    window._on_source_format_detected("/cam_12bit.mp4", SourceFormat("gray12le", 12, 1))
    assert auto_calls == ["/cam_12bit.mp4"]
    # 8-bit video does NOT trigger auto levels on open
    window._on_source_format_detected("/cam_8bit.mp4", SourceFormat("yuv420p", 8, 3))
    assert auto_calls == ["/cam_12bit.mp4"]
