"""Alternative multi-channel plot presentations (Grouped, Overlaid, Heatmap) and row pinning."""

from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING, Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAccessible, QPalette
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from avialsync.core.channel_reader import ChannelKey
from avialsync.ui.accessible_views import register_painted
from avialsync.ui.i18n import tr
from avialsync.ui.plot_group_canvas import (
    GROUP_OVERLAY_LIMIT,
    build_signal_group_bands,
    populate_heatmap_item,
    render_group_band,
)
from avialsync.ui.plot_row import (
    ChannelPlot,
    apply_channel_visibility,
    create_channel_plot,
    detach_row,
    fit_channel_y,
    set_channel_gutter_alias,
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
    "PLOT_MODE_GROUPED",
    "PLOT_MODE_HEATMAP",
    "PLOT_MODE_OVERLAY",
    "PLOT_MODE_STACKED",
    "PlotModeCanvas",
    "toggle_channel_pin",
]

PLOT_MODE_STACKED = "stacked"
PLOT_MODE_GROUPED = "grouped"
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


def _configure_mode_plot_item(plot_item: Any, *, show_bottom: bool) -> None:
    plot_item.setMenuEnabled(False)
    plot_item.setMouseEnabled(x=False, y=False)
    plot_item.enableAutoRange(axis="x", enable=False)
    plot_item.enableAutoRange(axis="y", enable=False)
    plot_item.getAxis("left").setWidth(104)
    plot_item.getAxis("left").enableAutoSIPrefix(False)
    bottom = plot_item.getAxis("bottom")
    bottom.setStyle(showValues=show_bottom)
    bottom.showLabel(show_bottom)
    bottom.enableAutoSIPrefix(show_bottom)
    if show_bottom:
        bottom.setLabel(tr("Master time"), units="s")
    for hidden in ("top", "right"):
        plot_item.getAxis(hidden).enableAutoSIPrefix(False)


