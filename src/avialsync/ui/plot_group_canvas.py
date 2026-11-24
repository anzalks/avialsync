"""Signal-grouped band partitioning and rendering for PlotModeCanvas."""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPalette

from avialsync.ui.channel_tree import channel_tree_paths
from avialsync.ui.i18n import tr
from avialsync.ui.plot_row import ChannelPlot
from avialsync.ui.plot_sweep import SweepCurveItem
from avialsync.ui.theme import plot_colors, trace_color

#: Maximum channels drawn as overlaid traces inside one signal-group band;
#: denser groups (e.g. 16-200 ROIs or 32 electrodes) render as a Viridis raster.
GROUP_OVERLAY_LIMIT = 8

_PEN_STYLES = (
    Qt.PenStyle.SolidLine,
    Qt.PenStyle.DashLine,
    Qt.PenStyle.DotLine,
    Qt.PenStyle.DashDotLine,
)


@dataclass(frozen=True)
class SignalGroupBand:
    """One coherent signal band sharing source, hierarchy group, and physical unit."""

    source_id: str
    title: str
    unit: str
    channels: tuple[ChannelPlot, ...]
    leaves: tuple[str, ...]


def build_signal_group_bands(all_channels: list[ChannelPlot]) -> list[SignalGroupBand]:
    """Partition visible *all_channels* into coherent per-group plot bands."""
    paths_by_source: dict[str, dict[str, list[str]]] = {}
    names_by_source: dict[str, list[str]] = {}
    for ch in all_channels:
        names_by_source.setdefault(ch.reader.source_id, []).append(ch.name)
    for src, names in names_by_source.items():
        paths_by_source[src] = channel_tree_paths(names)

    visible = [ch for ch in all_channels if ch.visible]
    if not visible:
        return []

    buckets: dict[tuple[str, str, str], list[tuple[ChannelPlot, list[str]]]] = {}
    raw_titles: dict[tuple[str, str, str], str] = {}
    for ch in visible:
        src = ch.reader.source_id
        parts = paths_by_source.get(src, {}).get(ch.name, [ch.name])
        if len(parts) > 1:
            group_key = "/".join(parts[:-1])
            title = parts[-2] if len(parts) == 2 else f"{parts[-3]} · {parts[-2]}"
        else:
            group_key = f"__solo__:{ch.name}"
            title = parts[0]
        bkey = (src, group_key, ch.unit)
        buckets.setdefault(bkey, []).append((ch, parts))
        raw_titles[bkey] = title

    title_sources: dict[str, set[str]] = {}
    for (src, _gk, _unit), title in raw_titles.items():
        title_sources.setdefault(title, set()).add(src)

    bands: list[SignalGroupBand] = []
    for bkey, entries in buckets.items():
        src, _gk, unit = bkey
        title = raw_titles[bkey]
        if len(title_sources.get(title, ())) > 1 and src:
            title = f"{title} · {Path(src).stem}"
        bands.append(
            SignalGroupBand(
                source_id=src,
                title=title,
                unit=unit,
                channels=tuple(ch for ch, _ in entries),
                leaves=tuple(parts[-1] for _, parts in entries),
            )
        )
    return bands


def populate_heatmap_item(
    plot_item: Any,
    channels: tuple[ChannelPlot, ...] | list[ChannelPlot],
    labels: tuple[str, ...] | list[str],
    window_duration: float,
    heatmap_lut: np.ndarray,
) -> pg.ImageItem:
    """Render *channels* as a row-normalized 2D Viridis carpet on *plot_item*."""
    n_rows = len(channels)
    n_bins = 256
    dur = max(window_duration, 1e-6)
    grid_x = np.linspace(0.0, dur, n_bins)
    matrix = np.zeros((n_bins, n_rows), dtype=np.float32)
    sampled_rows = np.full((n_rows, n_bins), np.nan, dtype=float)
    valid_row_mask = np.zeros(n_rows, dtype=bool)

    for row_idx, ch in enumerate(channels):
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
    img.setLookupTable(heatmap_lut)
    img.setLevels([0.0, 1.0])
    img.setRect(QRectF(0.0, 0.0, dur, float(n_rows)))
    img.setZValue(1)
    plot_item.addItem(img)
    plot_item.setYRange(0.0, float(n_rows), padding=0)

    max_ticks = 6 if n_rows <= 24 else 8
    step = max(1, (n_rows + max_ticks - 1) // max_ticks)
    ticks = [
        (
            float(n_rows - 1 - i) + 0.5,
            labels[i] if len(labels[i]) <= 16 else f"…{labels[i][-15:]}",
        )
        for i in range(0, n_rows, step)
    ]
    plot_item.getAxis("left").setTicks([ticks])
    return img


def render_group_band(
    plot_item: Any,
    band: SignalGroupBand,
    window_duration: float,
    palette: QPalette,
    heatmap_lut: np.ndarray,
    *,
    reveal: bool,
    phase: float,
) -> tuple[list[SweepCurveItem], pg.ImageItem | None, pg.LegendItem | None]:
    """Populate *plot_item* for one *band* as overlaid traces or a dense raster."""
    curves: list[SweepCurveItem] = []
    legend: pg.LegendItem | None = None
    n_ch = len(band.channels)

    if n_ch > GROUP_OVERLAY_LIMIT:
        plot_item.showGrid(x=False, y=False)
        meta = tr("{count} ch").format(count=n_ch)
        if band.unit:
            meta = f"{meta} · {band.unit}"
        gutter = f"{html.escape(band.title)}<br/>({html.escape(meta)})"
        plot_item.getAxis("left").setLabel(gutter)
        img = populate_heatmap_item(
            plot_item, band.channels, band.leaves, window_duration, heatmap_lut
        )
        return curves, img, None

    plot_item.showGrid(x=True, y=True, alpha=plot_colors(palette).grid_alpha)
    gutter_lines = [html.escape(band.title)]
    if band.unit:
        gutter_lines.append(html.escape(f"({band.unit})"))
    plot_item.getAxis("left").setLabel("<br/>".join(gutter_lines))

    if n_ch > 1:
        legend = plot_item.addLegend(offset=(-10, 8))
    y_min = float("inf")
    y_max = float("-inf")
    for idx, (ch, leaf) in enumerate(zip(band.channels, band.leaves, strict=True)):
        xs, ys = ch.curve.getData()
        style = _PEN_STYLES[(idx // 6) % len(_PEN_STYLES)] if n_ch > 1 else Qt.PenStyle.SolidLine
        pen = pg.mkPen(color=trace_color(palette, ch.color_index), width=1.4, style=style)
        curve = SweepCurveItem(pen=pen, connect="finite", name=leaf)
        curve.set_reveal_enabled(reveal)
        curve.set_sweep_position(phase)
        if xs is not None and ys is not None and len(xs) > 0:
            curve.setData(xs, ys)
            finite = np.asarray(ys)[np.isfinite(ys)]
            if len(finite):
                y_min = min(y_min, float(finite.min()))
                y_max = max(y_max, float(finite.max()))
        plot_item.addItem(curve)
        curves.append(curve)
        if legend is not None:
            legend.addItem(curve, html.escape(leaf))

    if np.isfinite(y_min) and np.isfinite(y_max):
        pad = max(1e-3, (y_max - y_min) * 0.08) if not np.isclose(y_min, y_max) else 1.0
        plot_item.setYRange(y_min - pad, y_max + pad, padding=0)
    else:
        plot_item.setYRange(-1.0, 1.0, padding=0)
    return curves, None, legend
