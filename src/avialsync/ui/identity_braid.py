"""Drawing the braid: who is who, over time, and where that changed.

One horizontal line per lane, and a line that *moves* to another lane's row
wherever an accepted flip says the data did.  Two lines crossing is the whole
picture, and it is the picture because it is what happened: the tracker carried
on with the labels exchanged, and the crossing is where.

Underneath it, the separation between the two lanes.  A flip is only possible
where the trajectories came close, so the trace is what makes a node
*plausible* rather than merely asserted -- the same argument the residual plot
makes for an alignment (BLUEPRINT principle 8).  It is decimated by minimum
rather than by stride, because the closest approach is the one value on it that
must survive.

This module knows nothing about stores, selectors or gestures: it is handed a
model and draws it.  The routing in that model comes from
:meth:`avialsync.core.identity_swaps.SwapStore.lane_map`, never recomputed
here, so the picture and the data cannot disagree about who is who.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette

from avialsync.core.identity_detect import Trajectory
from avialsync.ui.i18n import tr
from avialsync.ui.theme import evidence_color, status_color, system_accent

__all__ = ["BraidNode", "BraidModel", "build_model", "draw_braid", "draw_separation"]

#: Never more points than pixels (architecture rule 4).
MAX_POINTS = 800

#: Half-width of a crossing, as a share of the visible span.  Wide enough to
#: read as a crossing rather than a step, narrow enough that two flips a second
#: apart do not merge into one.
_CROSSING = 0.006

#: Rows are one apart and the first lane is on top, which is the order the
#: selector lists them in.
_ROW_GAP = 1.0


@dataclasses.dataclass(frozen=True)
class BraidNode:
    """One place the plot offers to change an identity."""

    index: int
    #: Master time, which is what every other plot in the application shows.
    at: float
    lanes: tuple[str, str]
    accepted: bool
    #: The parts an *accepted* event moves, empty for the whole group and for a
    #: candidate, which has no scope until somebody accepts one. Carried so a
    #: removal takes the scope that was accepted rather than whatever the part
    #: selector happens to show now (D-141).
    parts: tuple[str, ...] = ()
    #: The video frame number for a pose file whose rows are not contiguous.
    display_frame: int | None = None
    #: The evidence, in words, for the line under the plot.
    detail: str = ""


@dataclasses.dataclass(frozen=True)
class BraidModel:
    """Everything the braid draws for one group and one part."""

    lanes: tuple[str, ...]
    #: ``(start index, lane -> the lane whose data it displays)``, ascending.
    #: The first entry always starts at 0, so the whole recording is covered.
    routing: tuple[tuple[int, Mapping[str, str]], ...]
    nodes: tuple[BraidNode, ...]
    #: Master time per sample index.
    times: np.ndarray
    #: ``(time, distance)`` between the pair below, decimated by minimum.
    separation: tuple[np.ndarray, np.ndarray]
    pair: tuple[str, str] | None = None
    #: Video frame numbers; one per pose row, if a frame rate was declared.
    frame_numbers: np.ndarray | None = None

    def row(self, lane: str) -> float:
        """Where *lane*'s own row sits.  First lane on top."""
        return -_ROW_GAP * self.lanes.index(lane) if lane in self.lanes else 0.0

    def span(self) -> tuple[float, float]:
        if len(self.times) == 0:
            return (0.0, 1.0)
        return (float(self.times[0]), float(self.times[-1]))

    def lane_at(self, y: float) -> str | None:
        """Which lane's row is nearest *y*, or None with no lanes."""
        if not self.lanes:
            return None
        return min(self.lanes, key=lambda lane: abs(self.row(lane) - y))

    def nearest_node(self, at: float, tolerance: float) -> BraidNode | None:
        """The node nearest master time *at*, or None outside *tolerance*."""
        if not self.nodes:
            return None
        nearest = min(self.nodes, key=lambda node: abs(node.at - at))
        return nearest if abs(nearest.at - at) <= tolerance else None

    def index_at(self, at: float) -> int:
        """The sample index master time *at* falls on."""
        if len(self.times) == 0:
            return 0
        position = int(np.searchsorted(self.times, at, side="right")) - 1
        return max(0, min(position, len(self.times) - 1))


