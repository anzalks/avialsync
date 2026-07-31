"""Construction and state for one pyramid-backed time-series plot row."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsProxyWidget, QToolButton

from avialview.core.channel_reader import MappedChannelReader
from avialview.core.pyramid import PyramidReader
from avialview.core.timeline import TimeMap
from avialview.ui.plot_sweep import SweepCurveItem

CHANNEL_COLORS = [(72, 169, 232), (87, 194, 143), (218, 160, 84), (174, 132, 222)]

Y_FIT_ONCE = "fit_once"
Y_AUTO = "auto"
Y_MANUAL = "manual"


@dataclass
class ChannelPlot:
    """UI and cached-data state for a single time-series channel."""

    name: str
    reader: MappedChannelReader
    plot_item: pg.PlotItem
    curve: SweepCurveItem
    envelope_upper: SweepCurveItem
    envelope_fill: pg.FillBetweenItem
    retained_curve: SweepCurveItem
    retained_upper: SweepCurveItem
    cursor_line: pg.InfiniteLine
    close_button: QToolButton
    close_proxy: QGraphicsProxyWidget
    coverage_region: pg.LinearRegionItem | None = None
    coverage_bounds: tuple[float, float] | None = None
    gap_markers: list[pg.InfiniteLine] = field(default_factory=list)
    gap_times: tuple[float, ...] = ()
    unit: str = ""
    y_mode: str = Y_FIT_ONCE
    y_range: tuple[float, float] | None = None
    row_height: int = 110
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

    # PyQtGraph's FillBetweenItem draws garbage to 0,0 when it encounters NaNs.
    # If the pyramid level hasn't diverged (vmin == vmax), hide the fill entirely.
    has_envelope = not np.array_equal(vmin, vmax, equal_nan=True)
    channel.envelope_fill.setVisible(has_envelope)

    if channel.y_mode == Y_AUTO:
        fit_channel_y(channel)


def retain_channel_plot(channel: ChannelPlot) -> None:
    """Keep one previous page for Sweep overwrite without retaining unbounded history."""
    x, lower = channel.curve.getData()
    _, upper = channel.envelope_upper.getData()
    if x is None or lower is None or upper is None:
        channel.retained_curve.setData([], [])
        channel.retained_upper.setData([], [])
        return
    channel.retained_curve.setData(np.asarray(x).copy(), np.asarray(lower).copy())
    channel.retained_upper.setData(np.asarray(x).copy(), np.asarray(upper).copy())


def set_channel_unit(channel: ChannelPlot, unit: str) -> None:
    """Show a channel's unit in the fixed left-axis gutter."""
    channel.unit = unit
    _update_channel_gutter(channel)


def fit_channel_y(channel: ChannelPlot) -> None:
    """Fit a stable finite Y range from the currently loaded bounded page."""
    _, lower = channel.curve.getData()
    _, upper = channel.envelope_upper.getData()
    if lower is None or upper is None:
        return
    values = np.concatenate((np.asarray(lower), np.asarray(upper)))
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return
    low, high = float(values.min()), float(values.max())
    if np.isclose(low, high):
        pad = max(1.0, abs(low) * 0.1)
    else:
        pad = (high - low) * 0.08
    channel.y_range = (low - pad, high + pad)
    channel.plot_item.setYRange(*channel.y_range, padding=0)
    channel.plot_item.enableAutoRange(axis="y", enable=False)
    _update_channel_gutter(channel)


