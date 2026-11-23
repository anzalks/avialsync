"""Overlay drawing and context-menu helpers for pyramid-backed plot rows."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import QMenu

from avialsync.core.channel_reader import ChannelKey
from avialsync.ui.annotations import AnnotationStore
from avialsync.ui.i18n import tr
from avialsync.ui.plot_row import ChannelPlot
from avialsync.ui.plot_theme import gap_marker_pen, identity_marker_pen, measure_pen

logger = logging.getLogger(__name__)

ContextAction = Literal[
    "annotate",
    "measure_a",
    "measure_b",
    "clear_measure",
    "fit_y",
    "auto_y",
    "hold_y",
    "pin",
    "export",
    "hide",
]


@dataclass(frozen=True)
class ContextChoice:
    """A concrete plot-menu choice, mapped to master time and channel."""

    action: ContextAction
    time: float
    channel_id: str
    channel_key: ChannelKey | None = None


def show_context_menu(
    event: Any,
    channel: ChannelPlot,
    master_at: Callable[[float], float],
    extra_actions: Iterable[QAction],
) -> ContextChoice | None:
    """Show plot actions for one row and return the selected semantic action.

    *master_at* turns a page position into master time (``PlotPane.master_at``).
    """
    scene_pos = event.scenePos()
    view_pos = channel.plot_item.vb.mapSceneToView(scene_pos)
    time = master_at(float(view_pos.x()))
    menu = QMenu()
    annotate = menu.addAction(tr("Add marker here  ({time} s)").format(time=f"{time:.3f}"))
    menu.addSeparator()
    measure_a = menu.addAction(tr("Set Measure A  ({time} s)").format(time=f"{time:.3f}"))
    measure_b = menu.addAction(tr("Set Measure B  ({time} s)").format(time=f"{time:.3f}"))
    clear_measure = menu.addAction(tr("Clear Measure"))
    menu.addSeparator()
    fit_y = menu.addAction(tr("Fit {name} Y (hold)").format(name=channel.name))
    auto_y = menu.addAction(tr("Auto-scale {name} Y").format(name=channel.name))
    hold_y = menu.addAction(tr("Hold {name} Y scale").format(name=channel.name))
    menu.addSeparator()
    pin_label = (
        tr("Unpin {name} from top").format(name=channel.name)
        if channel.pinned
        else tr("Pin {name} to top").format(name=channel.name)
    )
    pin = menu.addAction(pin_label)
    extras = tuple(extra_actions)
    if extras:
        menu.addSeparator()
        for extra in extras:
            menu.addAction(extra)
    # pyqtgraph's own exporter, for this row: a picture of the trace, or the
    # points as drawn. The samples themselves are File -> Export Data Slice.
    menu.addSeparator()
    export = menu.addAction(tr("Export {name}…").format(name=channel.name))
    # The row's own close, also here so it never depends on hovering.
    menu.addSeparator()
    hide = menu.addAction(tr("Hide {name}").format(name=channel.name))
    chosen = menu.exec(event.screenPos().toPoint())
    actions: dict[QAction, ContextAction] = {
        annotate: "annotate",
        measure_a: "measure_a",
        measure_b: "measure_b",
        clear_measure: "clear_measure",
        fit_y: "fit_y",
        auto_y: "auto_y",
        hold_y: "hold_y",
        pin: "pin",
        export: "export",
        hide: "hide",
    }
    action = actions.get(chosen)
    if action is None:
        return None
    return ContextChoice(action, time, channel.name, channel.reader.key)


def show_mode_context_menu(
    event: Any,
    plot_item: pg.PlotItem,
    master_at: Callable[[float], float],
    extra_actions: Iterable[QAction],
) -> ContextChoice | None:
    """Show shared time-axis actions for Overlaid / Heatmap mode canvas."""
    scene_pos = event.scenePos()
    view_pos = plot_item.vb.mapSceneToView(scene_pos)
    time = master_at(float(view_pos.x()))
    menu = QMenu()
    annotate = menu.addAction(tr("Add marker here  ({time} s)").format(time=f"{time:.3f}"))
    menu.addSeparator()
    measure_a = menu.addAction(tr("Set Measure A  ({time} s)").format(time=f"{time:.3f}"))
    measure_b = menu.addAction(tr("Set Measure B  ({time} s)").format(time=f"{time:.3f}"))
    clear_measure = menu.addAction(tr("Clear Measure"))
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
    }
    action = actions.get(chosen)
    return ContextChoice(action, time, "") if action is not None else None


def redraw_measure_lines(
    channels: list[Any],
    measure_a: float | None,
    measure_b: float | None,
    display_x: Callable[[float], float | None],
    old_a: list[pg.InfiniteLine],
    old_b: list[pg.InfiniteLine],
    palette: QPalette,
) -> tuple[list[pg.InfiniteLine], list[pg.InfiniteLine]]:
    """Replace A/B measurement pins without retaining stale plot items."""
    if measure_a is None and measure_b is None and not old_a and not old_b:
        return [], []
    for line in old_a + old_b:
        owner = getattr(line, "_owner_plot_item", None)
        if owner is not None:
            try:
                owner.removeItem(line)
            except RuntimeError:
                logger.debug("Plot item was already deleted", exc_info=True)
            continue
        for channel in channels:
            try:
                channel.plot_item.removeItem(line)
            except RuntimeError:
                logger.debug("Plot item was already deleted", exc_info=True)
    pen_a = measure_pen(palette, "in")
    pen_b = measure_pen(palette, "out")
    new_a: list[pg.InfiniteLine] = []
    new_b: list[pg.InfiniteLine] = []
    for channel in channels:
        if not channel.visible or getattr(channel, "culled", False):
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
            line._owner_plot_item = channel.plot_item  # type: ignore[attr-defined]
            channel.plot_item.addItem(line)
            destination.append(line)
    return new_a, new_b


def redraw_gap_markers(
    channels: list[ChannelPlot],
    display_x: Callable[[float], float | None],
    palette: QPalette,
) -> None:
    """Draw retained gap evidence only where it intersects the visible page."""
    if not any(ch.gap_markers or (ch.visible and ch.gap_times) for ch in channels):
        return
    pen = gap_marker_pen(palette)
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


def redraw_identity_markers(
    channels: list[ChannelPlot],
    events: dict[str, tuple[tuple[float, str], ...]],
    display_x: Callable[[float], float | None],
    palette: QPalette,
    old_items: list[tuple[pg.PlotItem, pg.InfiniteLine]],
) -> list[tuple[pg.PlotItem, pg.InfiniteLine]]:
    """Draw accepted flips on the affected source's visible plot rows."""
    if not events and not old_items:
        return []
    for plot_item, line in old_items:
        try:
            plot_item.removeItem(line)
        except RuntimeError:
            logger.debug("Plot item was already deleted", exc_info=True)
    pen = identity_marker_pen(palette)
    new_items: list[tuple[pg.PlotItem, pg.InfiniteLine]] = []
    for channel in channels:
        if not channel.visible:
            continue
        for time, label in events.get(channel.reader.source_id, ()):
            x = display_x(time)
            if x is None:
                continue
            line = pg.InfiniteLine(pos=x, angle=90, movable=False, pen=pen)
            line.setZValue(4)
            line.setToolTip(label)
            channel.plot_item.addItem(line)
            new_items.append((channel.plot_item, line))
    return new_items


