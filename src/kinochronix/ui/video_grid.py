"""Video grid layout manager."""

import math
from pathlib import Path

from PySide6.QtWidgets import QGridLayout, QWidget

from kinochronix.ui.video_pane import VideoPane


class VideoGrid(QWidget):
    """
    Manages N VideoPanes in a dynamic grid layout.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.panes: list[VideoPane] = []
        self._fullscreen_pane: VideoPane | None = None
        self._paths: list[str] = []

        self.grid_layout = QGridLayout(self)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(2)

    def add_pane(self, path: str) -> VideoPane:
        """Add a new video pane to the grid and open the video."""
        pane = VideoPane(self)
        pane.double_clicked.connect(self._on_pane_double_clicked)
        self.panes.append(pane)
        self._paths.append(path)

        pane.open(path)
        self._update_layout()
        self._update_labels()
        return pane

    def _update_layout(self) -> None:
        # Clear existing layout
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item.widget():
                self.grid_layout.removeWidget(item.widget())

        # If in fullscreen mode, only show that pane
        if self._fullscreen_pane and self._fullscreen_pane in self.panes:
            for pane in self.panes:
                pane.setVisible(pane == self._fullscreen_pane)
            self.grid_layout.addWidget(self._fullscreen_pane, 0, 0)
            return

        # Normal grid layout
        n = len(self.panes)
        if n == 0:
            return

        cols = math.ceil(math.sqrt(n))

        for i, pane in enumerate(self.panes):
            pane.setVisible(True)
            row = i // cols
            col = i % cols
            self.grid_layout.addWidget(pane, row, col)

    def _update_labels(self) -> None:
        """Update camera labels, disambiguating duplicates."""
        # Find duplicates by filename
        from collections import defaultdict
        name_counts = defaultdict(list)
        for i, p in enumerate(self._paths):
            name_counts[Path(p).name].append(i)

        for i, p in enumerate(self._paths):
            path = Path(p)
            if len(name_counts[path.name]) > 1:
                # Disambiguate with parent directory
                label = f"{path.parent.name}/{path.name}"
            else:
                label = path.name

            # Hide labels if there is only 1 camera and we are not disambiguating
            if len(self.panes) == 1:
                self.panes[i].set_label("")
            else:
                self.panes[i].set_label(label)

    def _on_pane_double_clicked(self, pane: VideoPane) -> None:
        """Toggle fullscreen for the clicked pane."""
        if self._fullscreen_pane == pane:
            self._fullscreen_pane = None
        else:
            self._fullscreen_pane = pane
        self._update_layout()