def _update_channel_gutter(channel: ChannelPlot) -> None:
    """Keep name, unit, and stable scale together in the fixed row gutter."""
    lines = [channel.name]
    if channel.unit:
        lines.append(channel.unit)
    if channel.y_range is not None:
        low, high = channel.y_range
        lines.append(f"{low:.3g}…{high:.3g}")
    channel.plot_item.setLabel("left", "\n".join(lines))


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
    minimum_height = channel.row_height if channel.visible else 0
    maximum_height = 16777215 if channel.visible else 0
    if channel.plot_item.isVisible() != channel.visible:
        channel.plot_item.setVisible(channel.visible)
    if channel.close_proxy.isVisible() != channel.visible:
        channel.close_proxy.setVisible(channel.visible)
    if channel.plot_item.minimumHeight() != minimum_height:
        channel.plot_item.setMinimumHeight(minimum_height)
    if channel.plot_item.maximumHeight() != maximum_height:
        channel.plot_item.setMaximumHeight(maximum_height)
    if channel.close_proxy.minimumHeight() != minimum_height:
        channel.close_proxy.setMinimumHeight(minimum_height)
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
    time_map: TimeMap | None = None,
    source_id: str = "",
) -> ChannelPlot:
    """Create one row without deciding shared X-axis ownership.

    The row always reads through a :class:`MappedChannelReader`, so every time it
    handles is master time regardless of the source's own clock.
    """
    reader = MappedChannelReader(PyramidReader(cache_dir, channel_name), time_map, source_id)
    close_button = QToolButton()
    close_button.setText("×")
    close_button.setAutoRaise(True)
    close_button.setFixedSize(18, 18)
    close_button.setAccessibleName(f"Hide plot {channel_name}")
    close_button.setToolTip(f"Hide {channel_name}")
    close_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    close_button.clicked.connect(
        lambda _checked=False, channel_id=channel_name: close_requested(channel_id)
    )
    close_proxy = QGraphicsProxyWidget()
    close_proxy.setWidget(close_button)
    graphics_layout.addItem(close_proxy, row=row, col=0)

    plot_item = graphics_layout.addPlot(row=row, col=1)
    plot_item.setMinimumHeight(110)
    plot_item.setLabel("left", channel_name)
    plot_item.setLabel("bottom", "Master time", units="s")
    plot_item.getAxis("left").setWidth(70)
    plot_item.showGrid(x=True, y=False, alpha=0.18)
    plot_item.setMouseEnabled(x=False, y=False)
    plot_item.enableAutoRange(axis="y", enable=False)
    plot_item.enableAutoRange(axis="x", enable=False)

    color = QColor(*CHANNEL_COLORS[color_index % len(CHANNEL_COLORS)])
    pen = pg.mkPen(color=color, width=1.4)
    curve = SweepCurveItem(pen=pen, connect="finite")
    envelope_upper = SweepCurveItem(pen=None, connect="finite")
    fill_brush = QColor(color)
    fill_brush.setAlpha(70)
    envelope_fill = pg.FillBetweenItem(
        curve, envelope_upper, brush=pg.mkBrush(fill_brush), pen=None
    )
    retained_pen = pg.mkPen(color=color.darker(150), width=1.0)
    retained_curve = SweepCurveItem(pen=retained_pen, connect="finite")
    # The previous page keeps its min/max outlines but no longer carries a third
    # alpha-blended FillBetweenItem between them; that fill was composited over
    # the whole row on every repaint purely to tint data about to be overwritten
    # (D-054).  A thin pen costs a line, not a blended polygon.
    retained_upper = SweepCurveItem(pen=retained_pen, connect="finite")
    retained_curve.setZValue(0)
    retained_upper.setZValue(0)
    envelope_fill.setZValue(1.5)
    curve.setZValue(2)
    envelope_upper.setZValue(2)
    plot_item.addItem(retained_curve)
    plot_item.addItem(retained_upper)
    plot_item.addItem(curve)
    plot_item.addItem(envelope_upper)
    plot_item.addItem(envelope_fill)
    cursor_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("y", width=2))
    plot_item.addItem(cursor_line)

    coverage_region = None
    coverage_bounds = reader.coverage()
    if coverage_bounds is not None:
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
        envelope_fill=envelope_fill,
        retained_curve=retained_curve,
        retained_upper=retained_upper,
        cursor_line=cursor_line,
        close_button=close_button,
        close_proxy=close_proxy,
        coverage_region=coverage_region,
        coverage_bounds=coverage_bounds,
    )
