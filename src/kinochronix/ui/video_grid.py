"""Video grid layout manager."""

from pathlib import Path

from PySide6.QtWidgets import QHBoxLayout, QWidget

from kinochronix.ui.video_pane import VideoPane


class VideoGrid(QWidget):
    """
    Manages N VideoPanes in a horizontal layout.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.panes: list[VideoPane] = []
        self._fullscreen_pane: VideoPane | None = None
        self._paths: list[str] = []

        self.grid_layout = QHBoxLayout(self)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(2)

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel

        self.lbl_empty = QLabel(
            "No videos loaded.\nDrag and drop videos or CSV files here to view.\nDouble-click a video pane to maximize."
        )
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setStyleSheet("color: #888888; font-size: 18px;")
        self.lbl_empty.setMinimumHeight(200)
        self.grid_layout.addWidget(self.lbl_empty)

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
            self.lbl_empty.setVisible(False)
            for pane in self.panes:
                pane.setVisible(pane == self._fullscreen_pane)
            self.grid_layout.addWidget(self._fullscreen_pane)
            return

        # Normal layout
        n = len(self.panes)
        if n == 0:
            self.lbl_empty.setVisible(True)
            self.grid_layout.addWidget(self.lbl_empty)
            return

        self.lbl_empty.setVisible(False)
        for pane in self.panes:
            pane.setVisible(True)
            self.grid_layout.addWidget(pane)

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
