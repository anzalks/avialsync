"""Left Sidebar / Inspector Pane."""

from pathlib import Path
from typing import TypeVar

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.inspection import SourceInspection
from avialsync.ui.source_properties import VideoPropertiesPanel

_W = TypeVar("_W", bound=QWidget)


def _widgets_of(layout: QVBoxLayout, kind: type[_W]) -> "list[_W]":
    """Return the layout's direct child widgets of *kind*, skipping empty slots.

    ``QLayout.itemAt`` and ``QLayoutItem.widget`` both return None for a spacer
    or a slot that has been taken; every call site here wants "the real widgets
    of this type", so express that once.
    """
    found: list[_W] = []
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item is None:
            continue
        widget = item.widget()
        if isinstance(widget, kind):
            found.append(widget)
    return found


#: Range of the per-source offset controls, in seconds. A full day either way.
#:
#: It was +/-1 hour, which silently truncated any session whose sources carry a
#: wall-clock time base. An AOL recording is timed as seconds since midnight, so
#: a mid-morning session needs about -34500 s; the spin box clamped that to
#: -3600 and `mapping()` then reported the clamp as fact. Nothing warned, the
#: live view stayed correct because the value is applied with signals blocked,
#: and the wrong number only surfaced on save -- reopening the session put the
#: source hours away from the video. A control that cannot express a legitimate
#: value must not silently substitute one (D-026).
_OFFSET_LIMIT_S = 86_400.0


