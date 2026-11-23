"""Detachable workspace panes, camera windows, and inspector page pop-outs.

Centralises multi-display window management outside ``MainWindow`` so plots,
the 3D tracking view, two-photon imaging, individual cameras, and secondary
inspector pages (such as Values or Changes alongside Sources) can float onto
another monitor and always return cleanly via ``Bring Panels Back`` or window
shutdown.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from avialsync.ui.design_tokens import ControlRole, apply_role, spacing
from avialsync.ui.detached_pane import DetachedPaneWindow
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow
    from avialsync.ui.video_grid import VideoGrid
    from avialsync.ui.video_pane import VideoPane

__all__ = [
    "DetachedCameraWindow",
    "PanelDetachment",
    "PopOutInspectorWindow",
    "bring_onto_screen",
]


def bring_onto_screen(owner: QWidget, widget: QWidget) -> None:
    """Move *widget* onto *owner*'s screen when it sits off every display."""
    if QGuiApplication.screenAt(widget.frameGeometry().center()) is not None:
        return
    screen = owner.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        return
    available = screen.availableGeometry()
    frame = widget.frameGeometry()
    frame.moveCenter(available.center())
    widget.move(frame.topLeft())


class DetachedCameraWindow(QDialog):
    """Host one ``VideoPane`` in its own window while keeping it synced."""

    returned = Signal(str)

    def __init__(
        self,
        title: str,
        path: str,
        pane: VideoPane,
        grid: VideoGrid,
        parent: QWidget,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._path = path
        self._pane = pane
        self._grid = grid
        self._restored = False
        self.setWindowTitle(title)
        self.setAccessibleName(tr("Detached camera {title}").format(title=title))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(pane, 1)
        pane.setVisible(True)

        controls = QHBoxLayout()
        controls.setContentsMargins(spacing("xs"), spacing("xs"), spacing("xs"), spacing("xs"))
        controls.addStretch(1)
        self.return_button = QPushButton(tr("Return to main window"), self)
        apply_role(self.return_button, ControlRole.SECONDARY)
        self.return_button.setAccessibleDescription(
            tr("Put this camera pane back into the main video grid.")
        )
        self.return_button.clicked.connect(self.close)
        controls.addWidget(self.return_button)
        layout.addLayout(controls)

    def restore_now(self) -> None:
        """Put the pane back into ``VideoGrid`` idempotently."""
        if self._restored:
            return
        self._restored = True
        if isValid(self._pane) and isValid(self._grid):
            lay = self.layout()
            if lay is not None:
                lay.removeWidget(self._pane)
            self._grid.set_pane_detached(self._path, False)
        self.returned.emit(self._path)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Return the camera pane to the grid before destroying this window."""
        self.restore_now()
        super().closeEvent(event)


class PopOutInspectorWindow(QDialog):
    """Show one inspector page in a separate window alongside the main rail."""

    returned = Signal(int)

    def __init__(
        self,
        page_index: int,
        title: str,
        page: QWidget,
        placeholder: QWidget,
        window: MainWindow,
    ) -> None:
        super().__init__(window, Qt.WindowType.Window)
        self._index = page_index
        self._page = page
        self._placeholder = placeholder
        self._window = window
        self._restored = False
        self.setWindowTitle(tr("Inspector — {page}").format(page=title))
        self.setAccessibleName(tr("Detached {page} inspector").format(page=title))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(360, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(page, 1)
        page.setVisible(True)

        controls = QHBoxLayout()
        controls.setContentsMargins(spacing("xs"), spacing("xs"), spacing("xs"), spacing("xs"))
        controls.addStretch(1)
        self.return_button = QPushButton(tr("Return to inspector"), self)
        apply_role(self.return_button, ControlRole.SECONDARY)
        self.return_button.setAccessibleDescription(
            tr("Put this page back into the main inspector dock.")
        )
        self.return_button.clicked.connect(self.close)
        controls.addWidget(self.return_button)
        layout.addLayout(controls)

    def restore_now(self) -> None:
        """Swap the page back into ``InspectorNav`` idempotently."""
        if self._restored:
            return
        self._restored = True
        nav = getattr(self._window, "_left_tabs", None)
        if nav is not None and isValid(nav) and isValid(self._page):
            lay = self.layout()
            if lay is not None:
                lay.removeWidget(self._page)
            nav.swap_page_widget(self._index, self._page)
        if isValid(self._placeholder):
            self._placeholder.deleteLater()
        self.returned.emit(self._index)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Return the inspector page to its rail slot on close."""
        self.restore_now()
        super().closeEvent(event)


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
        from pathlib import Path

        title = Path(path).name
        dialog = DetachedCameraWindow(title, path, pane, win.video_grid, win)
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


def _build_inspector_placeholder(title: str, on_return: object) -> QWidget:
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(spacing("m"), spacing("m"), spacing("m"), spacing("m"))
    layout.setSpacing(spacing("s"))
    layout.addStretch(1)
    note = QLabel(
        tr("{page} is open in a separate window.").format(page=title),
        holder,
    )
    note.setWordWrap(True)
    note.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(note)
    btn = QPushButton(tr("Return {page} here").format(page=title), holder)
    apply_role(btn, ControlRole.SECONDARY)
    btn.setAccessibleDescription(
        tr("Close the separate {page} window and show it in this dock again.").format(page=title)
    )
    if callable(on_return):
        btn.clicked.connect(on_return)
    layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)
    layout.addStretch(1)
    return holder
