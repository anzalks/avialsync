"""Plot rendering pane using pyqtgraph and decimation pyramids."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

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
    curve_min: pg.PlotCurveItem
    curve_max: pg.PlotCurveItem
    fill: pg.FillBetweenItem
    cursor_line: pg.InfiniteLine
    coverage_region: pg.LinearRegionItem | None = None


class PlotPane(QWidget):
    """
    Data plotting pane for multiple time-series channels.

    Uses pyqtgraph GraphicsLayoutWidget to stack channels vertically.
    All channels share the same X-axis.
    """

    # Emitted when the set of active readers changes so ReadoutPanel can refresh
    sources_changed = Signal(list)  # list[PyramidReader]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)

        # Configure pyqtgraph
        pg.setConfigOption("background", "k")
        pg.setConfigOption("foreground", "d")

        self.graphics_layout = pg.GraphicsLayoutWidget()
        self.layout().addWidget(self.graphics_layout)

        # State
        self.channels: list[ChannelPlot] = []
        self.follow_playhead = False

        # We will use the first channel's X axis as the master for linking
        self._master_plot: pg.PlotItem | None = None

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
            pen = pg.mkPen(color=color, width=1)
            brush = pg.mkBrush(*color, 100)

            curve_min = pg.PlotCurveItem(pen=pen, connect="finite")
            curve_max = pg.PlotCurveItem(pen=pen, connect="finite")
            fill = pg.FillBetweenItem(curve_min, curve_max, brush=brush)

            plot_item.addItem(curve_min)
            plot_item.addItem(curve_max)
            plot_item.addItem(fill)

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
                    curve_min=curve_min,
                    curve_max=curve_max,
                    fill=fill,
                    cursor_line=cursor_line,
                    coverage_region=coverage_region,
                )
            )

        # Reset view range to full bounds using the master plot if it's the first source
        if self._master_plot and start_row == 0 and self.channels:
            t, _, _, _ = self.channels[0].reader._load_level(1)
            if len(t) > 0:
                self._master_plot.setXRange(float(t[0]), float(t[-1]))

        self.update_plots()
        self.sources_changed.emit([ch.reader for ch in self.channels])

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
                ch.curve_min.setData([], [])
                ch.curve_max.setData([], [])
                continue

            # Break lines across gaps and handle NaN
            vmin = vmin.copy()
            vmax = vmax.copy()
            vmin[gap] = np.nan
            vmax[gap] = np.nan

            ch.curve_min.setData(t, vmin)

            # Optimization: if vmin == vmax (level 1), don't draw max and fill
            if np.array_equal(vmin, vmax, equal_nan=True):
                ch.curve_max.setData([], [])
            else:
                ch.curve_max.setData(t, vmax)

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
            self._master_plot.setXRange(
                min(t_all), max(t_all), padding=0.02
            )
        for ch in self.channels:
            ch.plot_item.enableAutoRange(axis="y")
