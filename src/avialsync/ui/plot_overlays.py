"""Overlay drawing and context-menu helpers for pyramid-backed plot rows."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QLineF, QRectF, Qt
from PySide6.QtGui import QAction, QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import QMenu

from avialsync.core.channel_reader import ChannelKey
from avialsync.core.trials import TimeWarp
from avialsync.ui.annotations import AnnotationStore
from avialsync.ui.i18n import tr
from avialsync.ui.plot_row import ChannelPlot
from avialsync.ui.plot_theme import gap_marker_pen, identity_marker_pen, measure_pen

logger = logging.getLogger(__name__)

_DENSE_LINE_THRESHOLD = 64
_MAX_PIXEL_BUCKETS = 512
_EMPTY_F64 = np.empty(0, dtype=np.float64)

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


@dataclass(frozen=True)
class PageTransform:
    """Shared page parameters hoisted once per overlay pass for vectorized slicing."""

    sweep_start: float
    window_duration: float
    warp: TimeWarp
    master_lo: float
    master_hi: float


class _BatchVerticalLines(pg.GraphicsObject):
    """Single graphics item painting dense vertical tick lines across a ViewBox's Y span."""

    def __init__(self, xs: np.ndarray, pen: QPen, z_value: float = 3.0) -> None:
        super().__init__()
        self._xs = np.asarray(xs, dtype=np.float64)
        self._pen = pen
        self._bounds = QRectF()
        self.setZValue(z_value)

    def setPen(self, pen: QPen) -> None:  # noqa: N802
        self._pen = pen
        self.update()

    def viewRangeChanged(self) -> None:  # noqa: N802
        self.prepareGeometryChange()
        self._bounds = QRectF()
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802
        if self._bounds.isNull() and len(self._xs) > 0:
            vb = self.getViewBox()
            if vb is not None:
                vr = vb.viewRect()
                x0, x1 = float(self._xs[0]), float(self._xs[-1])
                self._bounds = QRectF(x0, vr.top(), max(1e-6, x1 - x0), vr.height())
        return self._bounds

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        del option, widget
        if len(self._xs) == 0:
            return
        vb = self.getViewBox()
        if vb is None:
            return
        vr = vb.viewRect()
        y0, y1 = float(vr.top()), float(vr.bottom())
        painter.setPen(self._pen)
        painter.drawLines([QLineF(float(x), y0, float(x), y1) for x in self._xs])


def _bucket_positions(
    xs: np.ndarray, duration: float, buckets: int = _MAX_PIXEL_BUCKETS
) -> np.ndarray:
    """Coalesce dense X positions to at most one representative per pixel bucket."""
    if len(xs) <= buckets or duration <= 0.0:
        return np.unique(xs)
    cols = np.clip(np.rint(xs / duration * buckets).astype(np.int64), 0, buckets)
    _, first_idx = np.unique(cols, return_index=True)
    return xs[np.sort(first_idx)]


