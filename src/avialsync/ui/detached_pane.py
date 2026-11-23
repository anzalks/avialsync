"""Detached workspace windows for splitter panes, cameras, and inspector pages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from avialsync.ui.design_tokens import ControlRole, apply_role, spacing
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow
    from avialsync.ui.video_grid import VideoGrid
    from avialsync.ui.video_pane import VideoPane

__all__ = [
    "DetachedCameraWindow",
    "DetachedPaneWindow",
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


class DetachedPaneWindow(QDialog):
    """Move one pane out of a splitter and restore its exact slot on close."""

    returned = Signal()

    def __init__(
        self,
        title: str,
        pane: QWidget,
        splitter: QSplitter,
        index: int,
        parent: QWidget,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setProperty("av_workspace_window", True)
        self.setWindowTitle(title)
        self.setAccessibleName(tr("Detached {title} pane").format(title=title))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(900, 560)
        self._pane = pane
        self._splitter = splitter
        self._placeholder = QWidget()
        self._placeholder.setObjectName("detached_pane_placeholder")
        self._splitter.replaceWidget(index, self._placeholder)

        self._pane_layout = QVBoxLayout(self)
        self._pane_layout.setContentsMargins(0, 0, 0, 0)
        self._pane_layout.addWidget(pane, 1)
        controls = QHBoxLayout()
        controls.addStretch(1)
        self.return_button = QPushButton(tr("Return to main window"), self)
        apply_role(self.return_button, ControlRole.SECONDARY)
        self.return_button.setAccessibleDescription(
            tr("Put this pane back in its original place in the main workspace.")
        )
        self.return_button.clicked.connect(self.close)
        controls.addWidget(self.return_button)
        self._pane_layout.addLayout(controls)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Reinsert the pane before the detached window is destroyed."""
        index = self._splitter.indexOf(self._placeholder)
        if index >= 0:
            self._pane_layout.removeWidget(self._pane)
            self._splitter.replaceWidget(index, self._pane)
            self._placeholder.deleteLater()
            self.returned.emit()
        super().closeEvent(event)


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
        self.setProperty("av_workspace_window", True)
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
        self.setProperty("av_workspace_window", True)
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
