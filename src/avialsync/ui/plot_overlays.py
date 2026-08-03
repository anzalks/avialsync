"""Overlay drawing and context-menu helpers for pyramid-backed plot rows."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QMenu

from avialsync.ui.annotations import AnnotationStore
from avialsync.ui.plot_row import ChannelPlot

logger = logging.getLogger(__name__)

ContextAction = Literal[
    "annotate", "measure_a", "measure_b", "clear_measure", "fit_y", "auto_y", "hold_y"
]


@dataclass(frozen=True)
class ContextChoice:
    """A concrete plot-menu choice, mapped to master time and channel."""

    action: ContextAction
    time: float
    channel_id: str


def show_context_menu(
    event: Any,
    channel: ChannelPlot,
    sweep_start: float,
    extra_actions: Iterable[QAction],
) -> ContextChoice | None:
    """Show plot actions for one row and return the selected semantic action."""
    scene_pos = event.scenePos()
    view_pos = channel.plot_item.vb.mapSceneToView(scene_pos)
    time = sweep_start + float(view_pos.x())
    menu = QMenu()
    annotate = menu.addAction(f"Add marker here  ({time:.3f} s)")
    menu.addSeparator()
    measure_a = menu.addAction(f"Set Measure A  ({time:.3f} s)")
    measure_b = menu.addAction(f"Set Measure B  ({time:.3f} s)")
    clear_measure = menu.addAction("Clear Measure")
    menu.addSeparator()
    fit_y = menu.addAction(f"Fit {channel.name} Y (hold)")
    auto_y = menu.addAction(f"Auto-scale {channel.name} Y")
    hold_y = menu.addAction(f"Hold {channel.name} Y scale")
    extras = tuple(extra_actions)
    if extras:
        menu.addSeparator()
        for extra in extras:
            menu.addAction(extra)
    chosen = menu.exec(event.screenPos().toPoint())
    actions: dict[QAction, ContextAction] = {
        annotate: "annotate",
        measure_a: "measure_a",
        measure_b: "measure_b",
        clear_measure: "clear_measure",
        fit_y: "fit_y",
        auto_y: "auto_y",
        hold_y: "hold_y",
    }
    action = actions.get(chosen)
    if action is None:
        return None
    return ContextChoice(action, time, channel.name)


def redraw_measure_lines(
    channels: list[ChannelPlot],
    measure_a: float | None,
    measure_b: float | None,
    display_x: Callable[[float], float | None],
    old_a: list[pg.InfiniteLine],
    old_b: list[pg.InfiniteLine],
) -> tuple[list[pg.InfiniteLine], list[pg.InfiniteLine]]:
    """Replace A/B measurement pins without retaining stale plot items."""
    for line in old_a + old_b:
        for channel in channels:
            try:
                channel.plot_item.removeItem(line)
            except RuntimeError:
                logger.debug("Plot item was already deleted", exc_info=True)
    pen_a = pg.mkPen(color=(0, 255, 100), width=2, style=Qt.PenStyle.DashLine)
    pen_b = pg.mkPen(color=(255, 80, 80), width=2, style=Qt.PenStyle.DashLine)
    new_a: list[pg.InfiniteLine] = []
    new_b: list[pg.InfiniteLine] = []
    for channel in channels:
        if not channel.visible:
            continue
        for marker, pen, destination in (
            (measure_a, pen_a, new_a),
            (measure_b, pen_b, new_b),
        ):
            x = display_x(marker) if marker is not None else None
            if x is None:
                continue
            line = pg.InfiniteLine(pos=x, angle=90, movable=False, pen=pen)
            line.setZValue(5)
            channel.plot_item.addItem(line)
            destination.append(line)
    return new_a, new_b


def redraw_gap_markers(
    channels: list[ChannelPlot], display_x: Callable[[float], float | None]
) -> None:
    """Draw retained gap evidence only where it intersects the visible page."""
    pen = pg.mkPen(color=(255, 60, 60), width=1, style=Qt.PenStyle.DotLine)
    for channel in channels:
        for line in channel.gap_markers:
            channel.plot_item.removeItem(line)
        channel.gap_markers.clear()
        if not channel.visible:
            continue
        for time in channel.gap_times:
            x = display_x(time)
            if x is None:
                continue
            line = pg.InfiniteLine(pos=x, angle=90, movable=False, pen=pen)
            line.setZValue(3)
            channel.plot_item.addItem(line)
            channel.gap_markers.append(line)


def redraw_annotations(
    channels: list[ChannelPlot],
    annotation_store: AnnotationStore | None,
    display_x: Callable[[float], float | None],
    sweep_start: float | None,
    window_duration: float,
    old_items: list[tuple[pg.PlotItem, object]],
) -> list[tuple[pg.PlotItem, object]]:
    """Replace page-local annotation graphics from the authoritative store."""
    for plot_item, item in old_items:
        plot_item.removeItem(item)
    if annotation_store is None:
        return []
    new_items: list[tuple[pg.PlotItem, object]] = []
    for marker in annotation_store.markers:
        color = pg.mkColor(marker.color)
        for channel in channels:
            if not channel.visible:
                continue
            if marker.t_end is None:
                x = display_x(marker.t_start)
                if x is None:
                    continue
                pen = pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine)
                line = pg.InfiniteLine(pos=x, angle=90, movable=False, pen=pen)
                channel.plot_item.addItem(line)
                new_items.append((channel.plot_item, line))
                continue
            if sweep_start is None:
                continue
            marker_start = max(marker.t_start, sweep_start)
            marker_end = min(marker.t_end, sweep_start + window_duration)
            if marker_end < marker_start:
                continue
            brush = QColor(marker.color)
            brush.setAlpha(40)
            region = pg.LinearRegionItem(
                values=[marker_start - sweep_start, marker_end - sweep_start],
                movable=False,
                brush=brush,
                pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashLine),
            )
            region.setZValue(-5)
            channel.plot_item.addItem(region)
            new_items.append((channel.plot_item, region))
    return new_items
