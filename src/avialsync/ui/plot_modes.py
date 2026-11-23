"""Alternative multi-channel plot presentations (Overlaid, 2D Carpet Heatmap) and row pinning."""

from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING, Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QAccessible, QPalette
from PySide6.QtWidgets import QVBoxLayout, QWidget

from avialsync.core.channel_reader import ChannelKey
from avialsync.ui.accessible_views import register_painted
from avialsync.ui.i18n import tr
from avialsync.ui.plot_row import (
    ChannelPlot,
    apply_channel_visibility,
    create_channel_plot,
    detach_row,
    fit_channel_y,
    set_channel_unit,
)
from avialsync.ui.plot_stack_view import PlotStackView
from avialsync.ui.plot_sweep import SweepCurveItem
from avialsync.ui.plot_theme import apply_canvas_palette
from avialsync.ui.theme import playhead_color, plot_colors, trace_color

if TYPE_CHECKING:
    from avialsync.ui.plot_pane import PlotPane

logger = logging.getLogger(__name__)

__all__ = [
    "PLOT_MODE_HEATMAP",
    "PLOT_MODE_OVERLAY",
    "PLOT_MODE_STACKED",
    "PlotModeCanvas",
    "toggle_channel_pin",
]

PLOT_MODE_STACKED = "stacked"
PLOT_MODE_OVERLAY = "overlay"
PLOT_MODE_HEATMAP = "heatmap"

_PEN_STYLES = (
    Qt.PenStyle.SolidLine,
    Qt.PenStyle.DashLine,
    Qt.PenStyle.DotLine,
    Qt.PenStyle.DashDotLine,
)

# Perceptual Viridis stops for the 2D carpet heatmap (dark purple -> teal -> yellow)
_VIRIDIS_STOPS = np.array(
    [
        [68, 1, 84],
        [59, 82, 139],
        [33, 145, 140],
        [94, 201, 98],
        [253, 231, 37],
    ],
    dtype=np.float64,
)


