"""Applying the live application palette to pyqtgraph canvases.

pyqtgraph does not participate in Qt's palette system.  It paints onto its own
scene, and its colours come from module-level config options that are read
*once*, when an item is constructed, and never consulted again.  A palette
change therefore reaches every ordinary widget in the window and stops at the
edge of a plot: the graph keeps the background, the axis lines, the tick
numbers and the axis titles it was born with.

That is the whole reason this module exists.  Everything here is the
application step — walking live scene objects and re-penning them.  What the
colours *are* is decided in :mod:`avialsync.ui.theme`, with every other colour
in the application, so there is one authority per user-visible concept (D-092)
and pyqtgraph stays out of that module.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QPen

from avialsync.ui.theme import (
    PlotColors,
    coverage_edge_color,
    evidence_color,
    loop_pin_color,
    plot_colors,
)


def apply_canvas_palette(view: pg.GraphicsView, palette: QPalette) -> PlotColors:
    """Repaint *view*'s background and every axis in it for *palette*.

    Returns the colours used, so a caller that also owns per-row graphics can
    finish the job without solving the palette a second time.

    The plots are found through the scene rather than through a layout, because
    the two callers hold different containers — a ``GraphicsLayoutWidget`` of
    stacked rows, and a single ``PlotWidget`` — and every plot in either is an
    item in its scene.
    """
    colors = plot_colors(palette)
    view.setBackground(colors.canvas)
    for item in view.scene().items():
        if isinstance(item, pg.PlotItem):
            apply_plot_item_palette(item, colors)
    return colors


def apply_plot_item_palette(plot_item: pg.PlotItem, colors: PlotColors) -> None:
    """Re-pen one plot's axes, ticks, tick labels, and axis titles.

    Three separately-coloured things per axis, which is why a theme switch used
    to move none of them:

    ``setPen`` draws the axis line and the tick marks — and the grid, which
    pyqtgraph strokes with the same pen at reduced alpha.  ``setTextPen`` draws
    the tick numbers.  Neither touches the axis *title*, which pyqtgraph keeps
    in a separate ``labelStyle`` defaulting to a literal mid-grey that is
    low-contrast on a light canvas and lower on a dark one.

    The title is re-styled by handing ``setLabel`` its own current text, units
    and visibility back.  pyqtgraph 0.14 treats a ``None`` text as "no label"
    and hides it, so the earlier ``setLabel(color=…)`` emptied every channel's
    name/unit/range gutter on the first theme switch — the gutter was blank in
    the Light screenshot and in any session switched after load
    (INTERFACE_DESIGN_PLAN F-27).  A later label rewrite — the channel
    gutter's, say — passes no style of its own and keeps this colour.
    """
    for name in ("left", "right", "top", "bottom"):
        axis = plot_item.getAxis(name)
        if axis is None:
            continue
        axis.setPen(colors.axis)
        axis.setTextPen(colors.axis)
        shown = axis.label.isVisibleTo(axis)
        axis.setLabel(
            axis.labelText or None,
            units=axis.labelUnits or None,
            unitPrefix=axis.labelUnitPrefix or None,
            unitPower=axis.unitPower,
            color=colors.axis.name(),
        )
        axis.showLabel(shown)


def apply_coverage_region_palette(region: pg.LinearRegionItem, palette: QPalette) -> None:
    """Re-pen the two rules bounding a coverage wash, idle and hovered alike."""
    pen = pg.mkPen(coverage_edge_color(palette), width=1)
    for line in region.lines:
        line.setPen(pen)
        line.setHoverPen(pen)


def gap_marker_pen(palette: QPalette) -> QPen:
    """Return the pen for retained gap evidence drawn over a plot row.

    Dotted, and the same derived defect colour the timeline's gap lane uses, so
    "the data stops here" reads identically in the overview and in the plot
    rather than being one red in one place and a different red in the other.
    """
    # Wrapped rather than returned straight through: pyqtgraph ships no type
    # information, so `mkPen` is `Any` and would silently widen every caller.
    # The copy constructor costs nothing â€” a QPen is implicitly shared.
    return QPen(pg.mkPen(color=evidence_color(palette, "gap"), width=1, style=Qt.PenStyle.DotLine))


def identity_marker_pen(palette: QPalette) -> QPen:
    """Dash a flip boundary in the same palette role as the identity lane."""
    return QPen(
        pg.mkPen(color=evidence_color(palette, "identity"), width=2, style=Qt.PenStyle.DashLine)
    )


def measure_pen(palette: QPalette, which: str) -> QPen:
    """Return the pen for the A or B measurement pin.

    Shares :func:`~avialsync.ui.theme.loop_pin_color` with the transport's A/B
    loop pins: the same two letters mark the same two points, so a reader who
    has learned the pair on the scrub bar already knows them on the plot. The
    literal green and red this replaces agreed with neither, and neither of them
    followed the theme.
    """
    return QPen(pg.mkPen(color=loop_pin_color(palette, which), width=2, style=Qt.PenStyle.DashLine))