class SensorInfoWidget(QFrame):
    """Displays metadata and per-channel controls for one loaded sensor CSV."""

    remove_requested = Signal(str)  # whole sensor removed
    channel_remove_requested = Signal(str, str)  # sensor_path, channel_name
    channel_visibility_changed = Signal(str, str, bool)  # sensor_path, channel_name, is_visible
    badge_clicked = Signal(str)  # path
    report_requested = Signal(str)  # path
    # Source-to-master mapping, mirroring VideoInfoWidget.offset_changed (P3.5).
    mapping_changed = Signal(str, float, float)  # path, offset_s, drift_ppm

    def __init__(self, path: str, channels: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self._channels = list(channels)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(3)

        # ── Header: filename + badge + remove whole source ──────────
        header = QHBoxLayout()
        name_lbl = QLabel(Path(path).name)
        name_lbl.setToolTip(path)
        name_lbl.setStyleSheet("font-weight: bold;")

        self._badge_btn = QPushButton("⚠")
        self._badge_btn.setFixedSize(18, 18)
        self._badge_btn.setFlat(True)
        self._badge_btn.setStyleSheet("color: #e9c46a; font-weight: bold;")
        self._badge_btn.setVisible(False)
        self._badge_btn.clicked.connect(lambda: self.badge_clicked.emit(self.path))

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setToolTip("Remove entire sensor source")
        close_btn.clicked.connect(lambda: self.remove_requested.emit(self.path))

        header.addWidget(name_lbl, stretch=1)
        header.addWidget(self._badge_btn)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # ── Metadata: path + channel count ──────────────────────────
        path_lbl = QLabel(path)
        path_lbl.setWordWrap(True)
        layout.addWidget(path_lbl)

        n_ch = len(channels)
        ch_count_lbl = QLabel(f"{n_ch} channel{'s' if n_ch != 1 else ''}")
        layout.addWidget(ch_count_lbl)

        # ── Sync controls: same offset/drift treatment as video (P3.5) ─
        sync_layout = QHBoxLayout()
        sync_layout.addWidget(QLabel("Offset:"))
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-_OFFSET_LIMIT_S, _OFFSET_LIMIT_S)
        self.offset_spin.setDecimals(3)
        self.offset_spin.setSingleStep(0.05)
        self.offset_spin.setSuffix(" s")
        self.offset_spin.setAccessibleName(f"Time offset for {Path(path).name}")
        self.offset_spin.setToolTip(
            "Shift this source against the master clock. Cached samples are never rewritten."
        )
        self.offset_spin.valueChanged.connect(self._on_mapping_changed)
        sync_layout.addWidget(self.offset_spin, stretch=1)

        sync_layout.addWidget(QLabel("Drift:"))
        self.drift_spin = QDoubleSpinBox()
        self.drift_spin.setRange(-100000.0, 100000.0)
        self.drift_spin.setDecimals(1)
        self.drift_spin.setSingleStep(10.0)
        self.drift_spin.setSuffix(" ppm")
        self.drift_spin.setAccessibleName(f"Clock drift for {Path(path).name}")
        self.drift_spin.setToolTip("Rate difference between this source's clock and master time.")
        self.drift_spin.valueChanged.connect(self._on_mapping_changed)
        sync_layout.addWidget(self.drift_spin, stretch=1)
        layout.addLayout(sync_layout)

        # ── Separator ────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # ── Channel Tree ─────────────────────────────────────────────

        self.tree = QTreeWidget()
        self.tree.setColumnCount(1)
        self.tree.setHeaderHidden(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
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
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)

            self._channel_items[ch] = item

        self.tree.itemChanged.connect(self._on_item_changed)

        # ── Report button + Properties panel ─────────────────────────
        report_row = QHBoxLayout()
        self._report_btn = QPushButton("Report…")
        self._report_btn.setVisible(False)
        self._report_btn.clicked.connect(lambda: self.report_requested.emit(self.path))
        report_row.addWidget(self._report_btn)
        report_row.addStretch()
        layout.addLayout(report_row)

        from avialsync.ui.source_properties import SensorPropertiesPanel

        self._props_panel = SensorPropertiesPanel(_make_empty_inspection(path), parent=self)
        layout.addWidget(self._props_panel)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        ch = item.toolTip(0)
        if ch:
            is_visible = item.checkState(0) == Qt.CheckState.Checked
            self.channel_visibility_changed.emit(self.path, ch, is_visible)

    def set_channel_visible(self, channel: str, visible: bool) -> bool:
        """Set a channel checkbox and return whether this source owns it."""
        item = self._channel_items.get(channel)
        if item is None:
            return False
        state = Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked
        item.setCheckState(0, state)
        return True

    def _on_channel_remove(self, sensor_path: str, channel: str) -> None:
        item = self._channel_items.pop(channel, None)
        if item:
            parent = item.parent() or self.tree.invisibleRootItem()
            parent.removeChild(item)
        self.channel_remove_requested.emit(sensor_path, channel)

    def _on_mapping_changed(self, _value: float) -> None:
        self.mapping_changed.emit(self.path, self.offset_spin.value(), self.drift_spin.value())

    def set_mapping(self, offset: float, drift_ppm: float) -> None:
        """Show a restored mapping without re-emitting it back to the caller."""
        for spin, value in ((self.offset_spin, offset), (self.drift_spin, drift_ppm)):
            blocked = spin.blockSignals(True)
            spin.setValue(float(value))
            spin.blockSignals(blocked)

    def mapping(self) -> tuple[float, float]:
        """Return the displayed ``(offset_s, drift_ppm)``."""
        return self.offset_spin.value(), self.drift_spin.value()

    def set_inspection(self, inspection: SourceInspection) -> None:
        """Update badge and properties panel from a SourceInspection."""
        flags = getattr(inspection, "integrity_flags", None)
        if flags and getattr(flags, "any_flag", False):
            tip = "\n".join(flags.flag_labels())
            self._badge_btn.setToolTip(tip)
            self._badge_btn.setVisible(True)
        else:
            self._badge_btn.setVisible(False)
        self._report_btn.setVisible(True)
        self._props_panel.update_inspection(inspection)


def _make_empty_inspection(path: str) -> SourceInspection:

    return SourceInspection(path=path)


