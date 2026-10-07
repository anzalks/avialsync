"""Readable, non-overlapping text labels for marks drawn over video or 3D (D-166).

Every overlay that names a point -- props, wheel clicks, the 3D props view --
places its labels here, after its geometry is drawn, so one rule decides where
text goes:

* A label is a small pill: the mark's own colour on a dark, translucent
  backing, so it reads on bright fur, dark bedding and the grey placeholder.
* It tries positions around its mark, nearest first, and takes the first that
  stays inside the picture, clear of other labels, the pane's header and zoom
  controls, and every mark. Among those, it prefers the one crossing the
  fewest drawn lines. A label pushed out past the first ring keeps a thin
  leader line to its mark.
* When every position around the mark is taken, the nearest free spot in the
  picture is used, with a leader line. Only when the picture is full is the
  least-crowded position used rather than hiding the label: a name that
  overlaps is still better than a click with no name.

Line crossings are counted on a coarse occupancy grid, so a belt mesh of
hundreds of segments costs a few thousand set lookups per paint, not a
segment-by-rectangle test for each. Positions are tested against labels, chrome
and marks as arrays, all at once, so a frame of crowded labels lays out in a
few milliseconds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen

__all__ = ["LabelLayout"]

_CELL = 6.0
_GAP = 5.0
_PAD_X = 4.0
_PAD_Y = 1.0
_BACKING = QColor(12, 14, 18, 175)
# Nearest first; right before left and above before below, which is how a
# reader expects a caption to sit beside a point.
_DIRECTIONS = (
    (1.0, -1.0),
    (1.0, 0.0),
    (1.0, 1.0),
    (-1.0, -1.0),
    (-1.0, 0.0),
    (-1.0, 1.0),
    (0.0, -1.0),
    (0.0, 1.0),
)
# Outer rings are for crowded clusters; a label there keeps a leader line.
_RINGS = (1.0, 2.6, 4.2, 6.0, 8.5, 11.5, 15.0)
#: How far from its mark a crowded label may be moved, in pixels.
_FALLBACK_REACH = 160.0
#: Wide searches allowed per paint; past this, crowded labels take the
#: least-crowded ring position so a dense frame still paints in milliseconds.
_FALLBACK_BUDGET = 8


# Every ring position as parallel arrays, nearest first, so a label's
# candidates are computed in one pass.
_RING_OF = np.array([ring for ring in _RINGS for _ in _DIRECTIONS])
_DX = np.array([dx for _ in _RINGS for dx, _ in _DIRECTIONS])
_DY = np.array([dy for _ in _RINGS for _, dy in _DIRECTIONS])


def _edges(rects: list[QRectF]) -> np.ndarray:
    """Left, top, right and bottom of each rectangle, one row each."""
    return np.array(
        [(rect.left(), rect.top(), rect.right(), rect.bottom()) for rect in rects],
        dtype=float,
    ).reshape(-1, 4)


def _meeting(edges: np.ndarray, rect: QRectF) -> np.ndarray:
    """The rows of *edges* that *rect* intersects."""
    hit = (edges[:, 0] < rect.right()) & (rect.left() < edges[:, 2])
    hit &= (edges[:, 1] < rect.bottom()) & (rect.top() < edges[:, 3])
    return edges[hit]


def _overlaps(boxes: np.ndarray, others: np.ndarray) -> np.ndarray:
    """How many of *others* each box meets, as :meth:`QRectF.intersects` decides.

    Every rectangle here has a positive size, so open-interval overlap on both
    axes is exactly Qt's test.
    """
    if not len(others):
        return np.zeros(len(boxes), dtype=int)
    a = boxes[:, None, :]
    b = others[None, :, :]
    meets = (a[..., 0] < b[..., 2]) & (b[..., 0] < a[..., 2])
    meets &= (a[..., 1] < b[..., 3]) & (b[..., 1] < a[..., 3])
    counts: np.ndarray = meets.sum(axis=1)
    return counts


def _spaced(boxes: np.ndarray, width: float, height: float) -> np.ndarray:
    """*boxes* grown by 2 px a side, with :meth:`QRectF.adjusted`'s arithmetic."""
    left = boxes[:, 0] - 2.0
    top = boxes[:, 1] - 2.0
    return np.stack((left, top, left + (width + 4.0), top + (height + 4.0)), axis=1)


@dataclass
class _Label:
    anchor: QPointF
    text: str
    color: QColor
    dashed: bool


