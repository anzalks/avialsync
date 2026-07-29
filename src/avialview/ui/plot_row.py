"""Construction and state for one pyramid-backed time-series plot row."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
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
    envelope_upper: SweepCurveItem
    cursor_line: pg.InfiniteLine
    close_button: QToolButton
    close_proxy: QGraphicsProxyWidget
    coverage_region: pg.LinearRegionItem | None = None
    coverage_bounds: tuple[float, float] | None = None
    gap_markers: list[pg.InfiniteLine] = field(default_factory=list)
    gap_times: tuple[float, ...] = ()
    visible: bool = True


def point_budget_for_width(width: int) -> int:
    """Quantize viewport width to avoid re-querying for every resize pixel."""
    bounded_width = max(64, width)
    return min(8192, ((bounded_width + 63) // 64) * 64)


def refresh_channel_plot(
    channel: ChannelPlot,
    t0: float,
    t1: float,
    point_budget: int,
) -> None:
    """Replace envelope boundaries with the appropriate bounded pyramid slice."""
    t, vmin, vmax, gap = channel.reader.query(t0, t1, max_points=point_budget)
    if len(t) == 0:
        channel.curve.setData([], [])
        channel.envelope_upper.setData([], [])
        return
    x = t - t0
    lower = np.asarray(vmin, dtype=np.float64).copy()
    upper = np.asarray(vmax, dtype=np.float64).copy()
    lower[gap] = np.nan
    upper[gap] = np.nan
    channel.curve.setData(x, lower)
    channel.envelope_upper.setData(x, upper)


def update_channel_coverage(
    channel: ChannelPlot,
    sweep_start: float,
    sweep_end: float,
) -> None:
    """Move one cached coverage region into the current sweep coordinates."""
    if not channel.visible or channel.coverage_region is None:
        return
    if channel.coverage_bounds is None:
        channel.coverage_region.hide()
        return
    coverage_start, coverage_end = channel.coverage_bounds
    overlap_start = max(sweep_start, coverage_start)
    overlap_end = min(sweep_end, coverage_end)
    if overlap_end < overlap_start:
        channel.coverage_region.hide()
        return
    channel.coverage_region.setRegion([overlap_start - sweep_start, overlap_end - sweep_start])
    channel.coverage_region.show()


def apply_channel_visibility(channel: ChannelPlot) -> None:
    """Apply the row's authoritative visibility state to both graphics items."""
    maximum_height = 16777215 if channel.visible else 0
    if channel.plot_item.isVisible() != channel.visible:
        channel.plot_item.setVisible(channel.visible)
    if channel.close_proxy.isVisible() != channel.visible:
        channel.close_proxy.setVisible(channel.visible)
    if channel.plot_item.maximumHeight() != maximum_height:
        channel.plot_item.setMaximumHeight(maximum_height)
    if channel.close_proxy.maximumHeight() != maximum_height:
        channel.close_proxy.setMaximumHeight(maximum_height)


def enforce_channel_visibility(channels: list[ChannelPlot]) -> None:
    """Reapply visibility after a graphics-layout geometry change."""
    for channel in channels:
        apply_channel_visibility(channel)


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
    envelope_upper = SweepCurveItem(pen=pen, connect="finite")
    plot_item.addItem(curve)
    plot_item.addItem(envelope_upper)
    cursor_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("y", width=2))
    plot_item.addItem(cursor_line)

    times, _, _, _ = reader._load_level(1)
    coverage_region = None
    coverage_bounds = None
    if len(times) > 0:
        coverage_bounds = (float(times[0]), float(times[-1]))
        coverage_region = pg.LinearRegionItem(
            values=list(coverage_bounds),
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
        envelope_upper=envelope_upper,
        cursor_line=cursor_line,
        close_button=close_button,
        close_proxy=close_proxy,
        coverage_region=coverage_region,
        coverage_bounds=coverage_bounds,
    )