class VideoInfoWidget(QFrame):
    """Displays metadata and controls for a single loaded video."""

    remove_requested = Signal(str)  # Emits the file path
    offset_changed = Signal(str, float)  # Emits path, new offset
    visibility_changed = Signal(str, bool)  # Emits path, is_visible
    badge_clicked = Signal(str)  # path

    def __init__(self, path: str, metadata: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Header: Checkbox, Name, and Close button
        from PySide6.QtWidgets import QCheckBox

        header_layout = QHBoxLayout()

        self.visibility_cb = QCheckBox()
        self.visibility_cb.setChecked(True)
        self.visibility_cb.setToolTip("Show/Hide video pane")
        self.visibility_cb.toggled.connect(
            lambda checked: self.visibility_changed.emit(self.path, checked)
        )

        name_lbl = QLabel(Path(path).name)
        name_lbl.setToolTip(path)
        name_lbl.setStyleSheet("font-weight: bold;")

        close_btn = QPushButton("X")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(lambda: self.remove_requested.emit(self.path))

        header_layout.addWidget(self.visibility_cb)
        header_layout.addWidget(name_lbl, stretch=1)
        header_layout.addWidget(close_btn)
        layout.addLayout(header_layout)

        # Metadata
        fps = metadata.get("fps", 0.0)
        codec = metadata.get("codec", "unknown")
        duration = metadata.get("duration", 0.0)
        file_size = metadata.get("file_size_bytes", 0)
        is_vfr = metadata.get("is_vfr", False)
        measured_fps = metadata.get("measured_fps", fps)

        timing = f"VFR {measured_fps:.2f} avg (nominal {fps:.2f})" if is_vfr else f"CFR {fps:.2f}"
        size = f" | {file_size / 1_048_576:.1f} MB" if file_size else ""
        meta_lbl = QLabel(f"{codec.upper()} | {timing} | {duration:.1f}s{size}")
        layout.addWidget(meta_lbl)

        # Sync controls
        sync_layout = QHBoxLayout()
        sync_lbl = QLabel("Offset:")
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-_OFFSET_LIMIT_S, _OFFSET_LIMIT_S)
        self.offset_spin.setDecimals(3)
        self.offset_spin.setSingleStep(0.05)
        self.offset_spin.setSuffix(" s")
        self.offset_spin.valueChanged.connect(self._on_offset_changed)

        sync_layout.addWidget(sync_lbl)
        sync_layout.addWidget(self.offset_spin, stretch=1)
        layout.addLayout(sync_layout)

        # Badge (hidden until inspection is available)
        self._badge_btn = QPushButton("⚠")
        self._badge_btn.setFixedSize(18, 18)
        self._badge_btn.setFlat(True)
        self._badge_btn.setStyleSheet("color: #e9c46a; font-weight: bold;")
        self._badge_btn.setVisible(False)
        self._badge_btn.clicked.connect(lambda: self.badge_clicked.emit(self.path))
        header_layout.insertWidget(2, self._badge_btn)  # between name and close

        self._props_panel = VideoPropertiesPanel(loader=None, parent=self)
        self._loader: object = None
        layout.addWidget(self._props_panel)

    def _on_offset_changed(self, val: float) -> None:
        self.offset_changed.emit(self.path, val)

    def set_loader(self, loader: object) -> None:
        """Attach the VideoStandardLoader for metadata display."""
        self._loader = loader
        from avialsync.ui.source_properties import VideoPropertiesPanel

        self._props_panel.setParent(None)
        self._props_panel.deleteLater()
        self._props_panel = VideoPropertiesPanel(loader=loader, parent=self)
        panel_layout = self.layout()
        if panel_layout is not None:
            panel_layout.addWidget(self._props_panel)

    def set_pane(self, pane: object) -> None:
        """Attach the VideoPane for live mpv property reads."""
        self._props_panel.set_pane(pane)

    def set_inspection(self, inspection: SourceInspection) -> None:
        """Show badge if integrity flags are set."""
        flags = getattr(inspection, "integrity_flags", None)
        if flags and getattr(flags, "any_flag", False):
            tip = "\n".join(flags.flag_labels())
            self._badge_btn.setToolTip(tip)
            self._badge_btn.setVisible(True)
        else:
            self._badge_btn.setVisible(False)