def build_model(
    lanes: Sequence[str],
    times: np.ndarray,
    routing: Sequence[tuple[int, Mapping[str, str]]],
    nodes: Sequence[BraidNode],
    tracks: Mapping[str, Trajectory],
    limit: int = MAX_POINTS,
    frame_numbers: np.ndarray | None = None,
) -> BraidModel:
    """Assemble what the two plots need, including the separation trace."""
    ordered = tuple(lanes)
    pair = (ordered[0], ordered[1]) if len(ordered) >= 2 else None
    separation = _separation(times, tracks, pair, limit)
    full = tuple(routing) if routing and routing[0][0] == 0 else ((0, {}), *tuple(routing))
    return BraidModel(
        lanes=ordered,
        routing=full,
        nodes=tuple(nodes),
        times=np.asarray(times, dtype=float),
        separation=separation,
        pair=pair,
        frame_numbers=frame_numbers,
    )


def _separation(
    times: np.ndarray,
    tracks: Mapping[str, Trajectory],
    pair: tuple[str, str] | None,
    limit: int,
) -> tuple[np.ndarray, np.ndarray]:
    """How far apart the pair is, decimated so the closest approach survives."""
    empty = (np.zeros(0), np.zeros(0))
    if pair is None or pair[0] not in tracks or pair[1] not in tracks:
        return empty
    first, second = tracks[pair[0]], tracks[pair[1]]
    count = min(len(first.x), len(second.x), len(times))
    if count == 0:
        return empty
    distance = np.hypot(first.x[:count] - second.x[:count], first.y[:count] - second.y[:count])
    return _decimate(np.asarray(times[:count], dtype=float), distance, limit)


def _decimate(times: np.ndarray, values: np.ndarray, limit: int) -> tuple[np.ndarray, np.ndarray]:
    """Keep the minimum of each bucket: the closest approach is the point.

    A stride would drop the frame where the two touched as readily as any
    other, and that frame is the entire reason this trace is drawn.
    """
    count = len(values)
    if count <= limit or count == 0:
        return times, values
    edges = np.linspace(0, count, limit + 1, dtype=int)
    kept_t = np.empty(limit, dtype=float)
    kept_v = np.empty(limit, dtype=float)
    for position in range(limit):
        start, stop = edges[position], max(edges[position + 1], edges[position] + 1)
        window = values[start:stop]
        with np.errstate(invalid="ignore"):
            lowest = int(np.nanargmin(window)) if np.any(~np.isnan(window)) else 0
        kept_t[position] = times[start + lowest]
        kept_v[position] = window[lowest]
    return kept_t, kept_v


def draw_braid(
    plot: pg.PlotItem,
    model: BraidModel,
    palette: QPalette,
    on_node: Callable[[BraidNode], None] | None = None,
) -> None:
    """Draw one line per lane, moving rows wherever an accepted flip says so.

    *on_node* is called with the crossing a click lands on. The marks answer
    for themselves rather than leaving it to the view box underneath: a scatter
    point accepts the press that hits it, so relying on the click reaching the
    view box meant the one thing on this plot a person aims at was the one
    thing that did not respond.
    """
    plot.clear()
    if not model.lanes or len(model.times) == 0:
        return

    low, high = model.span()
    crossing = max((high - low) * _CROSSING, 1e-6)
    accent = system_accent(palette)

    for position, lane in enumerate(model.lanes):
        xs, ys = _lane_path(model, lane, crossing)
        pen = pg.mkPen(
            accent if position % 2 == 0 else palette.color(QPalette.ColorRole.Link),
            width=2,
            style=_style(position),
        )
        plot.plot(xs, ys, pen=pen, name=lane)

    _draw_nodes(plot, model, palette, on_node)

    axis = plot.getAxis("left")
    axis.setTicks([[(model.row(lane), lane) for lane in model.lanes]])
    plot.setYRange(-_ROW_GAP * (len(model.lanes) - 1) - 0.5, 0.5, padding=0)
    plot.setXRange(low, high, padding=0.01)


