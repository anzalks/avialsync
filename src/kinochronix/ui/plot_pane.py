"""Plot rendering pane using pyqtgraph and decimation pyramids."""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QVBoxLayout, QWidget

from kinochronix.core.pyramid import PyramidReader

# Predefined color palette for channels
CHANNEL_COLORS = [
    (0, 255, 255),  # Cyan
    (255, 0, 255),  # Magenta
    (255, 255, 0),  # Yellow
    (0, 255, 0),  # Green
    (255, 128, 0),  # Orange
    (128, 128, 255),  # Light Blue
    (255, 128, 128),  # Pink
    (128, 255, 128),  # Light Green
]


@dataclass
class ChannelPlot:
    """Holds UI and data state for a single time-series channel."""

    name: str
    reader: PyramidReader
    plot_item: pg.PlotItem
    curve: pg.PlotCurveItem
    cursor_line: pg.InfiniteLine
    coverage_region: pg.LinearRegionItem | None = None
    gap_markers: list = field(default_factory=list)  # list[pg.InfiniteLine]


class PlotPane(QWidget):
    """
    Data plotting pane for multiple time-series channels.

    Uses pyqtgraph GraphicsLayoutWidget to stack channels vertically.
    All channels share the same X-axis.
    """

    # Emitted when the set of active readers changes so ReadoutPanel can refresh
    sources_changed = Signal(list)  # list[PyramidReader]
    # Emitted when both measure points are set (t_a, t_b)
    measure_changed = Signal(float, float)
    # Emitted when user picks "Add marker here" from the plot context menu (D-022)
    annotate_at_requested = Signal(float)  # t in master-clock seconds

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        _layout = QVBoxLayout()
        _layout.setContentsMargins(0, 0, 0, 0)
        _layout.setSpacing(0)
        self.setLayout(_layout)

        # Toolbar: Reset Zoom button flush-left, rest of bar empty
        _toolbar = QWidget()
        _tbar = QHBoxLayout(_toolbar)
        _tbar.setContentsMargins(4, 2, 4, 0)
        _tbar.setSpacing(4)
        self._btn_reset_zoom = QPushButton("Reset Zoom")
        self._btn_reset_zoom.setFixedHeight(22)
        self._btn_reset_zoom.setFlat(True)
        self._btn_reset_zoom.setToolTip("Reset plot zoom to full data extent (Ctrl+0)")
        self._btn_reset_zoom.clicked.connect(self.reset_zoom)
        _tbar.addWidget(self._btn_reset_zoom)
        _tbar.addStretch()
        _layout.addWidget(_toolbar)

        # Configure pyqtgraph
        pg.setConfigOption("background", "k")
        pg.setConfigOption("foreground", "d")

        self.graphics_layout = pg.GraphicsLayoutWidget()
        self.graphics_layout.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        _layout.addWidget(self.graphics_layout)

        # State
        self.channels: list[ChannelPlot] = []
        self.follow_playhead = False

        self._annotation_store = None
        self._annotation_items: list[tuple[pg.PlotItem, object]] = []

        # Measure markers (A/B pins for Δ measurement, separate from loop A/B)
        self._measure_a: float | None = None
        self._measure_b: float | None = None
        self._measure_a_lines: list[pg.InfiniteLine] = []
        self._measure_b_lines: list[pg.InfiniteLine] = []

        # We will use the first channel's X axis as the master for linking
        self._master_plot: pg.PlotItem | None = None

        # Extra QAction objects injected by MainWindow (e.g. reset-zoom) so
        # the context menu shares the exact same action instances as the menu bar.
        self._extra_context_actions: list = []

        # Right-click context menu on the plot scene
        self.graphics_layout.scene().sigMouseClicked.connect(self._on_scene_clicked)

    def load_channels(self, cache_dir: Path, channel_names: list[str]) -> None:
        """Load multiple data sources from cache and build plot rows."""
        if not channel_names:
            return

        start_row = len(self.channels)

        for i, ch_name in enumerate(channel_names):
            reader = PyramidReader(cache_dir, ch_name)

            # Create plot item
            plot_item = self.graphics_layout.addPlot(row=start_row + i, col=0)
            plot_item.setLabel("left", ch_name)
            plot_item.getAxis("left").setWidth(70)
            plot_item.showGrid(x=True, y=True, alpha=0.3)

            # Link X-axes
            if self._master_plot is None:
                self._master_plot = plot_item
                # Connect master's range changed to update query
                self._master_plot.sigXRangeChanged.connect(self.update_plots)
            else:
                plot_item.setXLink(self._master_plot)

            # Aesthetics
            color = CHANNEL_COLORS[(start_row + i) % len(CHANNEL_COLORS)]
            pen = pg.mkPen(color=color, width=1.5)

            curve = pg.PlotCurveItem(pen=pen, connect="finite")
            plot_item.addItem(curve)

            # Cursor line
            cursor_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("y", width=2))
            plot_item.addItem(cursor_line)

            # Coverage shading — dim region showing data extent
            t_full, _, _, _ = reader._load_level(1)
            coverage_region = None
            if len(t_full) > 0:
                coverage_region = pg.LinearRegionItem(
                    values=[float(t_full[0]), float(t_full[-1])],
                    movable=False,
                    brush=pg.mkBrush(255, 255, 255, 15),
                )
                coverage_region.setZValue(-10)
                plot_item.addItem(coverage_region)

            self.channels.append(
                ChannelPlot(
                    name=ch_name,
                    reader=reader,
                    plot_item=plot_item,
                    curve=curve,
                    cursor_line=cursor_line,
                    coverage_region=coverage_region,
                )
            )

        self.update_plots()
        self.sources_changed.emit([ch.reader for ch in self.channels])
        self._redraw_annotations()

    def remove_channels(self, cache_dir: Path) -> None:
        """Remove all channels associated with a specific cache_dir (source)."""
        to_remove = [ch for ch in self.channels if ch.reader.cache_dir == cache_dir]
        for ch in to_remove:
            self.graphics_layout.removeItem(ch.plot_item)
            self.channels.remove(ch)

            if self._master_plot == ch.plot_item:
                if self.channels:
                    self._master_plot = self.channels[0].plot_item
                    self._master_plot.sigXRangeChanged.connect(self.update_plots)
                else:
                    self._master_plot = None

        # Update X-links to new master
        if self._master_plot:
            for ch in self.channels:
                if ch.plot_item != self._master_plot:
                    ch.plot_item.setXLink(self._master_plot)

        # We don't automatically update view bounds on remove to preserve UX state
        self.sources_changed.emit([ch.reader for ch in self.channels])
        self._redraw_annotations()

    def remove_channel(self, channel_id: str) -> None:
        """Remove a single channel by its channel_id, regardless of cache_dir."""
        to_remove = [ch for ch in self.channels if ch.reader.channel_id == channel_id]
        for ch in to_remove:
            self.graphics_layout.removeItem(ch.plot_item)
            self.channels.remove(ch)

            if self._master_plot == ch.plot_item:
                if self.channels:
                    self._master_plot = self.channels[0].plot_item
                    self._master_plot.sigXRangeChanged.connect(self.update_plots)
                else:
                    self._master_plot = None

        if self._master_plot:
            for ch in self.channels:
                if ch.plot_item != self._master_plot:
                    ch.plot_item.setXLink(self._master_plot)

        self.sources_changed.emit([ch.reader for ch in self.channels])
        self._redraw_annotations()

    def load_source(self, cache_dir: Path, channel_id: str) -> None:
        """Backwards compatibility for Phase 2 single-channel load."""
        self.load_channels(cache_dir, [channel_id])

    def update_plots(self) -> None:
        """Query the pyramid for the current view range and update all curves."""
        if not self._master_plot or not self.channels:
            return

        view = self._master_plot.viewRange()[0]
        t0, t1 = view[0], view[1]

        for ch in self.channels:
            # max_points is roughly screen width in pixels
            t, vmin, vmax, gap = ch.reader.query(t0, t1, max_points=1500)

            if len(t) == 0:
                ch.curve.setData([], [])
                continue

            # Break lines across gaps and handle NaN
            v_mean = (vmin + vmax) / 2.0
            v_mean[gap] = np.nan

            ch.curve.setData(t, v_mean)

    def set_cursor(self, t: float) -> None:
        """Update playhead position independently of curve redraws on all channels."""
        for ch in self.channels:
            ch.cursor_line.setValue(t)

        if self.follow_playhead and self._master_plot:
            view = self._master_plot.viewRange()[0]
            width = view[1] - view[0]
            if t < view[0] or t > view[1]:
                # Center the playhead
                self._master_plot.setXRange(t - width / 2, t + width / 2, padding=0)

    def set_follow_playhead(self, follow: bool) -> None:
        """Toggle playhead following mode."""
        self.follow_playhead = follow

    def set_channel_visible(self, channel_id: str, visible: bool) -> None:
        """Show or hide a specific channel's plot row."""
        for ch in self.channels:
            if ch.name == channel_id:
                ch.plot_item.setVisible(visible)
                # When showing/hiding, the layout updates automatically
                break

    def reset_zoom(self) -> None:
        """Reset all plot axes to their full data extent."""
        if not self.channels or not self._master_plot:
            return
        t_all = []
        for ch in self.channels:
            t, _, _, _ = ch.reader._load_level(1)
            if len(t) > 0:
                t_all.extend([float(t[0]), float(t[-1])])
        if t_all:
            self._master_plot.setXRange(min(t_all), max(t_all), padding=0.02)
        for ch in self.channels:
            ch.plot_item.enableAutoRange(axis="y")

    def zoom_in(self) -> None:
        """Zoom the X-axis in by ~30 % (+ key, D-022)."""
        if self._master_plot:
            self._master_plot.vb.scaleBy((0.7, 1.0))

    def zoom_out(self) -> None:
        """Zoom the X-axis out by ~40 % (- key, D-022)."""
        if self._master_plot:
            self._master_plot.vb.scaleBy((1.4, 1.0))

    def set_context_actions(self, actions: list) -> None:
        """Register extra QAction objects to appear in the right-click context menu.

        MainWindow passes its own QAction instances (e.g. the View→Reset Zoom
        action) so the context menu shares the exact same object — enabling
        the object-identity test mandated by D-022.
        """
        self._extra_context_actions = list(actions)

    # ── Measure markers ──────────────────────────────────────────────

    def set_measure_a(self, t: float) -> None:
        """Place measure pin A at time *t* on all channels."""
        self._measure_a = t
        self._redraw_measure_lines()
        if self._measure_b is not None:
            self.measure_changed.emit(min(t, self._measure_b), max(t, self._measure_b))

    def set_measure_b(self, t: float) -> None:
        """Place measure pin B at time *t* on all channels."""
        self._measure_b = t
        self._redraw_measure_lines()
        if self._measure_a is not None:
            self.measure_changed.emit(min(self._measure_a, t), max(self._measure_a, t))

    def clear_measure(self) -> None:
        """Remove both measure pins."""
        self._measure_a = None
        self._measure_b = None
        self._redraw_measure_lines()

    def _redraw_measure_lines(self) -> None:
        for line in self._measure_a_lines + self._measure_b_lines:
            for ch in self.channels:
                try:
                    ch.plot_item.removeItem(line)
                except Exception:
                    pass
        self._measure_a_lines.clear()
        self._measure_b_lines.clear()

        pen_a = pg.mkPen(color=(0, 255, 100), width=2, style=Qt.PenStyle.DashLine)
        pen_b = pg.mkPen(color=(255, 80, 80), width=2, style=Qt.PenStyle.DashLine)
        for ch in self.channels:
            if self._measure_a is not None:
                la = pg.InfiniteLine(pos=self._measure_a, angle=90, movable=False, pen=pen_a)
                la.setZValue(5)
                ch.plot_item.addItem(la)
                self._measure_a_lines.append(la)
            if self._measure_b is not None:
                lb = pg.InfiniteLine(pos=self._measure_b, angle=90, movable=False, pen=pen_b)
                lb.setZValue(5)
                ch.plot_item.addItem(lb)
                self._measure_b_lines.append(lb)

    def _on_scene_clicked(self, ev) -> None:
        if ev.button() != Qt.MouseButton.RightButton:
            return
        if not self._master_plot:
            return
        scene_pos = ev.scenePos()
        if not self._master_plot.vb.sceneBoundingRect().contains(scene_pos):
            return
        view_pos = self._master_plot.vb.mapSceneToView(scene_pos)
        t = float(view_pos.x())

        menu = QMenu()

        # Annotate at clicked position (D-022)
        act_annot = menu.addAction(f"Add marker here  ({t:.3f} s)")
        menu.addSeparator()

        # Measure sub-group
        act_a = menu.addAction(f"Set Measure A  ({t:.3f} s)")
        act_b = menu.addAction(f"Set Measure B  ({t:.3f} s)")
        menu.addSeparator()
        act_clear = menu.addAction("Clear Measure")

        # Extra actions injected by MainWindow (e.g. Reset Zoom — same QAction
        # object as the View menu item, verified by identity in tests).
        if self._extra_context_actions:
            menu.addSeparator()
            for extra in self._extra_context_actions:
                menu.addAction(extra)

        chosen = menu.exec(ev.screenPos().toPoint())
        if chosen == act_annot:
            self.annotate_at_requested.emit(t)
        elif chosen == act_a:
            self.set_measure_a(t)
        elif chosen == act_b:
            self.set_measure_b(t)
        elif chosen == act_clear:
            self.clear_measure()
        # Extra actions fire through their own triggered signal — no elif needed.
        ev.accept()

    # ── Gap markers ──────────────────────────────────────────────────

    def set_gap_markers(self, channel_id: str, gap_times: list[float]) -> None:
        """Overlay thin red vertical lines at gap positions for one channel."""
        for ch in self.channels:
            if ch.name != channel_id:
                continue
            for line in ch.gap_markers:
                ch.plot_item.removeItem(line)
            ch.gap_markers.clear()
            pen = pg.mkPen(color=(255, 60, 60), width=1, style=Qt.PenStyle.DotLine)
            for t in gap_times:
                line = pg.InfiniteLine(pos=t, angle=90, movable=False, pen=pen)
                line.setZValue(3)
                ch.plot_item.addItem(line)
                ch.gap_markers.append(line)
            break

    # ── Annotation / misc ────────────────────────────────────────────

    def set_annotation_store(self, store: object) -> None:
        self._annotation_store = store
        self._annotation_store.changed.connect(self._redraw_annotations)
        self._redraw_annotations()

    def set_x_range(self, t0: float, t1: float) -> None:
        """Set the view range of all linked plots."""
        if self._master_plot:
            self._master_plot.setXRange(t0, t1)

    def _redraw_annotations(self) -> None:
        """Draw point and range markers from the annotation store on all channels."""
        for plot_item, item in self._annotation_items:
            plot_item.removeItem(item)
        self._annotation_items.clear()

        if not self._annotation_store:
            return

        from PySide6.QtCore import Qt

        for marker in self._annotation_store.markers:
            c = pg.mkColor(marker.color)
            for ch in self.channels:
                if marker.t_end is None:
                    pen = pg.mkPen(c, width=2, style=Qt.PenStyle.DashLine)
                    line = pg.InfiniteLine(pos=marker.t_start, angle=90, movable=False, pen=pen)
                    ch.plot_item.addItem(line)
                    self._annotation_items.append((ch.plot_item, line))
                else:
                    c_brush = pg.mkColor(marker.color)
                    c_brush.setAlpha(40)
                    region = pg.LinearRegionItem(
                        values=[marker.t_start, marker.t_end],
                        movable=False,
                        brush=c_brush,
                        pen=pg.mkPen(c, width=1, style=Qt.PenStyle.DashLine),
                    )
                    region.setZValue(-5)
                    ch.plot_item.addItem(region)
                    self._annotation_items.append((ch.plot_item, region))