class SidebarPane(QWidget):
    """The left sidebar for file management and metadata."""

    open_video_requested = Signal()
    open_sensor_requested = Signal()

    video_offset_changed = Signal(str, float)
    video_remove_requested = Signal(str)
    video_visibility_changed = Signal(str, bool)
    video_badge_clicked = Signal(str)  # path
    sensor_remove_requested = Signal(str)
    sensor_mapping_changed = Signal(str, float, float)  # path, offset_s, drift_ppm
    sensor_badge_clicked = Signal(str)  # path
    sensor_report_requested = Signal(str)  # path
    channel_remove_requested = Signal(str, str)  # sensor_path, channel_name
    channel_visibility_changed = Signal(str, str, bool)  # sensor_path, channel_name, is_visible
    grid_mode_changed = Signal(bool)  # True = NxN grid, False = strip

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Wide enough for the offset/drift row, narrow enough that the whole
        # window can still be shrunk on a laptop display.
        self.setMinimumWidth(180)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        self.content_layout = QVBoxLayout(scroll_content)
        self.content_layout.setContentsMargins(5, 5, 5, 5)

        # Row 1: Actions
        actions_group = QGroupBox("Open Files")
        actions_layout = QHBoxLayout(actions_group)
        self.btn_open_video = QPushButton("Open Videos")
        self.btn_open_sensor = QPushButton("Open Sensor/Ephys Data")
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

        self._scroll_area.setWidget(scroll_content)
        main_layout.addWidget(self._scroll_area)

    def add_video(self, path: str, metadata: dict) -> None:
        """Add a video info widget to the sidebar."""
        if path in self._video_widgets:
            return

        widget = VideoInfoWidget(path, metadata)
        widget.offset_changed.connect(self.video_offset_changed)
        widget.remove_requested.connect(self.video_remove_requested)
        widget.visibility_changed.connect(self.video_visibility_changed)
        widget.badge_clicked.connect(self.video_badge_clicked)

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
            for placeholder in _widgets_of(self.sensors_layout, QLabel):
                self.sensors_layout.removeWidget(placeholder)
                placeholder.deleteLater()

        widget = SensorInfoWidget(path, channels)
        widget.remove_requested.connect(self.sensor_remove_requested)
        widget.channel_remove_requested.connect(self.channel_remove_requested)
        widget.channel_visibility_changed.connect(self.channel_visibility_changed)
        widget.badge_clicked.connect(self.sensor_badge_clicked)
        widget.report_requested.connect(self.sensor_report_requested)
        widget.mapping_changed.connect(self.sensor_mapping_changed)
        self.sensors_layout.addWidget(widget)

    def set_channel_visible(self, channel: str, visible: bool, source_id: str = "") -> bool:
        """Mirror plot-row visibility to the owning channel checkbox.

        *source_id* disambiguates a channel name shared by several loaded files.
        Without it the first owner wins, which is only safe when the caller
        already knows the name is unique.
        """
        if source_id:
            widget = self.sensor_widget(source_id)
            if widget is not None:
                return widget.set_channel_visible(channel, visible)
            return False
        for widget in _widgets_of(self.sensors_layout, SensorInfoWidget):
            if widget.set_channel_visible(channel, visible):
                return True
        return False

    def remove_sensor(self, path: str) -> None:
        """Remove a sensor info widget."""
        for w in _widgets_of(self.sensors_layout, SensorInfoWidget):
            if True and w.path == path:
                self.sensors_layout.removeWidget(w)
                w.deleteLater()
                break

        if self.sensors_layout.count() == 0:
            self.sensors_layout.addWidget(QLabel("No sensor data loaded."))

    def set_video_loader(self, path: str, loader: object) -> None:
        """Forward loader reference to VideoInfoWidget for properties panel."""
        w = self._video_widgets.get(path)
        if w:
            w.set_loader(loader)

    def set_video_pane(self, path: str, pane: object) -> None:
        """Forward VideoPane reference to VideoInfoWidget for live mpv reads."""
        w = self._video_widgets.get(path)
        if w:
            w.set_pane(pane)

    def set_video_inspection(self, path: str, inspection: SourceInspection) -> None:
        """Forward SourceInspection to the VideoInfoWidget badge."""
        w = self._video_widgets.get(path)
        if w:
            w.set_inspection(inspection)

    def sensor_widget(self, path: str) -> SensorInfoWidget | None:
        """Return the widget owning *path*, or None when it is not loaded."""
        for widget in _widgets_of(self.sensors_layout, SensorInfoWidget):
            if True and widget.path == path:
                return widget
        return None

    def set_sensor_mapping(self, path: str, offset: float, drift_ppm: float) -> None:
        """Show a restored sensor mapping without re-emitting it."""
        widget = self.sensor_widget(path)
        if widget is not None:
            widget.set_mapping(offset, drift_ppm)

    def sensor_mapping(self, path: str) -> tuple[float, float]:
        """Return the displayed ``(offset_s, drift_ppm)`` for *path*."""
        widget = self.sensor_widget(path)
        return widget.mapping() if widget is not None else (0.0, 0.0)

    def set_sensor_inspection(self, path: str, inspection: SourceInspection) -> None:
        """Forward SourceInspection to the SensorInfoWidget badge + panel."""
        for w in _widgets_of(self.sensors_layout, SensorInfoWidget):
            if True and w.path == path:
                w.set_inspection(inspection)
                break
