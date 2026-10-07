"""Painting a wheel's bars as solid cylinders in the 3D view (D-128).

The 3D view is orthographic, which makes a cylinder simple to draw honestly:
its outline is a band exactly one diameter wide whatever way it points, closed
at each end by the end circle seen edge-on or face-on -- an ellipse whose long
axis is the diameter and whose short axis shrinks with how far the bar points
across the screen rather than at the viewer.

So each bar is: the far end's ellipse, the band, then the near end's face,
shaded dark at the edges and light down the middle so it reads as round rather
than as a flat strip. Bars are painted back to front, so a nearer bar covers a
farther one.

Painting only: screen positions, depths and widths arrive already projected.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen, QPolygonF

__all__ = ["draw_cylinders"]

#: Shading across a bar, as lightness factors of the wheel colour (100 = as is).
_EDGE_DARKER = 185
_MIDDLE_LIGHTER = 135
_FACE_LIGHTER = 115
_FILL_ALPHA = 215


def draw_cylinders(
    painter: QPainter,
    starts: np.ndarray,
    ends: np.ndarray,
    start_depth: np.ndarray,
    end_depth: np.ndarray,
    lengths: np.ndarray,
    width: float,
    color: QColor,
) -> None:
    """Paint ``N`` cylinders of screen *width* between *starts* and *ends* ``(N, 2)``.

    *start_depth* and *end_depth* are each end's depth toward the viewer
    (larger is nearer), and *lengths* each bar's length in the same world
    units, so the end faces can be foreshortened.
    """
    base = QColor(color)
    base.setAlpha(_FILL_ALPHA)
    edge, middle = base.darker(_EDGE_DARKER), base.lighter(_MIDDLE_LIGHTER)
    face = base.lighter(_FACE_LIGHTER)
    outline = QPen(base.darker(_EDGE_DARKER), 1.0)
    order = np.argsort((start_depth + end_depth) / 2.0)
    painter.save()
    for index in order:
        _draw_one(
            painter,
            starts[index],
            ends[index],
            float(end_depth[index] - start_depth[index]),
            float(lengths[index]),
            width,
            (edge, middle, face, outline),
        )
    painter.restore()


def _draw_one(
    painter: QPainter,
    start: np.ndarray,
    end: np.ndarray,
    rise: float,
    length: float,
    width: float,
    colours: tuple[QColor, QColor, QColor, QPen],
) -> None:
    edge, middle, face, outline = colours
    span = end - start
    projected = float(np.hypot(span[0], span[1]))
    # How face-on the end circles are: 1 pointing at the viewer, 0 across.
    facing = min(1.0, abs(rise) / length) if length > 0 else 0.0
    near, far = (end, start) if rise > 0 else (start, end)
    if projected < 1e-6:
        _ellipse(painter, near, (1.0, 0.0), width, width, QBrush(face), outline)
        return
    along = span / projected
    across = np.array([-along[1], along[0]])
    half = across * (width / 2.0)
    middle_point = (start + end) / 2.0
    gradient = QLinearGradient(_point(middle_point - half), _point(middle_point + half))
    gradient.setColorAt(0.0, edge)
    gradient.setColorAt(0.5, middle)
    gradient.setColorAt(1.0, edge)
    cap = width * facing
    # Far face first: only its outer half shows past the band, rounding it off.
    # Solid, not the band's gradient, which would not follow _ellipse's rotation.
    _ellipse(painter, far, along, cap, width, QBrush(middle), QPen(edge, 1.0))
    painter.setPen(QPen(edge, 0.0))
    painter.setBrush(QBrush(gradient))
    painter.drawPolygon(
        QPolygonF([_point(p) for p in (start + half, end + half, end - half, start - half)])
    )
    painter.setPen(outline)
    painter.drawLine(_point(start + half), _point(end + half))
    painter.drawLine(_point(start - half), _point(end - half))
    _ellipse(painter, near, along, cap, width, QBrush(face), outline)


def _ellipse(
    painter: QPainter,
    centre: np.ndarray,
    along: tuple[float, float] | np.ndarray,
    minor: float,
    major: float,
    brush: QBrush,
    pen: QPen,
) -> None:
    """An end face: *major* across the bar, *minor* along it, centred on *centre*."""
    painter.save()
    painter.translate(_point(centre))
    painter.rotate(math.degrees(math.atan2(float(along[1]), float(along[0]))))
    painter.setBrush(brush)
    painter.setPen(pen)
    painter.drawEllipse(QPointF(0.0, 0.0), max(minor, 0.5) / 2.0, major / 2.0)
    painter.restore()


def _point(xy: np.ndarray) -> QPointF:
    return QPointF(float(xy[0]), float(xy[1]))
