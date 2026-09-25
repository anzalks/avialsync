"""How a wheel is drawn over a camera's video (D-113).

The wheel is a model -- a handful of clicked bars and a bar count, turned by an
encoder -- so it must never be read as tracking. Each bar is a **thin line from
end to end**, a shape nothing else on the frame uses: tracked points are dots,
hand-placed markers are rings, reprojected points are crosses (AGENTS rule 17:
the kinds are told apart by shape, not by colour). The colour is neutral, not a
body part's, for the same reason.

* Bars the camera sees: a light line over a dark underlay, readable on fur and
  on the wheel's own metal.
* Bars behind the side plate: faint, and only on their own layer
  (``tracking.wheel_hidden``), because "hidden" is the model's estimate.
* Bar 0 -- the first bar clicked -- carries a small tick, so a turn can be
  followed by eye and checked against the footage.
* While the wheel is being placed and before it is accepted, it is drawn
  **dashed**: a proposal, not a result. Actual clicks are labelled rings;
  projections into unclicked views are dashed diamonds labelled as projected.

Painting only: what to draw arrives as a :class:`WheelDrawing`, already
projected into this camera's pixels by the controller.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from avialsync.ui.i18n import tr

__all__ = ["WheelBar", "WheelDrawing", "draw_wheel", "draw_wheel_clicks"]

_UNDERLAY = QColor(0, 0, 0, 170)
#: A bar's body when its diameter is set: light, and see-through, so the edges
#: of the real bar stay visible to line it up against.
_BODY = QColor(255, 255, 255, 70)
_BAR = QColor(235, 235, 235, 230)
_HIDDEN = QColor(235, 235, 235, 70)
_CLICK_RADIUS = 5
_TICK = 4.0


@dataclass(frozen=True)
class WheelBar:
    """One bar, projected: its two ends in video pixels and how to draw it."""

    x1: float
    y1: float
    x2: float
    y2: float
    #: The camera sees this bar rather than the side plate hiding it.
    facing: bool = True
    #: Not accepted yet: drawn dashed.
    preview: bool = False
    #: Bar 0, the first one clicked.
    first: bool = False
    #: The bar's diameter in video pixels at its middle; 0 when none is set.
    width: float = 0.0


@dataclass(frozen=True)
class WheelDrawing:
    """Everything wheel-related to draw on one camera for one frame."""

    bars: tuple[WheelBar, ...] = ()
    #: ``(label, x, y)`` per click of a placement in progress, e.g. ``("2b", x, y)``.
    clicks: tuple[tuple[str, float, float], ...] = ()
    #: The 2D view of a point located by other cameras, not an observed click.
    projections: tuple[tuple[str, float, float], ...] = ()
    #: Placement cue in this camera, empty after placement.
    prompt: str = ""


def _pen(color: QColor, width: float, dashed: bool) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    if dashed:
        pen.setStyle(Qt.PenStyle.DashLine)
    return pen


def draw_wheel(
    painter: QPainter,
    drawing: WheelDrawing,
    scale: float,
    offset_x: float,
    offset_y: float,
    *,
    show_facing: bool,
    show_hidden: bool,
) -> None:
    """Draw *drawing* with the video mapped by *scale* and *offset*.

    A preview and the clicks behind it are drawn whatever the layers say:
    placing a wheel with nothing on screen to check it against is not a mode
    anyone can use (the reason Fix Tracker shows hidden points too).
    """

    def screen(x: float, y: float) -> QPointF:
        return QPointF(offset_x + x * scale, offset_y + y * scale)

    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for bar in drawing.bars:
        if not bar.preview and not (show_facing if bar.facing else show_hidden):
            continue
        start, end = screen(bar.x1, bar.y1), screen(bar.x2, bar.y2)
        if bar.facing and bar.width * scale > 1.0:
            # The bar's body, as wide as its diameter projects: what the slider
            # is matched against. Translucent, so the video shows through.
            body = QPen(_BODY, bar.width * scale)
            body.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(body)
            painter.drawLine(start, end)
        if bar.facing:
            painter.setPen(_pen(_UNDERLAY, 3.5, bar.preview))
            painter.drawLine(start, end)
            painter.setPen(_pen(_BAR, 1.5, bar.preview))
        else:
            painter.setPen(_pen(_HIDDEN, 1.0, bar.preview))
        painter.drawLine(start, end)
        if bar.first and bar.facing:
            painter.setPen(_pen(_BAR, 1.5, False))
            painter.drawEllipse(start, _TICK, _TICK)
    painter.restore()


def draw_wheel_clicks(
    painter: QPainter, drawing: WheelDrawing, scale: float, offset_x: float, offset_y: float
) -> None:
    """Draw real clicks and distinct projected estimates over the tracking."""
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for label, x, y in drawing.projections:
        projected_label = tr("{point} projected").format(point=label.upper())
        centre = QPointF(offset_x + x * scale, offset_y + y * scale)
        points = (
            centre + QPointF(0, -_CLICK_RADIUS),
            centre + QPointF(_CLICK_RADIUS, 0),
            centre + QPointF(0, _CLICK_RADIUS),
            centre + QPointF(-_CLICK_RADIUS, 0),
        )
        painter.setPen(_pen(_UNDERLAY, 3.0, True))
        for start, end in zip(points, (*points[1:], points[0]), strict=True):
            painter.drawLine(start, end)
        painter.setPen(_pen(_BAR, 1.5, True))
        for start, end in zip(points, (*points[1:], points[0]), strict=True):
            painter.drawLine(start, end)
        label_pos = centre + QPointF(_CLICK_RADIUS + 2, -_CLICK_RADIUS)
        painter.setPen(_pen(_UNDERLAY, 1.5, False))
        painter.drawText(label_pos + QPointF(1, 1), projected_label)
        painter.setPen(_pen(_BAR, 1.5, False))
        painter.drawText(label_pos, projected_label)
    for label, x, y in drawing.clicks:
        centre = QPointF(offset_x + x * scale, offset_y + y * scale)
        painter.setPen(_pen(_UNDERLAY, 3.0, False))
        painter.drawEllipse(centre, _CLICK_RADIUS, _CLICK_RADIUS)
        painter.setPen(_pen(_BAR, 1.5, False))
        painter.drawEllipse(centre, _CLICK_RADIUS, _CLICK_RADIUS)
        label_pos = centre + QPointF(_CLICK_RADIUS + 2, -_CLICK_RADIUS)
        painter.setPen(_pen(_UNDERLAY, 1.5, False))
        painter.drawText(label_pos + QPointF(1, 1), label)
        painter.setPen(_pen(_BAR, 1.5, False))
        painter.drawText(label_pos, label)
    if drawing.prompt:
        metrics = painter.fontMetrics()
        available = max(0, painter.viewport().width() - 30)
        if available:
            cue = metrics.elidedText(drawing.prompt, Qt.TextElideMode.ElideRight, available)
            box = QRectF(8, 8, metrics.horizontalAdvance(cue) + 14, metrics.height() + 8)
            painter.setBrush(_UNDERLAY)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(box, 4, 4)
            painter.setPen(_pen(_BAR, 1.0, False))
            painter.drawText(QPointF(15, 12 + metrics.ascent()), cue)
    painter.restore()