def _decimate_for_overlay(
    x_arr: np.ndarray, y_arr: np.ndarray, max_columns: int
) -> tuple[np.ndarray, np.ndarray]:
    """Coarsen an interleaved min/max curve when hundreds of traces share one canvas."""
    n_pts = len(x_arr)
    if n_pts <= max_columns * 2 or max_columns < 8:
        return x_arr, y_arr
    n_cols = n_pts // 2
    factor = max(1, -(-n_cols // max_columns))
    if factor <= 1:
        return x_arr, y_arr
    trunc = (n_cols // factor) * factor
    if trunc <= 0:
        return x_arr, y_arr
    x_cols = x_arr[0 : trunc * 2 : 2].reshape(-1, factor)[:, 0]
    y_blocks = y_arr[0 : trunc * 2].reshape(-1, factor * 2)
    has_nan = np.any(~np.isfinite(y_blocks), axis=1)
    safe = np.where(np.isfinite(y_blocks), y_blocks, 0.0)
    lo = np.min(safe, axis=1)
    hi = np.max(safe, axis=1)
    lo[has_nan] = np.nan
    hi[has_nan] = np.nan
    out_x = np.repeat(x_cols, 2)
    out_y = np.empty(len(x_cols) * 2, dtype=np.float64)
    out_y[0::2] = lo
    out_y[1::2] = hi
    return out_x, out_y


def _viridis_lut() -> np.ndarray:
    positions = np.linspace(0.0, 1.0, len(_VIRIDIS_STOPS))
    grid = np.linspace(0.0, 1.0, 256)
    lut = np.empty((256, 3), dtype=np.uint8)
    for col in range(3):
        lut[:, col] = np.clip(np.interp(grid, positions, _VIRIDIS_STOPS[:, col]), 0, 255).astype(
            np.uint8
        )
    return lut


_HEATMAP_LUT = _viridis_lut()


class PlotModeCanvas(QWidget):
    """Shared canvas rendering visible decimated channels as Overlaid traces or a 2D Heatmap."""

    seek_requested = Signal(float)  # page-local x
    context_requested = Signal(object)  # QGraphicsSceneMouseEvent

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode = PLOT_MODE_OVERLAY
        self._curves: list[SweepCurveItem] = []
        self._image_item: pg.ImageItem | None = None
        self._legend: pg.LegendItem | None = None
        self._channel_names: list[str] = []
        self.plot_item: Any = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.graphics_layout = PlotStackView(
            lambda: [self.plot_item.getViewBox()] if self.plot_item is not None else [], self
        )
        self.graphics_layout.setAccessibleName(tr("Combined plot canvas"))
        self.graphics_layout.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.graphics_layout.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.graphics_layout.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.graphics_layout)

        self.plot_item = self.graphics_layout.addPlot(row=0, col=0, enableMenu=False)
        self.plot_item.setMenuEnabled(False)
        self.plot_item.setMouseEnabled(x=False, y=False)
        self.plot_item.enableAutoRange(axis="x", enable=False)
        self.plot_item.enableAutoRange(axis="y", enable=False)
        self.plot_item.getAxis("left").setWidth(104)
        self.plot_item.getAxis("left").enableAutoSIPrefix(False)
        self.plot_item.getAxis("bottom").setLabel(tr("Master time"), units="s")
        for hidden in ("top", "right"):
            self.plot_item.getAxis(hidden).enableAutoSIPrefix(False)

        self.cursor_line = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen(playhead_color(self.palette()), width=2)
        )
        self.cursor_line.setZValue(10)
        self.plot_item.addItem(self.cursor_line, ignoreBounds=True)

        scene = self.graphics_layout.scene()
        scene.contextMenu = []
        scene.sigMouseClicked.connect(self._on_clicked)

        register_painted(
            self.graphics_layout,
            QAccessible.Role.Chart,
            lambda: tr("{mode} view of {n} channels").format(
                mode=self._mode, n=len(self._channel_names)
            ),
            lambda: ", ".join(self._channel_names[:16]),
        )

    def viewport(self) -> QWidget | None:
        vp = self.graphics_layout.viewport()
        return vp if isinstance(vp, QWidget) else None

    def set_mode(self, mode: str) -> None:
        """Select ``'overlay'`` or ``'heatmap'`` presentation."""
        self._mode = mode

    def apply_palette(self, palette: QPalette) -> None:
        apply_canvas_palette(self.graphics_layout, palette)
        self.cursor_line.setPen(pg.mkPen(playhead_color(palette), width=2))
        self.plot_item.showGrid(
            x=True, y=self._mode == PLOT_MODE_OVERLAY, alpha=plot_colors(palette).grid_alpha
        )

    def set_x_window(self, duration: float) -> None:
        if duration > 0:
            self.plot_item.setXRange(0.0, duration, padding=0)

    def set_cursor_phase(self, phase: float, *, reveal: bool) -> None:
        self.cursor_line.setValue(phase)
        for curve in self._curves:
            curve.set_reveal_enabled(reveal)
            curve.set_sweep_position(phase)

    def render_from_channels(
        self,
        channels: list[ChannelPlot],
        window_duration: float,
        palette: QPalette,
        *,
        reveal: bool,
        phase: float,
    ) -> None:
        """Render the already-installed decimated curve arrays from visible *channels*."""
        self.graphics_layout.setUpdatesEnabled(False)
        try:
            self._clear_items()
            visible = [ch for ch in channels if ch.visible]
            self._channel_names = [ch.name for ch in visible]
            self.set_x_window(window_duration)
            self.cursor_line.setValue(phase)
            if not visible:
                return
            if self._mode == PLOT_MODE_HEATMAP:
                self._render_heatmap(visible, window_duration)
            else:
                self._render_overlay(visible, palette, reveal=reveal, phase=phase)
        finally:
            self.graphics_layout.setUpdatesEnabled(True)

    def _clear_items(self) -> None:
        for curve in self._curves:
            self.plot_item.removeItem(curve)
        self._curves.clear()
        if self._image_item is not None:
            self.plot_item.removeItem(self._image_item)
            self._image_item = None
        if self._legend is not None:
            try:
                self._legend.scene().removeItem(self._legend)
            except (AttributeError, RuntimeError):
                logger.debug("Legend item was already removed", exc_info=True)
            self._legend = None
        self.plot_item.getAxis("left").setTicks(None)

    def _render_overlay(
        self,
        visible: list[ChannelPlot],
        palette: QPalette,
        *,
        reveal: bool,
        phase: float,
    ) -> None:
        self.plot_item.showGrid(x=True, y=True, alpha=plot_colors(palette).grid_alpha)
        units = {ch.unit for ch in visible if ch.unit}
        unit_label = f" ({next(iter(units))})" if len(units) == 1 else ""
        self.plot_item.setLabel("left", html.escape(tr("Overlaid") + unit_label))

        if len(visible) <= 12:
            self._legend = self.plot_item.addLegend(offset=(-10, 10))
        y_min = float("inf")
        y_max = float("-inf")
        use_dashes = len(visible) > 1
        if len(visible) <= 12:
            for idx, ch in enumerate(visible):
                xs, ys = ch.curve.getData()
                style = (
                    _PEN_STYLES[(idx // 6) % len(_PEN_STYLES)]
                    if use_dashes
                    else Qt.PenStyle.SolidLine
                )
                pen = pg.mkPen(color=trace_color(palette, ch.color_index), width=1.4, style=style)
                label = f"{ch.name} ({ch.unit})" if ch.unit else ch.name
                curve = SweepCurveItem(pen=pen, connect="finite", name=label)
                curve.set_reveal_enabled(reveal)
                curve.set_sweep_position(phase)
                if xs is not None and ys is not None and len(xs) > 0:
                    curve.setData(xs, ys)
                    finite = np.asarray(ys)[np.isfinite(ys)]
                    if len(finite):
                        y_min = min(y_min, float(finite.min()))
                        y_max = max(y_max, float(finite.max()))
                self.plot_item.addItem(curve)
                self._curves.append(curve)
                if self._legend is not None:
                    self._legend.addItem(curve, html.escape(label))
        else:
            # Batch dense overlays into one NaN-delimited curve per (colour, dash)
            # pen group so 600+ ROIs draw ~32 paths instead of 600+ QGraphicsItems.
            buckets: dict[
                tuple[int, Qt.PenStyle], tuple[Any, list[np.ndarray], list[np.ndarray]]
            ] = {}
            nan_sep = np.array([np.nan], dtype=np.float64)
            max_cols = max(32, 24_000 // len(visible))
            for idx, ch in enumerate(visible):
                xs, ys = ch.curve.getData()
                if xs is None or ys is None or len(xs) == 0:
                    continue
                x_arr = np.asarray(xs, dtype=np.float64)
                y_arr = np.asarray(ys, dtype=np.float64)
                finite = y_arr[np.isfinite(y_arr)]
                if len(finite):
                    y_min = min(y_min, float(finite.min()))
                    y_max = max(y_max, float(finite.max()))
                if len(visible) > 32:
                    x_arr, y_arr = _decimate_for_overlay(x_arr, y_arr, max_cols)
                color = trace_color(palette, ch.color_index)
                style = _PEN_STYLES[(idx // 6) % len(_PEN_STYLES)]
                key = (color.rgba(), style)
                entry = buckets.get(key)
                if entry is None:
                    entry = (color, [], [])
                    buckets[key] = entry
                if entry[1]:
                    entry[1].append(nan_sep)
                    entry[2].append(nan_sep)
                entry[1].append(x_arr)
                entry[2].append(y_arr)
            for (_rgba, style), (color, x_parts, y_parts) in buckets.items():
                pen = pg.mkPen(color=color, width=1.4, style=style)
                curve = SweepCurveItem(pen=pen, connect="finite")
                curve.set_reveal_enabled(reveal)
                curve.set_sweep_position(phase)
                curve.setData(np.concatenate(x_parts), np.concatenate(y_parts))
                self.plot_item.addItem(curve)
                self._curves.append(curve)

        if np.isfinite(y_min) and np.isfinite(y_max):
            pad = max(1e-3, (y_max - y_min) * 0.08) if not np.isclose(y_min, y_max) else 1.0
            self.plot_item.setYRange(y_min - pad, y_max + pad, padding=0)
        else:
            self.plot_item.setYRange(-1.0, 1.0, padding=0)

    def _render_heatmap(self, visible: list[ChannelPlot], window_duration: float) -> None:
        self.plot_item.showGrid(x=False, y=False)
        self.plot_item.setLabel("left", html.escape(tr("Channels")))
        n_rows = len(visible)
        n_bins = 256
        dur = max(window_duration, 1e-6)
        grid_x = np.linspace(0.0, dur, n_bins)
        # ImageItem expects shape (width_x, height_y); row 0 at top -> y = n_rows - 1 - row_idx
        matrix = np.zeros((n_bins, n_rows), dtype=np.float32)
        sampled_rows = np.full((n_rows, n_bins), np.nan, dtype=np.float64)
        valid_row_mask = np.zeros(n_rows, dtype=bool)

        for row_idx, ch in enumerate(visible):
            xs, ys = ch.curve.getData()
            if xs is None or ys is None or len(xs) < 2:
                continue
            x_arr = np.asarray(xs, dtype=np.float64)
            y_arr = np.asarray(ys, dtype=np.float64)
            finite = np.isfinite(x_arr) & np.isfinite(y_arr)
            if np.count_nonzero(finite) < 2:
                continue
            xf = x_arr[finite]
            yf = y_arr[finite]
            # Collapse interleaved (min, max) pairs monotonically along x; skip sort if monotonic.
            if not bool(np.all(xf[1:] >= xf[:-1])):
                order = np.argsort(xf, kind="mergesort")
                xf = xf[order]
                yf = yf[order]
            sampled = np.interp(grid_x, xf, yf, left=np.nan, right=np.nan)
            if np.any(np.isfinite(sampled)):
                sampled_rows[row_idx] = sampled
                valid_row_mask[row_idx] = True

        if np.any(valid_row_mask):
            active = sampled_rows[valid_row_mask]
            lo, hi = np.nanpercentile(active, (2.0, 98.0), axis=1)
            denom = np.where(hi > lo + 1e-12, hi - lo, 1.0)
            normed = np.clip((active - lo[:, None]) / denom[:, None], 0.0, 1.0)
            normed = np.nan_to_num(normed, nan=0.0)
            dest_cols = (n_rows - 1) - np.flatnonzero(valid_row_mask)
            matrix[:, dest_cols] = normed.T.astype(np.float32)

        img = pg.ImageItem(matrix)
        img.setLookupTable(_HEATMAP_LUT)
        img.setLevels([0.0, 1.0])
        img.setRect(QRectF(0.0, 0.0, dur, float(n_rows)))
        img.setZValue(1)
        self.plot_item.addItem(img)
        self._image_item = img
        self.plot_item.setYRange(0.0, float(n_rows), padding=0)

        step = max(1, (n_rows + 11) // 12)
        ticks = [
            (float(n_rows - 1 - i) + 0.5, visible[i].name[:14]) for i in range(0, n_rows, step)
        ]
        self.plot_item.getAxis("left").setTicks([ticks])

    def _on_clicked(self, event: Any) -> None:
        scene_pos = event.scenePos()
        if not self.plot_item.vb.sceneBoundingRect().contains(scene_pos):
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.context_requested.emit(event)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        mods = event.modifiers() if hasattr(event, "modifiers") else Qt.KeyboardModifier.NoModifier
        if bool(mods & Qt.KeyboardModifier.ShiftModifier):
            return
        x = float(self.plot_item.vb.mapSceneToView(scene_pos).x())
        self.seek_requested.emit(x)
        event.accept()


def toggle_channel_pin(pane: PlotPane, target: ChannelKey | str) -> None:
    """Pin *target* to the sticky top plot stack, or return it to the scroll stack."""
    matches = pane._matching(target)
    if not matches:
        return
    new_pinned = not matches[0].pinned
    pane.set_channel_pinned(target, new_pinned)


def _rebuild_one_channel(
    pane: PlotPane,
    ch: ChannelPlot,
    row_idx: int,
    curve_state: tuple[Any, Any, float | None],
) -> ChannelPlot:
    """Recreate *ch* in its target stack layout while preserving data and Y state."""
    xs, ys, page_t0 = curve_state
    target_layout = pane._pinned_layout if ch.pinned else pane.graphics_layout
    rebuilt = create_channel_plot(
        target_layout,
        row_idx,
        ch.reader.cache_dir,
        ch.name,
        ch.color_index,
        pane._request_channel_close,
        ch.reader.time_map,
        ch.reader.source_id,
        row_height=ch.row_height,
        visible=ch.visible,
        existing_reader=ch.reader,
    )
    rebuilt.pinned = ch.pinned
    rebuilt.pinned_in_layout = ch.pinned
    rebuilt.y_mode = ch.y_mode
    rebuilt.y_range = ch.y_range
    rebuilt.gap_times = ch.gap_times
    if ch.unit:
        set_channel_unit(rebuilt, ch.unit)
    if not rebuilt.visible:
        apply_channel_visibility(rebuilt)
    if xs is not None and ys is not None:
        rebuilt.curve.setData(xs, ys)
        rebuilt.page_t0 = page_t0
        if rebuilt.y_range is not None:
            rebuilt.plot_item.setYRange(*rebuilt.y_range, padding=0)
        else:
            fit_channel_y(rebuilt)
    return rebuilt


def rebuild_rows_across_stacks(pane: PlotPane) -> None:
    """Ensure every row in ``pane.channels`` lives in its matching pinned or scroll layout."""
    old_channels = list(pane.channels)
    if not old_channels:
        pane._pinned_layout.hide()
        return

    pane._interactions._hover.discard_items()
    saved_curves: list[tuple[Any, Any, float | None]] = []
    pane.graphics_layout.setUpdatesEnabled(False)
    pane._pinned_layout.setUpdatesEnabled(False)
    try:
        for ch in old_channels:
            xs, ys = ch.curve.getData()
            saved_curves.append((xs, ys, ch.page_t0))
            ch.plot_item.setXLink(None)
            owner = pane._pinned_layout if ch.pinned_in_layout else pane.graphics_layout
            detach_row(owner, ch)

        pane.channels.clear()
        pane._index_cache = None
        pane._master_plot = None
        pinned_row = 0
        scroll_row = 0

        for ch, curve_state in zip(old_channels, saved_curves, strict=True):
            row_idx = pinned_row if ch.pinned else scroll_row
            if ch.pinned:
                pinned_row += 1
            else:
                scroll_row += 1
            rebuilt = _rebuild_one_channel(pane, ch, row_idx, curve_state)
            if pane._master_plot is None:
                pane._master_plot = rebuilt.plot_item
            else:
                if pane.window_duration > 0:
                    rebuilt.plot_item.setXRange(0.0, pane.window_duration, padding=0)
                rebuilt.plot_item.setXLink(pane._master_plot)
            pane._label_axis(rebuilt)
            rebuilt.plot_item.geometryChanged.connect(pane._cull_timer.start)
            pane.channels.append(rebuilt)

        pane._index_cache = None
        pane._link_x_axes()
        pane._relayout_rows()
    finally:
        pane._pinned_layout.setUpdatesEnabled(True)
        pane.graphics_layout.setUpdatesEnabled(True)
    pane._redraw_sweep_overlays()
    if pane.sweep_start is not None:
        pane._set_sweep_for_time(
            pane._warp.to_master(pane._sweep_control.last_master_time), force=False
        )
