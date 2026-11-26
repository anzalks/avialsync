"""Build the View menu from live actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import QMenu, QMenuBar

from avialsync.core.commands import SetOverlayVisibleCommand
from avialsync.core.settings_schema import setting_for
from avialsync.ui.controllers import calibration_controller, gap_view
from avialsync.ui.i18n import tr
from avialsync.ui.overlay_registry import OVERLAY_LAYERS, layer_for
from avialsync.ui.time_format import TimeDisplayMode

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

Register = Callable[[QAction, str], QAction]


def apply_overlay_state(window: MainWindow) -> None:
    """Push registered visibility to video, 3D, and live action followers."""
    window.video_grid.set_overlay_visibility(window.overlay_state.visibility_for)
    window.tracking_3d_pane.canvas.set_point_labels_visible(
        window.overlay_state.is_visible("tracking.3d_point_labels")
    )
    # Action followers must hear undo as well as clicks. The toggled echo is
    # harmless: _on_overlay_toggled ignores visibility already held.
    for overlay_id, action in getattr(window, "_overlay_actions", {}).items():
        action.setChecked(window.overlay_state.is_visible(overlay_id))


def build_overlays_menu(window: MainWindow, register: Register) -> None:
    """Generate View -> Overlays from the registry, grouped.

    Generated rather than hand-written: a hand-written menu is how the next
    overlay ships without a switch, and every overlay must have one.
    """
    window._overlay_actions = {}
    current_group = ""
    for layer in OVERLAY_LAYERS:
        if current_group and layer.group != current_group:
            window._overlays_menu.addSeparator()
        current_group = layer.group

        action = window._overlays_menu.addAction(layer.label)
        action.setCheckable(True)
        action.setChecked(window.overlay_state.is_visible(layer.overlay_id))
        action.setToolTip(layer.description)
        if layer.locked:
            # Registered and shown, but not switchable. Greyed with the
            # reason in the tooltip, so the exception stays visible rather
            # than becoming folklore.
            action.setEnabled(False)
        else:
            action.toggled.connect(
                lambda checked, oid=layer.overlay_id: window._on_overlay_toggled(oid, checked)
            )
        register(action, "View")
        window._overlay_actions[layer.overlay_id] = action

    window._overlays_menu.addSeparator()
    show_all = window._overlays_menu.addAction(tr("Show All"))
    show_all.triggered.connect(lambda: window._set_all_overlays(True))
    register(show_all, "View")
    hide_all = window._overlays_menu.addAction(tr("Hide All"))
    hide_all.triggered.connect(lambda: window._set_all_overlays(False))
    register(hide_all, "View")

    # Install the resolver now, not on the first toggle. `apply_overlays_to`
    # is what a newly built pane goes through, and it returns early while
    # there is no resolver -- so before this, the first camera of a fresh
    # session kept whatever the canvas happened to construct itself with,
    # and only a session restore or a toggle ever corrected it.
    window._apply_overlay_state()


def overlay_toggled(
    window: MainWindow, overlay_id: str, visible: bool, camera: str | None = None
) -> None:
    """Apply an overlay change and record it as undoable."""
    if not window.overlay_state.set_visible(overlay_id, visible, camera):
        return
    layer = layer_for(overlay_id)
    window._record(
        SetOverlayVisibleCommand(
            overlay_id=overlay_id,
            visible=visible,
            camera=camera,
            display_name=layer.label if layer else overlay_id,
        )
    )
    window._apply_overlay_state()
    if overlay_id in (
        calibration_controller.REPROJECTION_OVERLAY,
        calibration_controller.REPROJECTION_SKELETON_OVERLAY,
    ):
        # Draws with the calibration in force, or offers to find one; never
        # a dialog in front of a checkbox or Show All.
        calibration_controller.reprojection_toggled(window, visible)


def set_all_overlays(window: MainWindow, visible: bool) -> None:
    """Show or hide every overlay that is not locked."""
    for layer in OVERLAY_LAYERS:
        if not layer.locked:
            window._on_overlay_toggled(layer.overlay_id, visible)


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
    # The same choices and names as Preferences: one authority (rule 15).
    font_setting = setting_for("font/preference")
    assert font_setting is not None
    for key, label in zip(font_setting.choices, font_setting.choice_labels, strict=True):
        fa = font_menu.addAction(tr(label))
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
    # Reset Plot Zoom — single authority; QShortcut removed from _setup_shortcuts
    # Overlays: one checkbox per registered layer, generated from the
    # registry so a new overlay cannot ship without one.
    window._overlays_menu = view_menu.addMenu(tr("Overlays"))
    window._build_overlays_menu(_reg)
    window.tracking_3d_pane.install_reprojection_action(
        window._overlay_actions[calibration_controller.REPROJECTION_OVERLAY]
    )
    window.tracking_3d_pane.install_point_labels_action(
        window._overlay_actions["tracking.3d_point_labels"]
    )
    window.wheel_tab.install_overlay_actions(
        window._overlay_actions["tracking.wheel"], window._overlay_actions["tracking.wheel_hidden"]
    )
    window._act_show_original_tracker = view_menu.addAction(tr("Show Original Tracking"))
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

    window._act_detach_3d = view_menu.addAction(tr("Detach 3D View"))
    window._act_detach_3d.setCheckable(True)
    window._act_detach_3d.setToolTip(
        tr("Show the 3D tracking view in a separate window for another display")
    )
    window._act_detach_3d.toggled.connect(window.panel_detachment.set_tracking_3d_detached)
    _reg(window._act_detach_3d, "View")

    window._act_detach_imaging = view_menu.addAction(tr("Detach Imaging"))
    window._act_detach_imaging.setCheckable(True)
    window._act_detach_imaging.setToolTip(
        tr("Show the two-photon imaging pane in a separate window for another display")
    )
    window._act_detach_imaging.toggled.connect(window.panel_detachment.set_imaging_detached)
    _reg(window._act_detach_imaging, "View")
    window._require(
        window._act_detach_imaging,
        lambda: (
            bool(window.imaging_pane.source_paths()) or window.panel_detachment.imaging_detached
        ),
        tr("Load an imaging stack before detaching the imaging pane."),
    )

    window._act_panels_back = view_menu.addAction(tr("Bring Panels Back"))
    window._act_panels_back.setToolTip(
        tr("Re-dock every panel and move any stray window back onto this screen")
    )
    window._act_panels_back.triggered.connect(window._bring_panels_back)
    _reg(window._act_panels_back, "View")
    view_menu.addSeparator()

    window._workspace_menu = view_menu.addMenu(tr("Workspace"))
    window._rebuild_workspace_menu()
    view_menu.addSeparator()


def _view_inspector(window: MainWindow, view_menu: QMenu, _reg: Register) -> None:
    """One action per inspector page, plus secondary pop-out windows."""
    inspector_menu = view_menu.addMenu(tr("Inspector"))
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
    tasks.triggered.connect(lambda: window.tasks_button.show_popover())
    window._inspector_actions.append(_reg(tasks, "View"))
    inspector_menu.addSeparator()
    pop_current = inspector_menu.addAction(tr("Pop Out Current Inspector Page"))
    pop_current.setToolTip(
        tr("Open the active inspector page in a separate window alongside this dock")
    )
    pop_current.triggered.connect(lambda: window.panel_detachment.pop_out_inspector_page())
    _reg(pop_current, "View")
    pop_menu = inspector_menu.addMenu(tr("Pop Out Page"))
    for index in range(nav.count()):
        name = nav.tabText(index)
        pop_act = pop_menu.addAction(tr("Pop Out {page}").format(page=name))
        pop_act.setToolTip(
            tr("Show {page} in its own window while keeping Sources open").format(page=name)
        )
        pop_act.triggered.connect(
            lambda _checked=False, i=index: window.panel_detachment.pop_out_inspector_page(i)
        )
        _reg(pop_act, "View")
    view_menu.addSeparator()


def _view_navigation(window: MainWindow, view_menu: QMenu, _reg: Register) -> None:
    """Offer plot zoom and video fitting commands."""
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

    window._act_collapse_gaps = view_menu.addAction(tr("Collapse Gaps Without Data"))
    window._act_collapse_gaps.setCheckable(True)
    window._act_collapse_gaps.setChecked(gap_view.collapse_enabled())
    window._act_collapse_gaps.setToolTip(
        tr(
            "Skip the time no loaded source recorded anything in, on the timeline and in "
            "playback. Timestamps are unchanged."
        )
    )
    window._act_collapse_gaps.toggled.connect(lambda on: gap_view.set_collapse(window, on))
    _reg(window._act_collapse_gaps, "View")

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
    _install_plot_context_actions(window)


def _install_plot_context_actions(window: MainWindow) -> None:
    ctx_actions = [window._act_reset_zoom]
    mark_range = getattr(window, "_act_mark_range", None)
    if mark_range is not None:
        ctx_actions.append(mark_range)
    window.plot_pane.set_context_actions(ctx_actions)
