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
segment-by-rectangle test for each.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

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

    def _crossings(self, rect: QRectF) -> int:
        left, top = int(rect.left() // _CELL), int(rect.top() // _CELL)
        right, bottom = int(rect.right() // _CELL), int(rect.bottom() // _CELL)
        return sum(
            (column, row) in self._cells
            for column in range(left, right + 1)
            for row in range(top, bottom + 1)
        )

    def _candidates(self, anchor: QPointF, width: float, height: float) -> list[QRectF]:
        rects: list[QRectF] = []
        for ring in _RINGS:
            reach = self._radius + _GAP * ring
            for dx, dy in _DIRECTIONS:
                x = anchor.x() + dx * reach
                y = anchor.y() + dy * reach
                left = x if dx > 0 else x - width if dx < 0 else x - width / 2
                top = y - height if dy < 0 else y if dy > 0 else y - height / 2
                rects.append(QRectF(left, top, width, height))
        return rects

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
        near = [rect for rect in placed if rect.intersects(window)]
        avoid = [rect for rect in self._avoid if rect.intersects(window)]
        marks = [rect for rect in self._marks if rect.intersects(window)]
        best: tuple[float, QRectF] | None = None
        top = window.top()
        while top + height <= window.bottom():
            left = window.left()
            while left + width <= window.right():
                rect = QRectF(left, top, width, height)
                spaced = rect.adjusted(-2.0, -2.0, 2.0, 2.0)
                if not any(spaced.intersects(other) for other in near) and not any(
                    rect.intersects(other) for other in avoid
                ):
                    centre = rect.center()
                    cost = math.hypot(centre.x() - anchor.x(), centre.y() - anchor.y())
                    cost += 40.0 * sum(rect.intersects(other) for other in marks)
                    if best is None or cost < best[0]:
                        best = (cost, rect)
                left += max(8.0, width / 3.0)
            top += height / 2.0
        return None if best is None else best[1]

    def _place(self, label: _Label, placed: list[QRectF]) -> tuple[QRectF, bool]:
        width = self._metrics.horizontalAdvance(label.text) + 2 * _PAD_X
        height = self._metrics.height() + 2 * _PAD_Y
        best: tuple[float, int, QRectF] | None = None
        candidates = self._candidates(label.anchor, width, height)
        # Only obstacles a candidate can reach are worth testing against.
        reach = self._radius + _GAP * _RINGS[-1] + width + height
        region = QRectF(label.anchor.x() - reach, label.anchor.y() - reach, 2 * reach, 2 * reach)
        near = [rect for rect in placed if rect.intersects(region)]
        avoid = [rect for rect in self._avoid if rect.intersects(region)]
        marks = [rect for rect in self._marks if rect.intersects(region)]
        for index, rect in enumerate(candidates):
            if not self._bounds.contains(rect):
                continue
            spaced = rect.adjusted(-2.0, -2.0, 2.0, 2.0)
            if any(spaced.intersects(other) for other in near) or any(
                rect.intersects(other) for other in avoid
            ):
                # Overlapping a label or the chrome is ruled out; no need to
                # score how many marks or lines it would also cover.
                cost = 1000.0 + index * 0.5
            else:
                covered = sum(rect.intersects(other) for other in marks)
                cost = 100.0 * covered + self._crossings(rect) + index * 0.5
            if best is None or cost < best[0]:
                best = (cost, index, rect)
            if cost < 1.0:
                break
        if (best is None or best[0] >= 1000.0) and self._searches < _FALLBACK_BUDGET:
            self._searches += 1
            free = self._nearest_free(label.anchor, width, height, placed)
            if free is not None:
                return free, True
        if best is None:
            rect = candidates[0]
            # Nothing fits inside the picture: clamp the nearest position in.
            rect.moveLeft(min(max(rect.left(), self._bounds.left()), self._bounds.right() - width))
            rect.moveTop(min(max(rect.top(), self._bounds.top()), self._bounds.bottom() - height))
            return rect, False
        return best[2], best[1] >= len(_DIRECTIONS)

    def draw(self) -> None:
        """Place every label, short ones first, and paint them over the geometry."""
        painter = self._painter
        painter.save()
        painter.setFont(self._font)
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