class LabelLayout:
    """Collect marks, lines and labels during a paint, then place the labels."""

    def __init__(
        self,
        painter: QPainter,
        bounds: QRectF,
        avoid: tuple[QRectF, ...] = (),
        *,
        mark_radius: float = 5.0,
        backing: QColor | None = None,
    ) -> None:
        self._painter = painter
        self._backing = _BACKING if backing is None else QColor(backing)
        self._bounds = bounds
        self._avoid = [rect for rect in avoid if rect.isValid()]
        self._radius = mark_radius
        self._marks: list[QRectF] = []
        self._cells: set[tuple[int, int]] = set()
        self._labels: list[_Label] = []
        self._searches = 0
        # Obstacle edges as arrays, filled when :meth:`draw` starts.
        self._avoid_edges = np.empty((0, 4))
        self._mark_edges = np.empty((0, 4))
        self._placed_rows: list[tuple[float, float, float, float]] = []
        font = QFont(painter.font())
        if font.pointSizeF() > 0:
            font.setPointSizeF(max(7.0, font.pointSizeF() * 0.9))
        self._font = font
        self._metrics = QFontMetricsF(font)

    def mark(self, point: QPointF, radius: float | None = None) -> None:
        """A drawn point no label may cover."""
        r = self._radius if radius is None else radius
        self._marks.append(QRectF(point.x() - r, point.y() - r, 2 * r, 2 * r))

    def line(self, start: QPointF, end: QPointF) -> None:
        """A drawn line labels should rather not cross."""
        length = math.hypot(end.x() - start.x(), end.y() - start.y())
        steps = max(1, int(length / _CELL))
        for index in range(steps + 1):
            fraction = index / steps
            x = start.x() + (end.x() - start.x()) * fraction
            y = start.y() + (end.y() - start.y()) * fraction
            self._cells.add((int(x // _CELL), int(y // _CELL)))

    def label(self, anchor: QPointF, text: str, color: QColor, *, dashed: bool = False) -> None:
        """Name the mark at *anchor*; placed when :meth:`draw` runs."""
        if text:
            self._labels.append(_Label(anchor, text, QColor(color), dashed))

    def _crossings(self, left: float, top: float, right: float, bottom: float) -> int:
        first_column, first_row = int(left // _CELL), int(top // _CELL)
        last_column, last_row = int(right // _CELL), int(bottom // _CELL)
        return sum(
            (column, row) in self._cells
            for column in range(first_column, last_column + 1)
            for row in range(first_row, last_row + 1)
        )

    def _candidates(self, anchor: QPointF, width: float, height: float) -> np.ndarray:
        """Edges of every ring position round *anchor*, nearest first."""
        reach = self._radius + _GAP * _RING_OF
        x = anchor.x() + _DX * reach
        y = anchor.y() + _DY * reach
        left = np.where(_DX > 0, x, np.where(_DX < 0, x - width, x - width / 2))
        top = np.where(_DY < 0, y - height, np.where(_DY > 0, y, y - height / 2))
        return np.stack((left, top, left + width, top + height), axis=1)

    def _placed_edges(self, placed: list[QRectF]) -> np.ndarray:
        """Edges of *placed*, which only grows during a paint, converted once each."""
        rows = self._placed_rows
        rows.extend(
            (rect.left(), rect.top(), rect.right(), rect.bottom()) for rect in placed[len(rows) :]
        )
        return np.array(rows, dtype=float).reshape(-1, 4)

    def _nearest_free(
        self, anchor: QPointF, width: float, height: float, placed: list[QRectF]
    ) -> QRectF | None:
        """The free spot nearest the mark when every ring position is taken.

        Only crowded clusters get here, and larger system fonts make those more
        likely. The search is confined to a window round the mark, against the
        obstacles inside it, so a paint stays a few milliseconds however many
        labels the frame carries.
        """
        reach = _FALLBACK_REACH
        window = QRectF(
            anchor.x() - reach - width,
            anchor.y() - reach - height,
            2 * (reach + width),
            2 * (reach + height),
        ).intersected(self._bounds)
        near = _meeting(self._placed_edges(placed), window)
        avoid = _meeting(self._avoid_edges, window)
        marks = _meeting(self._mark_edges, window)
        ax, ay = anchor.x(), anchor.y()
        lefts: list[float] = []
        left = window.left()
        while left + width <= window.right():
            lefts.append(left)
            left += max(8.0, width / 3.0)
        tops: list[float] = []
        top = window.top()
        while top + height <= window.bottom():
            tops.append(top)
            top += height / 2.0
        if not lefts or not tops:
            return None
        # Row by row, as a reader scans the window.
        spots = [(left, top) for top in tops for left in lefts]
        distances = [
            math.hypot(left + width / 2.0 - ax, top + height / 2.0 - ay) for left, top in spots
        ]
        corner = np.array(spots, dtype=float)
        boxes = np.concatenate((corner, corner + (width, height)), axis=1)
        free = (_overlaps(_spaced(boxes, width, height), near) == 0) & (
            _overlaps(boxes, avoid) == 0
        )
        if not free.any():
            return None
        cost = np.array(distances) + 40.0 * _overlaps(boxes, marks)
        # argmin keeps the first of equal costs in scanning order.
        best = int(np.argmin(np.where(free, cost, np.inf)))
        return QRectF(spots[best][0], spots[best][1], width, height)

    def _place(self, label: _Label, placed: list[QRectF]) -> tuple[QRectF, bool]:
        width = self._metrics.horizontalAdvance(label.text) + 2 * _PAD_X
        height = self._metrics.height() + 2 * _PAD_Y
        best: tuple[float, int] | None = None
        boxes = self._candidates(label.anchor, width, height)
        # Only obstacles a candidate can reach are worth testing against.
        reach = self._radius + _GAP * _RINGS[-1] + width + height
        region = QRectF(label.anchor.x() - reach, label.anchor.y() - reach, 2 * reach, 2 * reach)
        near = _meeting(self._placed_edges(placed), region)
        avoid = _meeting(self._avoid_edges, region)
        marks = _meeting(self._mark_edges, region)
        bounds = self._bounds
        inside = (
            (boxes[:, 0] >= bounds.left())
            & (boxes[:, 2] <= bounds.right())
            & (boxes[:, 1] >= bounds.top())
            & (boxes[:, 3] <= bounds.bottom())
        ).tolist()
        blocked = (
            (_overlaps(_spaced(boxes, width, height), near) > 0) | (_overlaps(boxes, avoid) > 0)
        ).tolist()
        covered = _overlaps(boxes, marks).tolist()
        for index, edges in enumerate(boxes.tolist()):
            if not inside[index]:
                continue
            if blocked[index]:
                # Overlapping a label or the chrome is ruled out; no need to
                # score how many marks or lines it would also cover.
                cost = 1000.0 + index * 0.5
            else:
                cost = 100.0 * covered[index] + self._crossings(*edges) + index * 0.5
            if best is None or cost < best[0]:
                best = (cost, index)
            if cost < 1.0:
                break
        if (best is None or best[0] >= 1000.0) and self._searches < _FALLBACK_BUDGET:
            self._searches += 1
            free = self._nearest_free(label.anchor, width, height, placed)
            if free is not None:
                return free, True
        if best is None:
            rect = QRectF(float(boxes[0, 0]), float(boxes[0, 1]), width, height)
            # Nothing fits inside the picture: clamp the nearest position in.
            rect.moveLeft(min(max(rect.left(), self._bounds.left()), self._bounds.right() - width))
            rect.moveTop(min(max(rect.top(), self._bounds.top()), self._bounds.bottom() - height))
            return rect, False
        chosen = QRectF(float(boxes[best[1], 0]), float(boxes[best[1], 1]), width, height)
        return chosen, best[1] >= len(_DIRECTIONS)

    def draw(self) -> None:
        """Place every label, short ones first, and paint them over the geometry."""
        painter = self._painter
        painter.save()
        painter.setFont(self._font)
        self._avoid_edges = _edges(self._avoid)
        self._mark_edges = _edges(self._marks)
        self._placed_rows = []
        placed: list[QRectF] = []
        for label in sorted(self._labels, key=lambda item: len(item.text)):
            rect, far = self._place(label, placed)
            placed.append(rect)
            if far:
                nearest = QPointF(
                    min(max(label.anchor.x(), rect.left()), rect.right()),
                    min(max(label.anchor.y(), rect.top()), rect.bottom()),
                )
                faint = QColor(label.color)
                faint.setAlpha(150)
                painter.setPen(QPen(faint, 1.0))
                painter.drawLine(label.anchor, nearest)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._backing)
            painter.drawRoundedRect(rect, 3.0, 3.0)
            text = QColor(label.color)
            if label.dashed:
                text.setAlpha(205)
            painter.setPen(text)
            painter.drawText(
                rect.adjusted(_PAD_X, _PAD_Y, -_PAD_X, -_PAD_Y),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                label.text,
            )
        painter.restore()
