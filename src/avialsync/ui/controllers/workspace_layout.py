"""Assemble and proportion the workspace from explicitly supplied widgets.

Only widget geometry belongs here. Source state, actions, input filtering,
playback and document mutations stay with their existing owners.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.i18n import tr
from avialsync.ui.inspector_dock import default_dock_width
from avialsync.ui.inspector_nav import InspectorNav
from avialsync.ui.pane_proportions import PaneProportions
from avialsync.ui.splitter import PaneSplitter
from avialsync.ui.workspace_scroll import scroll_when_short

_RESIZE_COALESCE_MS = 16
_EMPTY_PLACEHOLDER_SHARE = 0.001
EmptyLayout = dict[QSplitter, tuple[float, ...] | None]


@dataclass(frozen=True)
class WorkspaceParts:
    """The visible surfaces needed to assemble the existing workspace."""

    inspector: InspectorNav
    videos: QWidget
    tracking: QWidget
    imaging: QWidget
    imaging_splitter: QSplitter
    plots: QWidget
    video_tools: QWidget
    streams: QWidget
    transport: QWidget
    notifications: QWidget


@dataclass(frozen=True)
class WorkspaceLayout:
    """One authority for workspace splitters, proportions and resize coalescing."""

    central_widget: QWidget
    right_widget: QWidget
    video_column: QWidget
    media: QSplitter
    vertical: QSplitter
    content: QSplitter
    imaging: QSplitter
    proportions: PaneProportions
    resize_timer: QTimer

    def mount(self) -> None:
        """Mount after the window's existing initial-policy hooks have run."""
        layout = self.central_widget.layout()
        assert isinstance(layout, QHBoxLayout)
        layout.addWidget(scroll_when_short(self.right_widget))

    def splitters(self) -> tuple[QSplitter, ...]:
        """Return the managed splitters in outer-to-inner order."""
        return self.content, self.vertical, self.media, self.imaging

    def enforce_policy(self) -> None:
        """Reapply non-collapse policy after a saved Qt state is restored."""
        for splitter in self.splitters():
            splitter.setChildrenCollapsible(False)

    def repair_collapsed(self, apply_defaults: Callable[[], None]) -> None:
        """Repair a legacy saved state only if it collapsed a visible pane."""
        for splitter in self.splitters():
            sizes = splitter.sizes()
            visible = [
                index
                for index in range(splitter.count())
                if (child := splitter.widget(index)) is not None and child.isVisible()
            ]
            if any(sizes[index] <= 0 for index in visible):
                apply_defaults()
                return

    def apply_defaults(self, owner: QMainWindow, dock: QDockWidget, nav: InspectorNav) -> None:
        """Seed the existing ratios; the inspector dock stays outside proportion tracking."""
        owner.resizeDocks([dock], [default_dock_width(nav)], Qt.Orientation.Horizontal)
        defaults = (
            (self.content, (620, 160)),
            (self.vertical, (380, 240)),
            (self.media, (750, 250)),
            (self.imaging, (300, 300)),
        )
        for splitter, sizes in defaults:
            splitter.setSizes(list(sizes))
        for splitter, sizes in defaults:
            self.proportions.set_fractions(splitter, sizes)

    def apply_empty(self, empty: bool, saved: EmptyLayout | None) -> EmptyLayout | None:
        """Give the empty drop target room, then restore the same saved ratios."""
        splitters = (self.vertical, self.content)
        if empty:
            if saved is None:
                saved = {splitter: self.proportions.fractions(splitter) for splitter in splitters}
            for splitter in splitters:
                self.proportions.set_fractions(splitter, (1.0, _EMPTY_PLACEHOLDER_SHARE))
        elif saved is not None:
            for splitter, fractions in saved.items():
                if fractions is not None:
                    self.proportions.set_fractions(splitter, fractions)
            saved = None
        else:
            return None
        self.proportions.reapply()
        return saved


def _media_column(parts: WorkspaceParts) -> tuple[QWidget, QSplitter]:
    """Place video tools below their video surface, beside imaging and 3D."""
    column = QWidget()
    layout = QVBoxLayout(column)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(parts.videos, 1)
    layout.addWidget(parts.video_tools)
    media = PaneSplitter(Qt.Orientation.Horizontal)
    media.setAccessibleName(tr("Video and 3D tracking splitter"))
    media.addWidget(column)
    media.addWidget(parts.imaging_splitter)
    media.setStretchFactor(0, 2)
    media.setStretchFactor(1, 1)
    return column, media


def _workspace_column(parts: WorkspaceParts, media: QSplitter) -> tuple[QSplitter, QSplitter]:
    vertical = PaneSplitter(Qt.Orientation.Vertical)
    vertical.addWidget(media)
    vertical.addWidget(parts.plots)
    vertical.setStretchFactor(0, 3)
    vertical.setStretchFactor(1, 1)
    content = PaneSplitter(Qt.Orientation.Vertical)
    content.setAccessibleName(tr("Video, plots, and Data Streams splitter"))
    content.addWidget(vertical)
    content.addWidget(parts.streams)
    content.setStretchFactor(0, 4)
    content.setStretchFactor(1, 1)
    return vertical, content


def _allow_horizontal_shrink(parts: WorkspaceParts, video_column: QWidget) -> None:
    """Preserve vertical policy while letting workspace width fit a compact display."""
    for pane in (
        parts.inspector,
        video_column,
        parts.videos,
        parts.tracking,
        parts.imaging,
        parts.plots,
        parts.video_tools,
        parts.streams,
        parts.transport,
    ):
        pane.setSizePolicy(QSizePolicy.Policy.Ignored, pane.sizePolicy().verticalPolicy())


def create_workspace(owner: QMainWindow, parts: WorkspaceParts) -> WorkspaceLayout:
    """Build the existing widget hierarchy, owned by the window's central widget."""
    central = QWidget()
    owner.setCentralWidget(central)
    central_layout = QHBoxLayout(central)
    central_layout.setContentsMargins(0, 0, 0, 0)
    right = QWidget()
    right_layout = QVBoxLayout(right)
    right_layout.setContentsMargins(0, 0, 0, 0)
    video_column, media = _media_column(parts)
    vertical, content = _workspace_column(parts, media)
    right_layout.addWidget(parts.notifications)
    right_layout.addWidget(content)
    right_layout.addWidget(parts.transport)
    _allow_horizontal_shrink(parts, video_column)
    proportions = PaneProportions(owner)
    proportions.track(content, vertical, media, parts.imaging_splitter)
    timer = QTimer(owner)
    timer.setSingleShot(True)
    timer.setInterval(_RESIZE_COALESCE_MS)
    timer.timeout.connect(proportions.reapply)
    result = WorkspaceLayout(
        central,
        right,
        video_column,
        media,
        vertical,
        content,
        parts.imaging_splitter,
        proportions,
        timer,
    )
    return result


def first_window_size() -> tuple[int, int]:
    """1280 x 800, shrunk to the screen: on a 1366 x 768 laptop the bottom of
    the window, transport included, opened off-screen."""
    from PySide6.QtGui import QGuiApplication

    width, height = 1280, 800
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        width = min(width, max(640, area.width() - 32))
        height = min(height, max(480, area.height() - 32))
    return width, height
