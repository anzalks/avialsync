"""Synchronized hover crosshair, inline value pill, and on-canvas A/B measure callouts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

from avialsync.ui.plot_theme import measure_pen

if TYPE_CHECKING:
    from avialsync.ui.plot_row import ChannelPlot

logger = logging.getLogger(__name__)

__all__ = [
    "HoverCrosshair",
    "format_measure_delta",
    "redraw_measure_callouts",
]


def _hover_pen(palette: QPalette) -> object:
    color = QColor(palette.color(QPalette.ColorRole.Text))
    color.setAlpha(115)
    return pg.mkPen(color, width=1, style=Qt.PenStyle.DotLine)


def _pill_colors(palette: QPalette) -> tuple[QColor, QColor, QColor]:
    bg = QColor(palette.color(QPalette.ColorRole.Base))
    bg.setAlpha(215)
    fg = QColor(palette.color(QPalette.ColorRole.Text))
    border = QColor(palette.color(QPalette.ColorRole.Mid))
    border.setAlpha(180)
    return bg, fg, border


def _safe_remove_item(plot_item: pg.PlotItem, item: object) -> None:
    try:
        plot_item.removeItem(item)
    except RuntimeError:
        logger.debug("Plot item was already removed", exc_info=True)


class HoverCrosshair:
    """Lightweight hover hairline across visible plot rows + inline value readout."""

    def __init__(self) -> None:
        self._lines: dict[int, tuple[pg.PlotItem, pg.InfiniteLine]] = {}
        self._pill: pg.TextItem | None = None
        self._pill_host: pg.PlotItem | None = None
        self._pen_rgba: int | None = None
        self._pen: object = None
        self.last_hover_time: float | None = None

    def update(
        self,
        channels: list[ChannelPlot],
        hovered: ChannelPlot | None,
        x_page: float,
        t_master: float,
        palette: QPalette,
    ) -> None:
        """Move hover hairlines to *x_page* and show *hovered*'s sample at *t_master*."""
        self.last_hover_time = t_master
        self._sync_hairlines(channels, x_page, palette)
        if hovered is None or not hovered.visible:
            self._hide_pill()
            return
        self._update_pill(hovered, x_page, t_master, palette)

    def _sync_hairlines(
        self,
        channels: list[ChannelPlot],
        x_page: float,
        palette: QPalette,
    ) -> None:
        rgba = palette.color(QPalette.ColorRole.Text).rgba()
        pen_changed = rgba != self._pen_rgba or self._pen is None
        if pen_changed:
            self._pen_rgba = rgba
            self._pen = _hover_pen(palette)
        pen = self._pen

        active = [ch for ch in channels if ch.visible and not getattr(ch, "culled", False)]
        alive_ids = {id(ch.plot_item) for ch in active}
        for key in list(self._lines):
            if key not in alive_ids:
                plot_item, line = self._lines.pop(key)
                _safe_remove_item(plot_item, line)

        for ch in active:
            pid = id(ch.plot_item)
            entry = self._lines.get(pid)
            if entry is None:
                line = pg.InfiniteLine(pos=x_page, angle=90, movable=False, pen=pen)
                line.setZValue(6)
                ch.plot_item.addItem(line, ignoreBounds=True)
                self._lines[pid] = (ch.plot_item, line)
            else:
                _, line = entry
                if pen_changed:
                    line.setPen(pen)
                line.setValue(x_page)
                if not line.isVisible():
                    line.show()

    def _update_pill(
        self,
        hovered: ChannelPlot,
        x_page: float,
        t_master: float,
        palette: QPalette,
    ) -> None:
        sample = hovered.reader.available_sample_at(t_master)
        val_str = "—" if sample is None else f"{sample[1]:.4g}"
        unit_str = f" {hovered.unit}" if hovered.unit else ""
        text = f"{t_master:.3f} s · {val_str}{unit_str}"

        bg, fg, border = _pill_colors(palette)
        if self._pill is None:
            self._pill = pg.TextItem(text=text, color=fg, fill=bg, border=pg.mkPen(border, width=1))
            self._pill.setZValue(12)
        else:
            self._pill.setColor(fg)
            self._pill.fill = pg.mkBrush(bg)
            self._pill.border = pg.mkPen(border, width=1)
            self._pill.setText(text)

        if self._pill_host is not hovered.plot_item:
            if self._pill_host is not None:
                _safe_remove_item(self._pill_host, self._pill)
            hovered.plot_item.addItem(self._pill, ignoreBounds=True)
            self._pill_host = hovered.plot_item

        view_range = hovered.plot_item.vb.viewRange()
        x_lo, x_hi = view_range[0]
        y_lo, y_hi = view_range[1]
        anchor_right = x_page > (x_lo + x_hi) * 0.65
        self._pill.setAnchor((1.0 if anchor_right else 0.0, 0.0))
        self._pill.setPos(x_page, y_hi - (y_hi - y_lo) * 0.04)
        self._pill.show()

    def clear(self) -> bool:
        """Hide hover hairlines and pill; returns True if hover was active."""
        was_active = self.last_hover_time is not None
        self.last_hover_time = None
        for _, line in self._lines.values():
            line.hide()
        self._hide_pill()
        return was_active

    def discard_items(self) -> None:
        """Remove all graphics items before rows are torn down."""
        self.last_hover_time = None
        for plot_item, line in self._lines.values():
            _safe_remove_item(plot_item, line)
        self._lines.clear()
        if self._pill is not None and self._pill_host is not None:
            _safe_remove_item(self._pill_host, self._pill)
        self._pill = None
        self._pill_host = None

    def _hide_pill(self) -> None:
        if self._pill is not None:
            self._pill.hide()