class PlotModeCanvas(QWidget):
    """Shared canvas rendering visible channels as Signal Groups, Overlaid traces, or Heatmap."""

    seek_requested = Signal(float)  # page-local x
    context_requested = Signal(object)  # QGraphicsSceneMouseEvent

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode = PLOT_MODE_OVERLAY
        self._curves: list[SweepCurveItem] = []
        self._image_item: pg.ImageItem | None = None
        self._extra_images: list[tuple[Any, pg.ImageItem]] = []
        self._legends: list[pg.LegendItem] = []
        self._extra_plots: list[Any] = []
        self._extra_cursors: list[pg.InfiniteLine] = []
        self._channel_names: list[str] = []
        self.plot_item: Any = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.graphics_layout = PlotStackView(
            lambda: [
                p.getViewBox()
                for p in (
                    [self.plot_item, *self._extra_plots] if self.plot_item is not None else []
                )
            ],
            self,
        )
        self.graphics_layout.setAccessibleName(tr("Combined plot canvas"))
        self.graphics_layout.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.graphics_layout.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.graphics_layout.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setAccessibleName(tr("Grouped plot stack"))
        self._scroll.setWidget(self.graphics_layout)
        layout.addWidget(self._scroll)

        self.plot_item = self.graphics_layout.addPlot(row=0, col=0, enableMenu=False)
        _configure_mode_plot_item(self.plot_item, show_bottom=True)

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
        """Select ``'grouped'``, ``'overlay'``, or ``'heatmap'`` presentation."""
        self._mode = mode

    def apply_palette(self, palette: QPalette) -> None:
        apply_canvas_palette(self.graphics_layout, palette)
        pen = pg.mkPen(playhead_color(palette), width=2)
        self.cursor_line.setPen(pen)
        for line in self._extra_cursors:
            line.setPen(pen)
        if self._mode != PLOT_MODE_GROUPED:
            self.plot_item.showGrid(
                x=True, y=self._mode == PLOT_MODE_OVERLAY, alpha=plot_colors(palette).grid_alpha
            )

    def set_x_window(self, duration: float) -> None:
        if duration > 0:
            self.plot_item.setXRange(0.0, duration, padding=0)

    def set_cursor_phase(self, phase: float, *, reveal: bool) -> None:
        self.cursor_line.setValue(phase)
        for line in self._extra_cursors:
            line.setValue(phase)
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
                self.graphics_layout.setMinimumHeight(0)
                return
            if self._mode == PLOT_MODE_GROUPED:
                self._render_grouped(channels, window_duration, palette, reveal=reveal, phase=phase)
            elif self._mode == PLOT_MODE_HEATMAP:
                self.graphics_layout.setMinimumHeight(0)
                _configure_mode_plot_item(self.plot_item, show_bottom=True)
                self._render_heatmap(visible, window_duration)
            else:
                self.graphics_layout.setMinimumHeight(0)
                _configure_mode_plot_item(self.plot_item, show_bottom=True)
                self._render_overlay(visible, palette, reveal=reveal, phase=phase)
        finally:
            self.graphics_layout.setUpdatesEnabled(True)

    def _clear_items(self) -> None:
        for curve in self._curves:
            with_plot = getattr(curve, "_host_plot", self.plot_item)
            try:
                with_plot.removeItem(curve)
            except RuntimeError:
                pass
        self._curves.clear()
        if self._image_item is not None:
            self.plot_item.removeItem(self._image_item)
            self._image_item = None
        for host, img in self._extra_images:
            try:
                host.removeItem(img)
            except RuntimeError:
                pass
        self._extra_images.clear()
        for legend in self._legends:
            try:
                legend.scene().removeItem(legend)
            except (AttributeError, RuntimeError):
                logger.debug("Legend item was already removed", exc_info=True)
        self._legends.clear()
        for extra_plot in self._extra_plots:
            extra_plot.setXLink(None)
            self.graphics_layout.removeItem(extra_plot)
        self._extra_plots.clear()
        self._extra_cursors.clear()
        self.plot_item.getAxis("left").setTicks(None)

    def _render_grouped(
        self,
        all_channels: list[ChannelPlot],
        window_duration: float,
        palette: QPalette,
        *,
        reveal: bool,
        phase: float,
    ) -> None:
        bands = build_signal_group_bands(all_channels)
        if not bands:
            self.graphics_layout.setMinimumHeight(0)
            return
        cursor_pen = pg.mkPen(playhead_color(palette), width=2)
        total_min_h = 0
        for row_idx, band in enumerate(bands):
            is_last = row_idx == len(bands) - 1
            if row_idx == 0:
                p_item = self.plot_item
                _configure_mode_plot_item(p_item, show_bottom=is_last)
            else:
                p_item = pg.PlotItem(enableMenu=False)
                _configure_mode_plot_item(p_item, show_bottom=is_last)
                self.graphics_layout.addItem(p_item, row=row_idx, col=0)
                if window_duration > 0:
                    p_item.setXRange(0.0, window_duration, padding=0)
                p_item.setXLink(self.plot_item)
                c_line = pg.InfiniteLine(pos=phase, angle=90, movable=False, pen=cursor_pen)
                c_line.setZValue(10)
                p_item.addItem(c_line, ignoreBounds=True)
                self._extra_plots.append(p_item)
                self._extra_cursors.append(c_line)

            band_h = 135 if len(band.channels) > GROUP_OVERLAY_LIMIT else 105
            p_item.setMinimumHeight(band_h)
            total_min_h += band_h + 6

            curves, img, legend = render_group_band(
                p_item,
                band,
                window_duration,
                palette,
                _HEATMAP_LUT,
                reveal=reveal,
                phase=phase,
            )
            for curve in curves:
                curve._host_plot = p_item  # type: ignore[attr-defined]
                self._curves.append(curve)
            if img is not None:
                if row_idx == 0:
                    self._image_item = img
                else:
                    self._extra_images.append((p_item, img))
            if legend is not None:
                self._legends.append(legend)

        self.graphics_layout.setMinimumHeight(total_min_h if len(bands) > 1 else 0)

    def _render_overlay(
        self,
        visible: list[ChannelPlot],
        palette: QPalette,
        *,
        reveal: bool,
        phase: float,
    ) -> None:
        self.plot_item.setMinimumHeight(0)
        self.plot_item.showGrid(x=True, y=True, alpha=plot_colors(palette).grid_alpha)
        units = {ch.unit for ch in visible if ch.unit}
        unit_label = f" ({next(iter(units))})" if len(units) == 1 else ""
        self.plot_item.setLabel("left", html.escape(tr("Overlaid") + unit_label))

        legend: pg.LegendItem | None = None
        if len(visible) <= 12:
            legend = self.plot_item.addLegend(offset=(-10, 10))
            self._legends.append(legend)
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
                short = ch.gutter_alias[1] if ch.gutter_alias[0] == ch.name else ch.name
                label = f"{short} ({ch.unit})" if ch.unit else short
                curve = SweepCurveItem(pen=pen, connect="finite", name=label)
                curve.set_reveal_enabled(reveal)
                curve.set_sweep_position(phase)
                if xs is not None and ys is not None and len(xs) > 0:
                    curve.setData(xs, ys)
                    finite = np.asarray(ys)[np.isfinite(ys)]
                    if len(finite):
                        y_min = min(y_min, float(finite.min()))
                        y_max = max(y_max, float(finite.max()))
                curve._host_plot = self.plot_item  # type: ignore[attr-defined]
                self.plot_item.addItem(curve)
                self._curves.append(curve)
                if legend is not None:
                    legend.addItem(curve, html.escape(label))
        else:
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
                curve._host_plot = self.plot_item  # type: ignore[attr-defined]
                self.plot_item.addItem(curve)
                self._curves.append(curve)

        if np.isfinite(y_min) and np.isfinite(y_max):
            pad = max(1e-3, (y_max - y_min) * 0.08) if not np.isclose(y_min, y_max) else 1.0
            self.plot_item.setYRange(y_min - pad, y_max + pad, padding=0)
        else:
            self.plot_item.setYRange(-1.0, 1.0, padding=0)

    def _render_heatmap(self, visible: list[ChannelPlot], window_duration: float) -> None:
        self.plot_item.setMinimumHeight(0)
        self.plot_item.showGrid(x=False, y=False)
        self.plot_item.setLabel("left", html.escape(tr("Channels")))
        labels = [
            ch.gutter_alias[1] if ch.gutter_alias[0] == ch.name and ch.gutter_alias[1] else ch.name
            for ch in visible
        ]
        self._image_item = populate_heatmap_item(
            self.plot_item, visible, labels, window_duration, _HEATMAP_LUT
        )

    def _on_clicked(self, event: Any) -> None:
        scene_pos = event.scenePos()
        target_vb = None
        for p_item in (self.plot_item, *self._extra_plots):
            if p_item is not None and p_item.vb.sceneBoundingRect().contains(scene_pos):
                target_vb = p_item.vb
                break
        if target_vb is None:
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
        x = float(target_vb.mapSceneToView(scene_pos).x())
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
    if ch.gutter_alias[0] == ch.name and ch.gutter_alias[1]:
        set_channel_gutter_alias(rebuilt, ch.gutter_alias[1])
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
