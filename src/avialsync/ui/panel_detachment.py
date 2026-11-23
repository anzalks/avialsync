"""Detachable workspace panes, camera windows, and inspector page pop-outs.

Centralises multi-display window management outside ``MainWindow`` so plots,
the 3D tracking view, two-photon imaging, individual cameras, and secondary
inspector pages (such as Values or Changes alongside Sources) can float onto
another monitor and always return cleanly via ``Bring Panels Back`` or window
shutdown.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QDockWidget, QWidget
from shiboken6 import isValid

from avialsync.ui.detached_pane import (
    DetachedCameraWindow,
    DetachedPaneWindow,
    PopOutInspectorWindow,
    _build_inspector_placeholder,
    bring_onto_screen,
)
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

__all__ = [
    "DetachedCameraWindow",
    "PanelDetachment",
    "PopOutInspectorWindow",
    "bring_onto_screen",
]


class PanelDetachment:
    """Coordinate detached panes, cameras, and popped-out inspector pages."""

    def __init__(self, window: MainWindow) -> None:
        self._window = window
        self.tracking_3d_window: DetachedPaneWindow | None = None
        self.imaging_window: DetachedPaneWindow | None = None
        self.camera_windows: dict[str, DetachedCameraWindow] = {}
        self.inspector_windows: dict[int, PopOutInspectorWindow] = {}
        self._tracking_was_visible = False
        self._imaging_was_visible = False

    def _share_window_actions(self, dialog: QWidget) -> None:
        """Give a detached workspace surface the main window's live shortcuts."""
        actions = getattr(self._window, "_all_actions", None)
        if actions:
            dialog.addActions(list(actions))

    # ── Plots ────────────────────────────────────────────────────────

    def set_plots_detached(self, detached: bool) -> None:
        """Move plots to a separate window or restore their splitter slot."""
        win = self._window
        if not detached:
            dialog = win._detached_plot_window
            if dialog is not None and isValid(dialog):
                dialog.close()
            else:
                self.on_plots_returned()
            return

        existing = win._detached_plot_window
        if existing is not None and isValid(existing):
            existing.show()
            bring_onto_screen(win, existing)
            existing.raise_()
            return

        index = win._v_splitter.indexOf(win.plot_pane)
        if index < 0:
            _set_action_checked_quietly(win._act_detach_plots, False)
            return

        dialog = DetachedPaneWindow(tr("Plots"), win.plot_pane, win._v_splitter, index, win)
        self._share_window_actions(dialog)
        win._detached_plot_window = dialog
        win._plots_detached = True
        dialog.returned.connect(self.on_plots_returned)
        dialog.show()
        bring_onto_screen(win, dialog)
        dialog.raise_()

    def on_plots_returned(self) -> None:
        """Sync window state after the plot window closes."""
        win = self._window
        win._detached_plot_window = None
        win._plots_detached = False
        _set_action_checked_quietly(win._act_detach_plots, False)
        win._pane_proportions.record_all()

    # ── 3D Tracking ──────────────────────────────────────────────────

    @property
    def tracking_3d_detached(self) -> bool:
        return self.tracking_3d_window is not None and isValid(self.tracking_3d_window)

    def tracking_3d_geometry(self) -> QByteArray:
        if self.tracking_3d_window is not None and isValid(self.tracking_3d_window):
            return self.tracking_3d_window.saveGeometry()
        return QByteArray()

    def set_tracking_3d_detached(self, detached: bool) -> None:
        """Float ``Tracking3DPane`` in its own window or re-dock it."""
        win = self._window
        action = getattr(win, "_act_detach_3d", None)
        if not detached:
            if self.tracking_3d_window is not None and isValid(self.tracking_3d_window):
                self.tracking_3d_window.close()
            else:
                self._on_tracking_3d_returned()
            return

        if self.tracking_3d_window is not None and isValid(self.tracking_3d_window):
            self.tracking_3d_window.show()
            bring_onto_screen(win, self.tracking_3d_window)
            self.tracking_3d_window.raise_()
            return

        index = win.imaging_splitter.indexOf(win.tracking_3d_pane)
        if index < 0:
            if action is not None:
                _set_action_checked_quietly(action, False)
            return

        self._tracking_was_visible = not win.tracking_3d_pane.isHidden()
        dialog = DetachedPaneWindow(
            tr("3D View"), win.tracking_3d_pane, win.imaging_splitter, index, win
        )
        self._share_window_actions(dialog)
        win.tracking_3d_pane.setVisible(True)
        self.tracking_3d_window = dialog
        dialog.returned.connect(self._on_tracking_3d_returned)
        dialog.show()
        bring_onto_screen(win, dialog)
        dialog.raise_()

    def _on_tracking_3d_returned(self) -> None:
        win = self._window
        self.tracking_3d_window = None
        action = getattr(win, "_act_detach_3d", None)
        if action is not None:
            _set_action_checked_quietly(action, False)
        win.tracking_3d_pane.setVisible(self._tracking_was_visible)
        win._update_tracking_pane_visibility()
        win._pane_proportions.record_all()

    # ── Imaging ──────────────────────────────────────────────────────

    @property
    def imaging_detached(self) -> bool:
        return self.imaging_window is not None and isValid(self.imaging_window)

    def imaging_geometry(self) -> QByteArray:
        if self.imaging_window is not None and isValid(self.imaging_window):
            return self.imaging_window.saveGeometry()
        return QByteArray()

    def set_imaging_detached(self, detached: bool) -> None:
        """Float ``ImagingPane`` in its own window or re-dock it."""
        win = self._window
        action = getattr(win, "_act_detach_imaging", None)
        if not detached:
            if self.imaging_window is not None and isValid(self.imaging_window):
                self.imaging_window.close()
            else:
                self._on_imaging_returned()
            return

        if self.imaging_window is not None and isValid(self.imaging_window):
            self.imaging_window.show()
            bring_onto_screen(win, self.imaging_window)
            self.imaging_window.raise_()
            return

        index = win.imaging_splitter.indexOf(win.imaging_pane)
        if index < 0:
            if action is not None:
                _set_action_checked_quietly(action, False)
            return

        self._imaging_was_visible = not win.imaging_pane.isHidden()
        dialog = DetachedPaneWindow(
            tr("Imaging"), win.imaging_pane, win.imaging_splitter, index, win
        )
        self._share_window_actions(dialog)
        win.imaging_pane.setVisible(True)
        self.imaging_window = dialog
        dialog.returned.connect(self._on_imaging_returned)
        dialog.show()
        bring_onto_screen(win, dialog)
        dialog.raise_()

    def _on_imaging_returned(self) -> None:
        win = self._window
        self.imaging_window = None
        action = getattr(win, "_act_detach_imaging", None)
        if action is not None:
            _set_action_checked_quietly(action, False)
        has_sources = bool(win.imaging_pane.source_paths())
        win.imaging_pane.setVisible(self._imaging_was_visible or has_sources)
        win._pane_proportions.record_all()

    # ── Per-camera detach ────────────────────────────────────────────

    def is_camera_detached(self, path: str) -> bool:
        dialog = self.camera_windows.get(path)
        return dialog is not None and isValid(dialog)

    def set_camera_detached(self, path: str, detached: bool) -> None:
        """Detach one camera into its own window, or put it back in the grid."""
        win = self._window
        existing = self.camera_windows.get(path)
        if not detached:
            if existing is not None and isValid(existing):
                existing.close()
            else:
                self.camera_windows.pop(path, None)
                win.video_grid.set_pane_detached(path, False)
            return

        if existing is not None and isValid(existing):
            existing.show()
            bring_onto_screen(win, existing)
            existing.raise_()
            return

        pane = win.video_grid.set_pane_detached(path, True)
        if pane is None:
            return
        title = Path(path).name
        dialog = DetachedCameraWindow(title, path, pane, win.video_grid, win)
        self._share_window_actions(dialog)
        self.camera_windows[path] = dialog
        dialog.returned.connect(lambda p: self.camera_windows.pop(p, None))
        dialog.show()
        bring_onto_screen(win, dialog)
        dialog.raise_()

    def on_camera_removed(self, path: str) -> None:
        """Close any detached camera window when its source is unloaded."""
        dialog = self.camera_windows.pop(path, None)
        if dialog is not None and isValid(dialog):
            dialog._restored = True
            dialog.close()

    # ── Secondary inspector pop-out ──────────────────────────────────

    def is_inspector_page_popped(self, index: int) -> bool:
        dialog = self.inspector_windows.get(index)
        return dialog is not None and isValid(dialog)

    def pop_out_inspector_page(self, index: int | None = None) -> None:
        """Open inspector page *index* (default: current page) in a separate window."""
        win = self._window
        nav = win._left_tabs
        target = nav.currentIndex() if index is None else index
        if not 0 <= target < nav.count():
            return
        existing = self.inspector_windows.get(target)
        if existing is not None and isValid(existing):
            existing.show()
            bring_onto_screen(win, existing)
            existing.raise_()
            return

        title = nav.tabText(target)
        placeholder = _build_inspector_placeholder(
            title, lambda idx=target: self.return_inspector_page(idx)
        )
        page = nav.swap_page_widget(target, placeholder)
        if page is None:
            placeholder.deleteLater()
            return
        dialog = PopOutInspectorWindow(target, title, page, placeholder, win)
        self._share_window_actions(dialog)
        self.inspector_windows[target] = dialog
        dialog.returned.connect(lambda idx: self.inspector_windows.pop(idx, None))
        if nav.currentIndex() == target and target != 0 and not self.is_inspector_page_popped(0):
            nav.setCurrentIndex(0)
        dialog.show()
        bring_onto_screen(win, dialog)
        dialog.raise_()

    def return_inspector_page(self, index: int) -> None:
        """Close a popped-out inspector page and restore it to the rail."""
        dialog = self.inspector_windows.get(index)
        if dialog is not None and isValid(dialog):
            dialog.close()

    # ── Bring Panels Back & Shutdown ─────────────────────────────────

    def reattach_all_for_close(self) -> None:
        """Return every detached surface synchronously before window teardown."""
        for index in list(self.inspector_windows):
            dialog = self.inspector_windows.pop(index, None)
            if dialog is not None and isValid(dialog):
                dialog.restore_now()
                dialog.close()
        for path in list(self.camera_windows):
            cam_dialog = self.camera_windows.pop(path, None)
            if cam_dialog is not None and isValid(cam_dialog):
                cam_dialog.restore_now()
                cam_dialog.close()
        self.set_imaging_detached(False)
        self.set_tracking_3d_detached(False)
        self.set_plots_detached(False)

    def bring_panels_back(self) -> None:
        """Re-dock every detached pane, camera, inspector page, and stray dialog."""
        win = self._window
        self.reattach_all_for_close()
        for dock in win.findChildren(QDockWidget):
            if dock.isFloating():
                dock.setFloating(False)
            dock.show()
        for dialog in (
            getattr(win._help_controller, "_preferences_dialog", None),
            getattr(win, "_sync_wizard", None),
            getattr(win, "_identity_window", None),
        ):
            if dialog is not None and isValid(dialog) and dialog.isVisible():
                bring_onto_screen(win, dialog)
        win.notifications.show_success(tr("Panels are back on this window."))


def _set_action_checked_quietly(action: object, checked: bool) -> None:
    set_checked = getattr(action, "setChecked", None)
    block = getattr(action, "blockSignals", None)
    if callable(set_checked) and callable(block):
        was_blocked = block(True)
        set_checked(checked)
        block(was_blocked)
