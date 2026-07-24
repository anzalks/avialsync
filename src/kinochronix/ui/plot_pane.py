"""Plot rendering pane using pyqtgraph and decimation pyramids."""

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget

from kinochronix.core.pyramid import PyramidReader


class PlotPane(QWidget):
    """
    Data plotting pane.

    Uses pyqtgraph to render decimated signal data from the cache pyramid.
    Includes a vertical playhead cursor.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)

        # Configure pyqtgraph
        pg.setConfigOption("background", "k")
        pg.setConfigOption("foreground", "d")

        self.plot_widget = pg.PlotWidget()
        self.layout().addWidget(self.plot_widget)

        # Cursor line
        self.cursor_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("y", width=2))
        self.plot_widget.addItem(self.cursor_line)

        # State
        self.reader = None
        self.follow_playhead = False

        # Visual items
        self.curve_min = pg.PlotCurveItem(pen=pg.mkPen("c", width=1), connect="finite")
        self.curve_max = pg.PlotCurveItem(pen=pg.mkPen("c", width=1), connect="finite")

        brush = pg.mkBrush(0, 255, 255, 100)
        self.fill = pg.FillBetweenItem(self.curve_min, self.curve_max, brush=brush)

        self.plot_widget.addItem(self.curve_min)
        self.plot_widget.addItem(self.curve_max)
        self.plot_widget.addItem(self.fill)

        # Connect zoom/pan to pyramid query
        self.plot_widget.sigXRangeChanged.connect(self.update_plot)

    def load_source(self, cache_dir: Path, channel_id: str) -> None:
        """Load a data source from cache."""
        self.reader = PyramidReader(cache_dir, channel_id)
        # Reset view range to full bounds
        t, _, _, _ = self.reader._load_level(1)
        if len(t) > 0:
            self.plot_widget.setXRange(float(t[0]), float(t[-1]))
        self.update_plot()

    def update_plot(self) -> None:
        """Query the pyramid for the current view range and update curves."""
        if not self.reader:
            return

        view = self.plot_widget.viewRange()[0]
        t0, t1 = view[0], view[1]

        # max_points is roughly screen width in pixels
        t, vmin, vmax, gap = self.reader.query(t0, t1, max_points=1500)

        if len(t) == 0:
            self.curve_min.setData([], [])
            self.curve_max.setData([], [])
            return

        # Break lines across gaps and handle NaN
        vmin = vmin.copy()
        vmax = vmax.copy()
        vmin[gap] = np.nan
        vmax[gap] = np.nan

        self.curve_min.setData(t, vmin)

        # Optimization: if vmin == vmax (level 1), don't draw max and fill
        if np.array_equal(vmin, vmax, equal_nan=True):
            self.curve_max.setData([], [])
        else:
            self.curve_max.setData(t, vmax)

    def set_cursor(self, t: float) -> None:
        """Update playhead position independently of curve redraws."""
        self.cursor_line.setValue(t)

        if self.follow_playhead:
            view = self.plot_widget.viewRange()[0]
            width = view[1] - view[0]
            if t < view[0] or t > view[1]:
                # Center the playhead
                self.plot_widget.setXRange(t - width / 2, t + width / 2, padding=0)

    def set_follow_playhead(self, follow: bool) -> None:
        """Toggle playhead following mode."""
        self.follow_playhead = follow