def _style(position: int) -> Qt.PenStyle:
    """A dash pattern per lane, so two crossing lines stay tellable apart.

    Colour alone does not separate them where they overlap, and does not
    separate them at all under deuteranopia (rule 17, D-094).
    """
    styles = (
        Qt.PenStyle.SolidLine,
        Qt.PenStyle.DashLine,
        Qt.PenStyle.DotLine,
        Qt.PenStyle.DashDotLine,
    )
    return styles[position % len(styles)]


def _lane_path(model: BraidModel, lane: str, crossing: float) -> tuple[list[float], list[float]]:
    """The row *lane* occupies over time, with a diagonal at each change."""
    xs: list[float] = []
    ys: list[float] = []
    low, high = model.span()
    for position, (start, mapping) in enumerate(model.routing):
        row = model.row(mapping.get(lane, lane))
        at = low if position == 0 else float(model.times[min(start, len(model.times) - 1)])
        if position == 0:
            xs.append(at)
            ys.append(row)
        else:
            xs.extend((at - crossing, at + crossing))
            ys.extend((ys[-1], row))
    xs.append(high)
    ys.append(ys[-1])
    return xs, ys


def _draw_nodes(
    plot: pg.PlotItem,
    model: BraidModel,
    palette: QPalette,
    on_node: Callable[[BraidNode], None] | None = None,
) -> None:
    """Accepted flips as filled crossings, candidates as hollow ones."""
    for accepted in (False, True):
        nodes = [node for node in model.nodes if node.accepted is accepted]
        if not nodes:
            continue
        colour = (
            evidence_color(palette, "identity") if accepted else status_color(palette, "warning")
        )
        marks = pg.ScatterPlotItem(
            x=[node.at for node in nodes],
            y=[_node_row(model, node) for node in nodes],
            symbol="d",
            size=13,
            pen=pg.mkPen(colour, width=2),
            brush=pg.mkBrush(colour) if accepted else None,
            data=nodes,
            name=tr("Accepted swap") if accepted else tr("Candidate"),
        )
        if on_node is not None:
            marks.sigClicked.connect(lambda _item, points, _event: _clicked(points, on_node))
        plot.addItem(marks)


def _clicked(points: Sequence[Any], on_node: Callable[[BraidNode], None]) -> None:
    """Report the crossing a click landed on, if it carried one."""
    for point in points:
        node = point.data()
        if isinstance(node, BraidNode):
            on_node(node)
            return


def _node_row(model: BraidModel, node: BraidNode) -> float:
    """Between the two lanes it concerns, which is where a crossing happens."""
    rows = [model.row(lane) for lane in node.lanes if lane in model.lanes]
    return sum(rows) / len(rows) if rows else 0.0


def draw_separation(plot: pg.PlotItem, model: BraidModel, palette: QPalette) -> None:
    """Draw how far apart the pair came, under the braid and on its X axis."""
    plot.clear()
    times, distance = model.separation
    if len(times) == 0:
        return
    plot.plot(
        times,
        distance,
        pen=pg.mkPen(palette.color(QPalette.ColorRole.WindowText), width=1),
    )
    for node in model.nodes:
        plot.addItem(
            pg.InfiniteLine(
                pos=node.at,
                angle=90,
                pen=pg.mkPen(
                    evidence_color(palette, "identity")
                    if node.accepted
                    else status_color(palette, "warning"),
                    width=1,
                    style=_style(1),
                ),
            )
        )
    plot.setXRange(*model.span(), padding=0.01)
