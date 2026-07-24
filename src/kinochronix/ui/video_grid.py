"""Video grid layout manager."""

import math
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from kinochronix.ui.video_pane import VideoPane


class VideoGrid(QWidget):
    """Manages N VideoPanes in either a horizontal strip or an NxN grid.

    Uses a single QGridLayout and re-arranges children when the mode
    changes, avoiding the Qt limitation that prevents swapping layouts.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.panes: list[VideoPane] = []
        self._fullscreen_pane: VideoPane | None = None
        self._paths: list[str] = []
        self._grid_mode: bool = False

        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)

        self.lbl_empty = QLabel(
            "No videos loaded.\nDrag and drop videos or CSV "
            "files here.\nDouble-click a pane to maximise."
        )
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setStyleSheet("font-size: 18px;")
        self.lbl_empty.setMinimumHeight(200)
        self._layout.addWidget(self.lbl_empty, 0, 0)

    # ── Public API ────────────────────────────────────────────────────

    def set_grid_mode(self, enabled: bool) -> None:
        """Switch between horizontal-strip and NxN grid layout."""
        if enabled == self._grid_mode:
            return
        self._grid_mode = enabled
        self._relayout()

    def add_pane(self, path: str) -> VideoPane:
        """Add a new video pane to the grid and open the video."""
        pane = VideoPane(self)
        pane.double_clicked.connect(self._on_pane_double_clicked)
        self.panes.append(pane)
        self._paths.append(path)
        pane.open(path)
        self._relayout()
        self._update_labels()
        return pane

    def remove_pane(self, path: str) -> None:
        """Remove a video pane by path."""
        try:
            idx = self._paths.index(path)
        except ValueError:
            return

        pane = self.panes.pop(idx)
        self._paths.pop(idx)

        if self._fullscreen_pane == pane:
            self._fullscreen_pane = None

        self._layout.removeWidget(pane)
        pane.close()
        pane.deleteLater()
        self._relayout()
        self._update_labels()

    def set_offset(self, path: str, offset: float) -> None:
        """Update the time offset for a specific video."""
        try:
            idx = self._paths.index(path)
            self.panes[idx].time_map.offset = offset
        except ValueError:
            pass

    def set_pane_visible(self, path: str, visible: bool) -> None:
        """Show or hide a video pane without unloading it."""
        try:
            idx = self._paths.index(path)
            self.panes[idx].setVisible(visible)
            # The layout will automatically hide the item and reclaim space
        except ValueError:
            pass

    # ── Internal ──────────────────────────────────────────────────────

    def _relayout(self) -> None:
        """Remove all widgets from the grid and re-add them in the
        current arrangement (strip or NxN).  Widgets stay parented to
        *self* the whole time — only their grid position changes."""

        # Remove every widget from the layout without unparenting
        while self._layout.count():
            self._layout.takeAt(0)

        # Reset stretches
        for c in range(self._layout.columnCount()):
            self._layout.setColumnStretch(c, 0)
        for r in range(self._layout.rowCount()):
            self._layout.setRowStretch(r, 0)

        n = len(self.panes)

        # ── Empty state ──────────────────────────────────────────
        if n == 0:
            self.lbl_empty.setVisible(True)
            self._layout.addWidget(self.lbl_empty, 0, 0)
            return

        self.lbl_empty.setVisible(False)

        # ── Fullscreen override ──────────────────────────────────
        if (
            self._fullscreen_pane
            and self._fullscreen_pane in self.panes
        ):
            for pane in self.panes:
                pane.setVisible(pane is self._fullscreen_pane)
            self._layout.addWidget(self._fullscreen_pane, 0, 0)
            self._layout.setColumnStretch(0, 1)
            self._layout.setRowStretch(0, 1)
            return

        # ── Normal: all panes visible ────────────────────────────
        for pane in self.panes:
            pane.setVisible(True)

        if self._grid_mode:
            cols = math.ceil(math.sqrt(n))
            for i, pane in enumerate(self.panes):
                row, col = divmod(i, cols)
                self._layout.addWidget(pane, row, col)
            for c in range(cols):
                self._layout.setColumnStretch(c, 1)
            rows = math.ceil(n / cols)
            for r in range(rows):
                self._layout.setRowStretch(r, 1)
        else:
            # Horizontal strip: all in row 0
            for i, pane in enumerate(self.panes):
                self._layout.addWidget(pane, 0, i)
                self._layout.setColumnStretch(i, 1)
            self._layout.setRowStretch(0, 1)

    def _update_labels(self) -> None:
        """Update camera labels, disambiguating duplicate filenames."""
        from collections import defaultdict

        name_counts: dict[str, list[int]] = defaultdict(list)
        for i, p in enumerate(self._paths):
            name_counts[Path(p).name].append(i)

        for i, p in enumerate(self._paths):
            path = Path(p)
            if len(name_counts[path.name]) > 1:
                label = f"{path.parent.name}/{path.name}"
            else:
                label = path.name

            if len(self.panes) == 1:
                self.panes[i].set_label("")
            else:
                self.panes[i].set_label(label)

    def _on_pane_double_clicked(self, pane: VideoPane) -> None:
        """Toggle fullscreen for the clicked pane."""
        if self._fullscreen_pane is pane:
            self._fullscreen_pane = None
        else:
            self._fullscreen_pane = pane
        self._relayout()