def _resolve_region_drag(
    orig_start: float,
    orig_end: float,
    init_span: tuple[float, float],
    new_span: tuple[float, float],
    master_at: Callable[[float], float],
    x_of: Callable[[float], float | None] | None,
) -> tuple[float, float]:
    """Preserve off-page endpoints when a page-clipped range marker is dragged."""
    init_r0, init_r1 = init_span
    new_r0, new_r1 = new_span
    left_clipped = abs(master_at(init_r0) - orig_start) > 1e-6
    right_clipped = abs(master_at(init_r1) - orig_end) > 1e-6
    d0 = new_r0 - init_r0
    d1 = new_r1 - init_r1
    if (left_clipped or right_clipped) and abs(d0) > 1e-9 and abs(d0 - d1) <= 1e-6:
        if x_of is not None:
            raw0, raw1 = x_of(orig_start), x_of(orig_end)
            if raw0 is not None and raw1 is not None:
                return master_at(raw0 + d0), master_at(raw1 + d0)
    resolved_start = orig_start if (left_clipped and abs(d0) <= 1e-9) else master_at(new_r0)
    resolved_end = orig_end if (right_clipped and abs(d1) <= 1e-9) else master_at(new_r1)
    return resolved_start, resolved_end


def _build_range_region(
    marker: Any,
    marker_idx: int,
    span: tuple[float, float],
    color: Any,
    *,
    movable: bool,
    master_at: Callable[[float], float] | None,
    x_of: Callable[[float], float | None] | None,
    on_marker_moved: Callable[[int, float, float | None], None] | None,
) -> pg.LinearRegionItem:
    brush = QColor(marker.color)
    brush.setAlpha(40)
    region = pg.LinearRegionItem(
        values=list(span),
        movable=movable,
        brush=brush,
        pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashLine),
    )
    if movable and master_at is not None and on_marker_moved is not None:
        orig_s, orig_e = float(marker.t_start), float(marker.t_end)
        region.sigRegionChangeFinished.connect(
            lambda item=region, idx=marker_idx, s0=orig_s, e0=orig_e, sp=span: on_marker_moved(
                idx,
                *_resolve_region_drag(s0, e0, sp, item.getRegion(), master_at, x_of),
            )
        )
    region.setZValue(-5)
    return region


