"""Construction and state for one pyramid-backed time-series plot row."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsProxyWidget, QToolButton

from avialview.core.pyramid import PyramidReader
from avialview.ui.plot_sweep import SweepCurveItem

CHANNEL_COLORS = [
    (0, 255, 255),
    (255, 0, 255),
    (255, 255, 0),
    (0, 255, 0),
    (255, 128, 0),
    (128, 128, 255),
    (255, 128, 128),
    (128, 255, 128),
]


@dataclass
class ChannelPlot:
    """UI and cached-data state for a single time-series channel."""

    name: str
    reader: PyramidReader
    plot_item: pg.PlotItem
    curve: SweepCurveItem
    cursor_line: pg.InfiniteLine
    close_button: QToolButton
    close_proxy: QGraphicsProxyWidget
    coverage_region: pg.LinearRegionItem | None = None
    gap_markers: list[pg.InfiniteLine] = field(default_factory=list)
    gap_times: tuple[float, ...] = ()


def create_channel_plot(
    graphics_layout: pg.GraphicsLayoutWidget,
    row: int,
    cache_dir: Path,
    channel_name: str,
    color_index: int,
    close_requested: Callable[[str], None],
) -> ChannelPlot:
    """Create one row without deciding shared X-axis ownership."""
    reader = PyramidReader(cache_dir, channel_name)
    close_button = QToolButton()
    close_button.setText("×")
    close_button.setAutoRaise(True)
    close_button.setFixedSize(18, 18)
    close_button.setAccessibleName(f"Hide plot {channel_name}")
    close_button.setToolTip(f"Hide {channel_name}")
    close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    close_button.clicked.connect(
        lambda _checked=False, channel_id=channel_name: close_requested(channel_id)
    )
    close_proxy = QGraphicsProxyWidget()
    close_proxy.setWidget(close_button)
    graphics_layout.addItem(close_proxy, row=row, col=0)

    plot_item = graphics_layout.addPlot(row=row, col=1)
    plot_item.setLabel("left", channel_name)
    plot_item.setLabel("bottom", "Sweep", units="s")
    plot_item.getAxis("left").setWidth(70)
    plot_item.showGrid(x=True, y=True, alpha=0.3)
    plot_item.setMouseEnabled(x=False, y=False)
    plot_item.enableAutoRange(axis="y")
    plot_item.enableAutoRange(axis="x", enable=False)

    pen = pg.mkPen(color=CHANNEL_COLORS[color_index % len(CHANNEL_COLORS)], width=1.5)
    curve = SweepCurveItem(pen=pen, connect="finite")
    plot_item.addItem(curve)
    cursor_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("y", width=2))
    plot_item.addItem(cursor_line)

    times, _, _, _ = reader._load_level(1)
    coverage_region = None
    if len(times) > 0:
        coverage_region = pg.LinearRegionItem(
            values=[float(times[0]), float(times[-1])],
            movable=False,
            brush=pg.mkBrush(255, 255, 255, 15),
        )
        coverage_region.setZValue(-10)
        plot_item.addItem(coverage_region)

    return ChannelPlot(
        name=channel_name,
        reader=reader,
        plot_item=plot_item,
        curve=curve,
        cursor_line=cursor_line,
        close_button=close_button,
        close_proxy=close_proxy,
        coverage_region=coverage_region,
    )
