"""Build the View menu from live actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import QMenu, QMenuBar

from avialsync.ui.controllers import calibration_controller
from avialsync.ui.i18n import tr
from avialsync.ui.time_format import TimeDisplayMode

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

Register = Callable[[QAction, str], QAction]


def build_view_menu(window: MainWindow, menu: QMenuBar, _reg: Register) -> QMenu:
    """Create View actions without duplicating their QAction identity."""
    view_menu = menu.addMenu(tr("View"))
    _view_modes(window, view_menu, _reg)
    _view_overlays(window, view_menu, _reg)
    _view_panels(window, view_menu, _reg)
    _view_inspector(window, view_menu, _reg)
    _view_navigation(window, view_menu, _reg)
    return view_menu


def _view_modes(window: MainWindow, view_menu: QMenu, _reg: Register) -> None:
    """Offer appearance and time display modes."""
    theme_menu = view_menu.addMenu(tr("Theme"))
    window._theme_group = QActionGroup(window)
    for label, key in [("System", "system"), ("Dark", "dark"), ("Light", "light")]:
        ta = theme_menu.addAction(label)
        ta.setCheckable(True)
        ta.setData(key)
        window._theme_group.addAction(ta)
    window._theme_group.triggered.connect(window._on_theme_selected)
    window._sync_theme_menu()

    font_menu = view_menu.addMenu(tr("Font Size"))
    window._font_size_group = QActionGroup(window)
    for label, key in [
        ("System", "system"),
        ("Small", "small"),
        ("Medium", "medium"),
        ("Large", "large"),
    ]:
        fa = font_menu.addAction(label)
        fa.setCheckable(True)
        fa.setData(key)
        window._font_size_group.addAction(fa)
    window._font_size_group.triggered.connect(window._on_font_size_selected)
    window._sync_font_size_menu()

    time_menu = view_menu.addMenu(tr("Time Display"))
    window._time_mode_group = QActionGroup(window)
    for label, mode in [
        ("Relative (HH:MM:SS)", TimeDisplayMode.RELATIVE),
        ("UTC", TimeDisplayMode.UTC),
        ("Local time of day", TimeDisplayMode.LOCAL_TOD),
    ]:
        ta = time_menu.addAction(label)
        ta.setCheckable(True)
        ta.setData(mode)
        ta.setChecked(mode == TimeDisplayMode.RELATIVE)
        window._time_mode_group.addAction(ta)
    window._time_mode_group.triggered.connect(lambda a: window._set_time_mode(a.data()))

    view_menu.addSeparator()


def _view_overlays(window: MainWindow, view_menu: QMenu, _reg: Register) -> None:
    """Offer registered overlays and original tracker."""
    # Reset Plot Zoom — single authority (D-022.1); QShortcut removed from _setup_shortcuts
    # Overlays: one checkbox per registered layer, generated from the
    # registry so a new overlay cannot ship without one (D-090).
    window._overlays_menu = view_menu.addMenu(tr("Overlays"))
    window._build_overlays_menu(_reg)
    window.tracking_3d_pane.install_reprojection_action(
        window._overlay_actions[calibration_controller.REPROJECTION_OVERLAY]
    )
    window.wheel_tab.install_overlay_actions(
        window._overlay_actions["tracking.wheel"], window._overlay_actions["tracking.wheel_hidden"]
    )
    window._act_show_original_tracker = view_menu.addAction(tr("Play original"))
    window._act_show_original_tracker.setCheckable(True)
    window._act_show_original_tracker.triggered.connect(window._set_show_original_tracker)
    _reg(window._act_show_original_tracker, "View")
    window._act_show_original_tracker.setToolTip(
        tr("Draw the tracking the model predicted, ignoring accepted identity swaps")
    )
    window.view_toolbar.install_original_tracker_action(window._act_show_original_tracker)
    window._require(
        window._act_show_original_tracker,
        lambda: bool(window._pose_schemas),
        tr("Import a pose source before comparing the original tracker."),
    )


def _view_panels(window: MainWindow, view_menu: QMenu, _reg: Register) -> None:
    """Offer detachable panes and saved workspaces."""
    window._act_detach_plots = view_menu.addAction(tr("Detach Plots"))
    window._act_detach_plots.setCheckable(True)
    window._act_detach_plots.setToolTip(
        tr("Show the plot pane in a separate window for another display")
    )
    window._act_detach_plots.toggled.connect(window._set_plots_detached)
    _reg(window._act_detach_plots, "View")

    window._act_panels_back = view_menu.addAction(tr("Bring Panels Back"))
    window._act_panels_back.setToolTip(
        tr("Re-dock every panel and move any stray window back onto this screen")
    )
    window._act_panels_back.triggered.connect(window._bring_panels_back)
    _reg(window._act_panels_back, "View")
    # Kept in the menu and nowhere else. Attaching a panel belongs on the
    # panel -- its title bar carries that button -- and this is only the
    # last resort for the one case the panel's own button cannot serve: a
    # window on a screen that is no longer there to click.
    view_menu.addSeparator()

    # Workspaces: a session is looked at in more than one way, and
    # rearranging the splitters each time is friction enough to stop
    # people doing it (WP-11).
    window._workspace_menu = view_menu.addMenu(tr("Workspace"))
    window._rebuild_workspace_menu()
    view_menu.addSeparator()


def _view_inspector(window: MainWindow, view_menu: QMenu, _reg: Register) -> None:
    """One action per inspector page, so the palette and menu reach each (D-172)."""
    inspector_menu = view_menu.addMenu(tr("Inspector"))
    # The dock's own toggle: shown, hidden, or floating (D-180).
    inspector_menu.addAction(_reg(window.inspector_dock.toggleViewAction(), "View"))
    inspector_menu.addSeparator()
    nav = window._left_tabs
    window._inspector_actions = []
    for index in range(nav.count()):
        name = nav.tabText(index)
        action = inspector_menu.addAction(tr("Show {page}").format(page=name))
        action.setToolTip(tr("Show the {page} page in the inspector").format(page=name))
        action.triggered.connect(lambda _checked=False, i=index: nav.setCurrentIndex(i))
        window._inspector_actions.append(_reg(action, "View"))
    tasks = inspector_menu.addAction(tr("Show Tasks"))
    tasks.setToolTip(tr("Show running and recently finished background tasks"))
    # Late-bound: the status bar is built after the menus.
    tasks.triggered.connect(lambda: window.tasks_button.show_popover())
    window._inspector_actions.append(_reg(tasks, "View"))
    view_menu.addSeparator()


def _view_navigation(window: MainWindow, view_menu: QMenu, _reg: Register) -> None:
    """Offer plot zoom and video fitting commands."""
    # The plot pane's own action, so the button under the plots is this same
    # command. Renamed from "Reset Plot Zoom": it resets the time span too.
    window._act_reset_zoom = window.plot_pane.reset_action
    view_menu.addAction(window._act_reset_zoom)
    window._act_reset_zoom.setProperty("av_id", "view_reset_plot_zoom")
    window._act_reset_zoom.setShortcut(QKeySequence("Ctrl+0"))
    _reg(window._act_reset_zoom, "View")
    window._require(
        window._act_reset_zoom,
        lambda: bool(window.plot_pane.channels),
        tr("There are no plots to reset until data is loaded."),
    )

    # Fit All Videos: every camera back to the whole frame, 1.00x, unpanned --
    # what each pane's own reset button does, for all of them at once.
    window._act_fit_videos = view_menu.addAction(tr("Fit All Videos"))
    window._act_fit_videos.setShortcut(QKeySequence("Ctrl+Shift+0"))
    window._act_fit_videos.setToolTip(
        tr("Show every camera's whole frame again: zoom 1.00x, no pan (Ctrl+Shift+0)")
    )
    window._act_fit_videos.triggered.connect(window.video_grid.reset_all_views)
    _reg(window._act_fit_videos, "View")
    window._require(
        window._act_fit_videos,
        lambda: bool(window.video_grid.pane_paths()),
        tr("There are no videos to fit until one is loaded."),
    )
    window.view_toolbar.install_fit_videos_action(window._act_fit_videos)

    # Fullscreen toggle — StandardKey.FullScreen = F11 / Ctrl+Cmd+F on macOS (D-022.2)
    window._act_fullscreen = view_menu.addAction(tr("Fullscreen"))
    window._act_fullscreen.setShortcut(QKeySequence(QKeySequence.StandardKey.FullScreen))
    window._act_fullscreen.triggered.connect(window._toggle_fullscreen)
    _reg(window._act_fullscreen, "View")
    window._act_fullscreen.setToolTip(tr("Show the selected camera alone, or every camera again"))
    window.view_toolbar.install_fullscreen_action(window._act_fullscreen)
    window._require(
        window._act_fullscreen,
        lambda: bool(window.video_grid._paths),
        tr("Load a video — fullscreen applies to a camera pane."),
    )

    # Pass reset-zoom action to plot pane so the context menu uses the same object (D-022)
    window.plot_pane.set_context_actions([window._act_reset_zoom])
