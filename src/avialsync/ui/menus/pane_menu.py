"""The right-click menu on a video pane.

Moved from MainWindow (WINDOW_COMPOSITION_PLAN A5), which keeps a delegator
(D-066); every command it offers goes through the window's own methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu

from avialsync.ui.controllers import custom_marker_controller
from avialsync.ui.i18n import tr
from avialsync.ui.overlay_registry import OVERLAY_LAYERS

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


def show_pane_menu(window: MainWindow, path: str, pos: Any) -> None:
    """Show a per-pane context menu on video right-click."""
    menu = QMenu(window)

    # Delete a hand-placed 3D marker under the pointer. Only outside Fix
    # Tracker, which owns the gesture on points, and only for markers the
    # user placed: a model's prediction is not theirs to delete.
    act_delete_marker = None
    marker_hit = None
    if not window.video_grid.point_edit_mode:
        marker_hit = window.video_grid.custom_marker_at(path, pos)
    if marker_hit is not None:
        act_delete_marker = menu.addAction(tr("Delete 3D marker {name}").format(name=marker_hit[0]))
        menu.addSeparator()

    act_fs = menu.addAction(tr("Fullscreen this camera"))
    act_snap = menu.addAction(tr("Snapshot this camera"))
    menu.addSeparator()
    camera_actions, act_follow = _add_camera_overlays(window, menu, path)
    menu.addSeparator()
    act_props = menu.addAction(tr("Properties…"))
    act_copy = menu.addAction(tr("Copy frame info"))

    chosen = menu.exec(pos)
    if act_delete_marker is not None and chosen == act_delete_marker and marker_hit:
        custom_marker_controller.delete(window, marker_hit[0], marker_hit[1])
        return
    if chosen in camera_actions:
        overlay_id = camera_actions[chosen]
        window._on_overlay_toggled(overlay_id, chosen.isChecked(), camera=path)
        return
    if chosen == act_follow:
        for layer in OVERLAY_LAYERS:
            window.overlay_state.clear_override(layer.overlay_id, path)
        window._apply_overlay_state()
        return
    if chosen == act_fs:
        window.video_grid.toggle_fullscreen(path)
    elif chosen == act_snap:
        window._export_snapshot_for_pane(path)
    elif chosen == act_props:
        window._show_video_properties(path)
    elif chosen == act_copy:
        _copy_frame_info(window, path)


def _add_camera_overlays(
    window: MainWindow, menu: QMenu, path: str
) -> tuple[dict[QAction, str], QAction]:
    """Per-camera overrides, with the same labels as View -> Overlays.

    The View menu sets the default for every camera; this overrides one.
    """
    overlays_menu = menu.addMenu(tr("Overlays on this camera"))
    camera_actions: dict[QAction, str] = {}
    for layer in OVERLAY_LAYERS:
        if layer.locked or not layer.per_camera:
            continue
        act = overlays_menu.addAction(layer.label)
        act.setCheckable(True)
        act.setChecked(window.overlay_state.is_visible(layer.overlay_id, path))
        camera_actions[act] = layer.overlay_id
    overlays_menu.addSeparator()
    return camera_actions, overlays_menu.addAction(tr("Follow the View menu"))


def _copy_frame_info(window: MainWindow, path: str) -> None:
    """Put this camera's current frame index and media time on the clipboard."""
    records = window.video_grid.frame_records_at(window.clock.state.t)
    info_lines = [
        f"path={r['path']}\nframe={r['frame_index']}\nmedia_t={r['media_timestamp']:.6f}"
        for r in records
        if r["path"] == path
    ]
    text = "\n".join(info_lines) if info_lines else f"path={path}"
    clipboard = QApplication.clipboard()
    if clipboard:
        clipboard.setText(text)
