"""Left Sidebar / Inspector Pane."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class SensorInfoWidget(QFrame):
    """Displays metadata and per-channel controls for one loaded sensor CSV."""

    remove_requested = Signal(str)  # whole sensor removed
    channel_remove_requested = Signal(str, str)  # sensor_path, channel_name

    def __init__(self, path: str, channels: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self._channels = list(channels)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(3)

        # ── Header: filename + remove whole source ───────────────────
        header = QHBoxLayout()
        name_lbl = QLabel(Path(path).name)
        name_lbl.setToolTip(path)
        name_lbl.setStyleSheet("font-weight: bold; font-size: 12px;")

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setToolTip("Remove entire sensor source")
        close_btn.clicked.connect(lambda: self.remove_requested.emit(self.path))

        header.addWidget(name_lbl, stretch=1)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # ── Metadata: path + channel count ──────────────────────────
        path_lbl = QLabel(path)
        path_lbl.setStyleSheet("font-size: 9px;")
        path_lbl.setWordWrap(True)
        layout.addWidget(path_lbl)

        n_ch = len(channels)
        ch_count_lbl = QLabel(
            f"{n_ch} channel{'s' if n_ch != 1 else ''}"
        )
        ch_count_lbl.setStyleSheet("font-size: 10px;")
        layout.addWidget(ch_count_lbl)

        # ── Separator ────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # ── Channel Tree ─────────────────────────────────────────────
        from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QHeaderView

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.header().resizeSection(1, 24)
        self.tree.setIndentation(12)
        self.tree.setMinimumHeight(120)
        self.tree.setMaximumHeight(250)
        self.tree.setStyleSheet("QTreeWidget { border: 1px solid #444; background: transparent; }")
        layout.addWidget(self.tree)

        self._channel_items: dict[str, QTreeWidgetItem] = {}
        nodes = {"": self.tree.invisibleRootItem()}

        for ch in channels:
            # Grouping by '/' or '.'
            parts = ch.replace(".", "/").split("/")
            parent_path = ""
            for part in parts[:-1]:
                path_key = parent_path + "/" + part if parent_path else part
                if path_key not in nodes:
                    group_item = QTreeWidgetItem(nodes[parent_path])
                    group_item.setText(0, part)
                    font = group_item.font(0)
                    font.setBold(True)
                    group_item.setFont(0, font)
                    group_item.setExpanded(True)
                    nodes[path_key] = group_item
                parent_path = path_key
            
            leaf_part = parts[-1]
            item = QTreeWidgetItem(nodes[parent_path])
            item.setText(0, leaf_part)
            item.setToolTip(0, ch)
            
            rm_btn = QPushButton("×")
            rm_btn.setFixedSize(16, 16)
            rm_btn.setToolTip(f"Remove {ch}")
            rm_btn.setStyleSheet("font-size: 10px; padding: 0;")
            rm_btn.clicked.connect(lambda checked=False, c=ch: self._on_channel_remove(self.path, c))
            self.tree.setItemWidget(item, 1, rm_btn)
            
            self._channel_items[ch] = item

    def _on_channel_remove(self, sensor_path: str, channel: str) -> None:
        item = self._channel_items.pop(channel, None)
        if item:
            parent = item.parent() or self.tree.invisibleRootItem()
            parent.removeChild(item)
        self.channel_remove_requested.emit(sensor_path, channel)


class VideoInfoWidget(QFrame):
    """Displays metadata and controls for a single loaded video."""

    remove_requested = Signal(str)  # Emits the file path
    offset_changed = Signal(str, float)  # Emits path, new offset

    def __init__(self, path: str, metadata: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Header: Name and Close button
        header_layout = QHBoxLayout()
        name_lbl = QLabel(Path(path).name)
        name_lbl.setToolTip(path)
        name_lbl.setStyleSheet("font-weight: bold;")

        close_btn = QPushButton("X")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(lambda: self.remove_requested.emit(self.path))

        header_layout.addWidget(name_lbl, stretch=1)
        header_layout.addWidget(close_btn)
        layout.addLayout(header_layout)

        # Metadata
        fps = metadata.get("fps", 0.0)
        codec = metadata.get("codec", "unknown")
        duration = metadata.get("duration", 0.0)

        meta_lbl = QLabel(
            f"{codec.upper()} | {fps:.2f} fps | {duration:.1f}s"
        )
        meta_lbl.setStyleSheet("font-size: 11px;")
        layout.addWidget(meta_lbl)

        # Sync controls
        sync_layout = QHBoxLayout()
        sync_lbl = QLabel("Offset:")
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-3600.0, 3600.0)
        self.offset_spin.setDecimals(3)
        self.offset_spin.setSingleStep(0.05)
        self.offset_spin.setSuffix(" s")
        self.offset_spin.valueChanged.connect(self._on_offset_changed)

        sync_layout.addWidget(sync_lbl)
        sync_layout.addWidget(self.offset_spin, stretch=1)
        layout.addLayout(sync_layout)

    def _on_offset_changed(self, val: float) -> None:
        self.offset_changed.emit(self.path, val)


class SidebarPane(QWidget):
    """The left sidebar for file management and metadata."""

    open_video_requested = Signal()
    open_sensor_requested = Signal()

    video_offset_changed = Signal(str, float)
    video_remove_requested = Signal(str)
    sensor_remove_requested = Signal(str)
    channel_remove_requested = Signal(str, str)  # sensor_path, channel_name
    grid_mode_changed = Signal(bool)  # True = NxN grid, False = strip

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(250)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        self.content_layout = QVBoxLayout(scroll_content)
        self.content_layout.setContentsMargins(5, 5, 5, 5)

        # Row 1: Actions
        actions_group = QGroupBox("Open Files")
        actions_layout = QHBoxLayout(actions_group)
        self.btn_open_video = QPushButton("Open Videos")
        self.btn_open_sensor = QPushButton("Open Sensor Data")
        self.btn_open_video.clicked.connect(self.open_video_requested)
        self.btn_open_sensor.clicked.connect(self.open_sensor_requested)
        actions_layout.addWidget(self.btn_open_video)
        actions_layout.addWidget(self.btn_open_sensor)
        self.content_layout.addWidget(actions_group)

        # Row 2: Videos — header has an inline "Grid" checkbox
        self.videos_group = QGroupBox()
        videos_top = QHBoxLayout()
        videos_top.setContentsMargins(0, 0, 0, 0)
        videos_title = QLabel("Videos")
        videos_title.setStyleSheet("font-weight: bold;")
        self._grid_chk = QCheckBox("⊞ Grid")
        self._grid_chk.setToolTip("Arrange videos in an NxN grid instead of a horizontal strip")
        self._grid_chk.toggled.connect(self.grid_mode_changed)
        videos_top.addWidget(videos_title)
        videos_top.addStretch()
        videos_top.addWidget(self._grid_chk)
        self.videos_layout = QVBoxLayout(self.videos_group)
        self.videos_layout.setContentsMargins(5, 5, 5, 5)
        self.videos_layout.addLayout(videos_top)
        self.content_layout.addWidget(self.videos_group)
        self._video_widgets: dict[str, VideoInfoWidget] = {}

        # Row 3: Sensors
        self.sensors_group = QGroupBox("Sensor Data")
        self.sensors_layout = QVBoxLayout(self.sensors_group)
        self.sensors_layout.addWidget(QLabel("No sensor data loaded."))
        self.content_layout.addWidget(self.sensors_group)

        self.content_layout.addStretch(1)

        self.scroll.setWidget(scroll_content)
        main_layout.addWidget(self.scroll)

    def add_video(self, path: str, metadata: dict) -> None:
        """Add a video info widget to the sidebar."""
        if path in self._video_widgets:
            return

        widget = VideoInfoWidget(path, metadata)
        widget.offset_changed.connect(self.video_offset_changed)
        widget.remove_requested.connect(self.video_remove_requested)

        self.videos_layout.addWidget(widget)
        self._video_widgets[path] = widget

    def remove_video(self, path: str) -> None:
        """Remove a video info widget."""
        widget = self._video_widgets.pop(path, None)
        if widget:
            self.videos_layout.removeWidget(widget)
            widget.deleteLater()

    def add_sensor(self, path: str, channels: list[str]) -> None:
        """Add a sensor info widget to the sidebar."""
        # Remove placeholder if present
        if self.sensors_layout.count() == 1:
            item = self.sensors_layout.itemAt(0)
            if item.widget() and isinstance(item.widget(), QLabel):
                w = item.widget()
                self.sensors_layout.removeWidget(w)
                w.deleteLater()

        widget = SensorInfoWidget(path, channels)
        widget.remove_requested.connect(self.sensor_remove_requested)
        widget.channel_remove_requested.connect(self.channel_remove_requested)
        self.sensors_layout.addWidget(widget)

    def remove_sensor(self, path: str) -> None:
        """Remove a sensor info widget."""
        for i in range(self.sensors_layout.count()):
            item = self.sensors_layout.itemAt(i)
            w = item.widget()
            if isinstance(w, SensorInfoWidget) and w.path == path:
                self.sensors_layout.removeWidget(w)
                w.deleteLater()
                break

        if self.sensors_layout.count() == 0:
            self.sensors_layout.addWidget(QLabel("No sensor data loaded."))