def redraw_annotations(
    channels: list[Any],
    annotation_store: AnnotationStore | None,
    display_x: Callable[[float], float | None],
    x_range: Callable[[float, float], tuple[float, float] | None],
    old_items: list[tuple[pg.PlotItem, object]],
    *,
    master_at: Callable[[float], float] | None = None,
    x_of: Callable[[float], float | None] | None = None,
    on_marker_moved: Callable[[int, float, float | None], None] | None = None,
) -> list[tuple[pg.PlotItem, object]]:
    """Replace page-local annotation graphics from the authoritative store."""
    if (annotation_store is None or not annotation_store.markers) and not old_items:
        return []
    for plot_item, item in old_items:
        try:
            plot_item.removeItem(item)
        except RuntimeError:
            logger.debug("Plot item was already deleted", exc_info=True)
    if annotation_store is None:
        return []
    movable = master_at is not None and on_marker_moved is not None
    new_items: list[tuple[pg.PlotItem, object]] = []
    for marker_idx, marker in enumerate(annotation_store.markers):
        color = pg.mkColor(marker.color)
        for channel in channels:
            if not channel.visible:
                continue
            if marker.t_end is None:
                x = display_x(marker.t_start)
                if x is None:
                    continue
                pen = pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine)
                line = pg.InfiniteLine(pos=x, angle=90, movable=movable, pen=pen)
                if movable and master_at is not None and on_marker_moved is not None:
                    line.sigPositionChangeFinished.connect(
                        lambda item=line, idx=marker_idx: on_marker_moved(
                            idx, master_at(float(item.value())), None
                        )
                    )
                channel.plot_item.addItem(line)
                new_items.append((channel.plot_item, line))
                continue
            span = x_range(marker.t_start, marker.t_end)
            if span is None:
                continue
            region = _build_range_region(
                marker,
                marker_idx,
                span,
                color,
                movable=movable,
                master_at=master_at,
                x_of=x_of,
                on_marker_moved=on_marker_moved,
            )
            channel.plot_item.addItem(region)
            new_items.append((channel.plot_item, region))
    return new_items