def _visible_sorted_xs(
    sorted_times: np.ndarray,
    display_x: Callable[[float], float | None],
    page: PageTransform | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(page_xs, matched_indices)`` inside the current page for *sorted_times*."""
    if len(sorted_times) == 0:
        return _EMPTY_F64, np.empty(0, dtype=np.int64)
    if page is not None:
        i0 = int(np.searchsorted(sorted_times, page.master_lo, side="left"))
        i1 = int(np.searchsorted(sorted_times, page.master_hi, side="right"))
        if i1 <= i0:
            return _EMPTY_F64, np.empty(0, dtype=np.int64)
        raw = page.warp.to_view_array(sorted_times[i0:i1]) - page.sweep_start
        mask = (raw >= -1e-9) & (raw <= page.window_duration + 1e-9)
        if not np.any(mask):
            return _EMPTY_F64, np.empty(0, dtype=np.int64)
        xs = np.clip(raw[mask], 0.0, page.window_duration)
        return xs, np.flatnonzero(mask) + i0
    xs_list: list[float] = []
    idx_list: list[int] = []
    for idx, t in enumerate(sorted_times):
        x = display_x(float(t))
        if x is not None:
            xs_list.append(x)
            idx_list.append(idx)
    if not xs_list:
        return _EMPTY_F64, np.empty(0, dtype=np.int64)
    return np.asarray(xs_list, dtype=np.float64), np.asarray(idx_list, dtype=np.int64)


def _remove_plot_items(old_items: Sequence[tuple[pg.PlotItem, Any]]) -> None:
    for plot_item, item in old_items:
        try:
            plot_item.removeItem(item)
        except RuntimeError:
            logger.debug("Plot item was already deleted", exc_info=True)


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
    menu.addSeparator()
    export = menu.addAction(tr("Export {name}…").format(name=channel.name))
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
    xa = display_x(measure_a) if measure_a is not None else None
    xb = display_x(measure_b) if measure_b is not None else None
    if xa is None and xb is None:
        return [], []
    pen_a = measure_pen(palette, "in")
    pen_b = measure_pen(palette, "out")
    new_a: list[pg.InfiniteLine] = []
    new_b: list[pg.InfiniteLine] = []
    for channel in channels:
        if not channel.visible or getattr(channel, "culled", False):
            continue
        for x, pen, destination in ((xa, pen_a, new_a), (xb, pen_b, new_b)):
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
    *,
    page: PageTransform | None = None,
) -> None:
    """Draw retained gap evidence on visible, non-culled rows with dense coalescing."""
    if not any(
        ch.gap_markers or (ch.visible and not getattr(ch, "culled", False) and ch.gap_times)
        for ch in channels
    ):
        return
    pen = gap_marker_pen(palette)
    duration = page.window_duration if page is not None else 0.0
    xs_cache: dict[int, np.ndarray] = {}
    for channel in channels:
        if channel.gap_markers:
            for line in channel.gap_markers:
                try:
                    channel.plot_item.removeItem(line)
                except RuntimeError:
                    logger.debug("Plot item was already deleted", exc_info=True)
            channel.gap_markers.clear()
        if not channel.visible or getattr(channel, "culled", False) or not channel.gap_times:
            continue
        cache_key = id(channel.gap_times)
        xs = xs_cache.get(cache_key)
        if xs is None:
            arr = np.asarray(channel.gap_times, dtype=np.float64)
            if len(arr) > 1 and bool(np.any(arr[1:] < arr[:-1])):
                arr = np.sort(arr)
            xs, _ = _visible_sorted_xs(arr, display_x, page)
            xs_cache[cache_key] = xs
        if len(xs) == 0:
            continue
        if len(xs) <= _DENSE_LINE_THRESHOLD:
            for x in xs:
                line = pg.InfiniteLine(pos=float(x), angle=90, movable=False, pen=pen)
                line.setZValue(3)
                channel.plot_item.addItem(line)
                channel.gap_markers.append(line)
        else:
            batch = _BatchVerticalLines(_bucket_positions(xs, duration), pen, z_value=3.0)
            channel.plot_item.addItem(batch, ignoreBounds=True)
            channel.gap_markers.append(cast(Any, batch))


def redraw_identity_markers(
    channels: list[ChannelPlot],
    events: dict[str, tuple[tuple[float, str], ...]],
    display_x: Callable[[float], float | None],
    palette: QPalette,
    old_items: list[tuple[pg.PlotItem, Any]],
    *,
    page: PageTransform | None = None,
) -> list[tuple[pg.PlotItem, Any]]:
    """Draw accepted flips on the affected source's visible, non-culled plot rows."""
    if not events and not old_items:
        return []
    _remove_plot_items(old_items)
    active = [ch for ch in channels if ch.visible and not getattr(ch, "culled", False)]
    if not events or not active:
        return []
    pen = identity_marker_pen(palette)
    duration = page.window_duration if page is not None else 0.0
    by_source: dict[str, list[ChannelPlot]] = {}
    for ch in active:
        by_source.setdefault(ch.reader.source_id, []).append(ch)

    new_items: list[tuple[pg.PlotItem, Any]] = []
    for source_id, src_channels in by_source.items():
        src_events = events.get(source_id, ())
        if not src_events:
            continue
        times = np.fromiter((t for t, _ in src_events), dtype=np.float64, count=len(src_events))
        if len(times) > 1 and bool(np.any(times[1:] < times[:-1])):
            order = np.argsort(times, kind="mergesort")
            times = times[order]
            src_events = tuple(src_events[int(i)] for i in order)
        xs, matched = _visible_sorted_xs(times, display_x, page)
        if len(xs) == 0:
            continue
        if len(xs) <= _DENSE_LINE_THRESHOLD:
            for ch in src_channels:
                for x, idx in zip(xs, matched, strict=True):
                    line = pg.InfiniteLine(pos=float(x), angle=90, movable=False, pen=pen)
                    line.setZValue(4)
                    line.setToolTip(src_events[int(idx)][1])
                    ch.plot_item.addItem(line)
                    new_items.append((ch.plot_item, line))
        else:
            b_xs = _bucket_positions(xs, duration)
            for ch in src_channels:
                batch = _BatchVerticalLines(b_xs, pen, z_value=4.0)
                ch.plot_item.addItem(batch, ignoreBounds=True)
                new_items.append((ch.plot_item, batch))
    return new_items


def redraw_segment_boundaries(
    channels: list[Any],
    segment_bounds: np.ndarray,
    display_x: Callable[[float], float | None],
    palette: QPalette,
    old_items: list[tuple[pg.PlotItem, Any]],
    *,
    page: PageTransform | None = None,
) -> list[tuple[pg.PlotItem, Any]]:
    """Draw trial boundaries inside the visible page on non-culled rows."""
    _remove_plot_items(old_items)
    active = [ch for ch in channels if ch.visible and not getattr(ch, "culled", False)]
    if len(segment_bounds) == 0 or not active:
        return []
    xs, _ = _visible_sorted_xs(segment_bounds, display_x, page)
    if len(xs) == 0:
        return []
    pen = pg.mkPen(palette.color(palette.ColorRole.Mid), width=1, style=Qt.PenStyle.DashLine)
    new_items: list[tuple[pg.PlotItem, Any]] = []
    if len(xs) <= _DENSE_LINE_THRESHOLD:
        for ch in active:
            for x in xs:
                line = pg.InfiniteLine(pos=float(x), angle=90, movable=False, pen=pen)
                line.setZValue(2)
                ch.plot_item.addItem(line)
                new_items.append((ch.plot_item, line))
        return new_items
    b_xs = _bucket_positions(xs, page.window_duration if page is not None else 0.0)
    for ch in active:
        batch = _BatchVerticalLines(b_xs, pen, z_value=2.0)
        ch.plot_item.addItem(batch, ignoreBounds=True)
        new_items.append((ch.plot_item, batch))
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


def _collect_visible_annotations(
    markers: Sequence[Any],
    display_x: Callable[[float], float | None],
    x_range: Callable[[float, float], tuple[float, float] | None],
    page: PageTransform | None,
) -> tuple[list[tuple[int, Any, float]], list[tuple[int, Any, tuple[float, float]]]]:
    """Convert visible point and range markers once before iterating over rows."""
    points: list[tuple[int, Any, float]] = []
    ranges: list[tuple[int, Any, tuple[float, float]]] = []
    if page is not None and len(markers) > _DENSE_LINE_THRESHOLD:
        pt_indices = [i for i, m in enumerate(markers) if m.t_end is None]
        if pt_indices:
            pt_t = np.fromiter(
                (markers[i].t_start for i in pt_indices), dtype=np.float64, count=len(pt_indices)
            )
            in_m = np.flatnonzero((pt_t >= page.master_lo) & (pt_t <= page.master_hi))
            if len(in_m):
                raw_x = page.warp.to_view_array(pt_t[in_m]) - page.sweep_start
                keep = (raw_x >= -1e-9) & (raw_x <= page.window_duration + 1e-9)
                for pos, x_val in zip(
                    in_m[keep], np.clip(raw_x[keep], 0.0, page.window_duration), strict=True
                ):
                    orig_i = pt_indices[int(pos)]
                    points.append((orig_i, markers[orig_i], float(x_val)))
        for idx, marker in enumerate(markers):
            if marker.t_end is None:
                continue
            if marker.t_end < page.master_lo or marker.t_start > page.master_hi:
                continue
            span = x_range(marker.t_start, marker.t_end)
            if span is not None:
                ranges.append((idx, marker, span))
        return points, ranges

    for idx, marker in enumerate(markers):
        if marker.t_end is None:
            x = display_x(marker.t_start)
            if x is not None:
                points.append((idx, marker, x))
        else:
            span = x_range(marker.t_start, marker.t_end)
            if span is not None:
                ranges.append((idx, marker, span))
    return points, ranges


def _draw_dense_ranges(
    active: list[Any],
    ranges: list[tuple[int, Any, tuple[float, float]]],
    duration: float,
    new_items: list[tuple[pg.PlotItem, object]],
) -> None:
    tol = duration / 256.0 if duration > 0 else 0.0
    by_color: dict[str, list[tuple[float, float]]] = {}
    for _idx, marker, span in ranges:
        by_color.setdefault(str(marker.color), []).append(span)
    for hex_color, spans in by_color.items():
        spans.sort()
        merged: list[tuple[float, float]] = []
        for s0, s1 in spans:
            if merged and s0 <= merged[-1][1] + tol:
                merged[-1] = (merged[-1][0], max(merged[-1][1], s1))
            else:
                merged.append((s0, s1))
        if len(merged) > _DENSE_LINE_THRESHOLD:
            stride = -(-len(merged) // _DENSE_LINE_THRESHOLD)
            merged = [
                (merged[i][0], max(s[1] for s in merged[i : i + stride]))
                for i in range(0, len(merged), stride)
            ]
        qcol = pg.mkColor(hex_color)
        brush = QColor(hex_color)
        brush.setAlpha(40)
        pen = pg.mkPen(qcol, width=1, style=Qt.PenStyle.DashLine)
        for ch in active:
            for sp in merged:
                region = pg.LinearRegionItem(values=list(sp), movable=False, brush=brush, pen=pen)
                region.setZValue(-5)
                ch.plot_item.addItem(region)
                new_items.append((ch.plot_item, region))


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
    page: PageTransform | None = None,
) -> list[tuple[pg.PlotItem, object]]:
    """Replace page-local annotation graphics on visible, non-culled rows."""
    if (annotation_store is None or not annotation_store._markers) and not old_items:
        return []
    _remove_plot_items(old_items)
    active = [ch for ch in channels if ch.visible and not getattr(ch, "culled", False)]
    if annotation_store is None or not annotation_store._markers or not active:
        return []
    markers = annotation_store.markers
    points, ranges = _collect_visible_annotations(markers, display_x, x_range, page)
    if not points and not ranges:
        return []

    movable = master_at is not None and on_marker_moved is not None
    duration = page.window_duration if page is not None else 0.0
    new_items: list[tuple[pg.PlotItem, object]] = []

    if len(points) <= _DENSE_LINE_THRESHOLD:
        for marker_idx, marker, x in points:
            pen = pg.mkPen(pg.mkColor(marker.color), width=2, style=Qt.PenStyle.DashLine)
            for ch in active:
                line = pg.InfiniteLine(pos=x, angle=90, movable=movable, pen=pen)
                if movable and master_at is not None and on_marker_moved is not None:
                    line.sigPositionChangeFinished.connect(
                        lambda item=line, idx=marker_idx: on_marker_moved(
                            idx, master_at(float(item.value())), None
                        )
                    )
                ch.plot_item.addItem(line)
                new_items.append((ch.plot_item, line))
    else:
        by_color: dict[str, list[float]] = {}
        for _idx, marker, x in points:
            by_color.setdefault(str(marker.color), []).append(x)
        for hex_color, xs_list in by_color.items():
            xs_arr = np.sort(np.asarray(xs_list, dtype=np.float64))
            b_xs = _bucket_positions(xs_arr, duration)
            pen = pg.mkPen(pg.mkColor(hex_color), width=2, style=Qt.PenStyle.DashLine)
            for ch in active:
                batch = _BatchVerticalLines(b_xs, pen, z_value=4.0)
                ch.plot_item.addItem(batch, ignoreBounds=True)
                new_items.append((ch.plot_item, batch))

    if len(ranges) <= _DENSE_LINE_THRESHOLD:
        for marker_idx, marker, span in ranges:
            color = pg.mkColor(marker.color)
            for ch in active:
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
                ch.plot_item.addItem(region)
                new_items.append((ch.plot_item, region))
    else:
        _draw_dense_ranges(active, ranges, duration, new_items)
    return new_items