def format_measure_delta(channel: ChannelPlot, t_a: float, t_b: float) -> str:
    """Format ``Δt``, ``Hz``, and ``Δy`` between *t_a* and *t_b* for *channel*."""
    t_lo, t_hi = (t_a, t_b) if t_a <= t_b else (t_b, t_a)
    dt = t_hi - t_lo
    hz_part = f" ({1.0 / dt:.2f} Hz)" if dt > 1e-6 else ""
    sa = channel.reader.available_sample_at(t_lo)
    sb = channel.reader.available_sample_at(t_hi)
    if sa is not None and sb is not None:
        dy = sb[1] - sa[1]
        unit = f" {channel.unit}" if channel.unit else ""
        return f"Δt {dt:.3f} s{hz_part} · Δy {dy:+.4g}{unit}"
    return f"Δt {dt:.3f} s{hz_part}"


def _add_channel_callout(
    ch: ChannelPlot,
    span: tuple[float, float],
    t_lo: float,
    t_hi: float,
    shade: QColor,
    bg: QColor,
    fg: QColor,
    border_pen: object,
) -> list[tuple[pg.PlotItem, object]]:
    region = pg.LinearRegionItem(
        values=list(span),
        movable=False,
        brush=pg.mkBrush(shade),
        pen=pg.mkPen(None),
    )
    region.setZValue(-4)
    ch.plot_item.addItem(region, ignoreBounds=True)

    label = format_measure_delta(ch, t_lo, t_hi)
    badge = pg.TextItem(text=label, color=fg, fill=bg, border=border_pen)
    badge.setAnchor((0.5, 0.0))
    y_lo, y_hi = ch.plot_item.vb.viewRange()[1]
    badge.setPos((span[0] + span[1]) * 0.5, y_hi - (y_hi - y_lo) * 0.06)
    badge.setZValue(11)
    ch.plot_item.addItem(badge, ignoreBounds=True)
    return [(ch.plot_item, region), (ch.plot_item, badge)]


def redraw_measure_callouts(
    channels: list[ChannelPlot],
    measure_a: float | None,
    measure_b: float | None,
    x_range: Callable[[float, float], tuple[float, float] | None],
    old_items: list[tuple[pg.PlotItem, object]],
    palette: QPalette,
) -> list[tuple[pg.PlotItem, object]]:
    """Draw shaded span + ``Δt``/``Δy`` callout badges when both Measure A and B exist."""
    for plot_item, item in old_items:
        _safe_remove_item(plot_item, item)
    if measure_a is None or measure_b is None:
        return []
    t_lo, t_hi = min(measure_a, measure_b), max(measure_a, measure_b)
    span = x_range(t_lo, t_hi)
    if span is None:
        return []

    bg, fg, _ = _pill_colors(palette)
    accent = measure_pen(palette, "in").color()
    shade = QColor(accent)
    shade.setAlpha(28)
    border_pen = pg.mkPen(accent, width=1)
    new_items: list[tuple[pg.PlotItem, object]] = []
    for ch in channels:
        if ch.visible and not getattr(ch, "culled", False):
            new_items.extend(_add_channel_callout(ch, span, t_lo, t_hi, shade, bg, fg, border_pen))
    return new_items
