"""The "Fix Tracker" gesture: grabbing a predicted point and putting it right.

Split out of :mod:`avialsync.ui.video_overlay` because painting a marker and
dragging one are separate concerns and the combined module ran past the
500-line rule.  The mixin is applied to ``PaintCanvas``, which supplies the
three things it needs from the overlay side -- the tracks, where they resolve
to right now, and the video-to-widget transform.

It never writes to the correction store.  A finished drag becomes a
:class:`~avialsync.core.point_edits.PointMove` on ``point_moved``; the window
puts it through the command bus so the edit is undoable and marks the document
dirty (architecture rule 14, D-099).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QContextMenuEvent, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget

from avialsync.core.point_edits import PointEditStore, PointKey, PointMove

if TYPE_CHECKING:
    from avialsync.ui.video_overlay import OverlayTrack, ResolvedPoint

__all__ = ["PointEditMixin", "CORRECTION_RADIUS", "HANDLE_RADIUS", "HIT_RADIUS"]

#: Ring drawn around a coordinate the user has corrected by hand. Sized outside
#: the ensemble marker so both remain readable at once.
CORRECTION_RADIUS = 8
#: Grab handle drawn in edit mode, and how near the pointer has to be to take
#: hold of one.  The hit radius is the more generous of the two: a 4 px marker
#: is not a mouse target, and a pose point often sits on a dark, textured area
#: where the handle itself is hard to see.
HANDLE_RADIUS = 9
HIT_RADIUS = 14


@dataclass
class _Drag:
    """A grab in progress: what is held, and where it has been moved to."""

    key: PointKey
    name: str
    before: tuple[float, float] | None
    position: tuple[float, float]


class PointEditMixin(QWidget):
    """Mouse handling for correcting a tracked point.

    A ``QWidget`` base rather than a bare mixin so that the Qt calls it makes
    -- cursor, mouse tracking, repaint -- are declared where they are used
    instead of being asserted about a host it cannot see. ``PaintCanvas``
    derives from this and supplies the three overlay-side members below.
    """

    #: Emitted with a :class:`PointMove` when a drag finishes somewhere new.
    #: The canvas does not apply it: the window routes it through the command
    #: bus so the correction is undoable and marks the document dirty (rule 14).
    point_moved = Signal(object)

    # ── supplied by the host canvas ──────────────────────────────────
    tracks: list[OverlayTrack]

    def _resolve(self, track: OverlayTrack) -> list[ResolvedPoint]:  # pragma: no cover - host
        raise NotImplementedError

    def _video_scale(self) -> tuple[float, float, float] | None:  # pragma: no cover - host
        raise NotImplementedError

    # ── state ────────────────────────────────────────────────────────

    def _init_point_editing(self) -> None:
        """Set up correction state.  Called from the canvas's ``__init__``."""
        #: Hand corrections, owned by the window and shared by every pane.
        self._edits: PointEditStore | None = None
        self._edit_mode = False
        self._drag: _Drag | None = None
        self._hover: PointKey | None = None

    def set_point_edits(self, edits: PointEditStore | None) -> None:
        """Adopt the session's correction store, or drop it."""
        self._edits = edits
        self.update()

    def set_edit_mode(self, enabled: bool) -> None:
        """Turn "Fix Tracker" on or off for this pane.

        Off, the canvas is transparent to the mouse exactly as before, so
        double-click, context menu, wheel zoom and middle-drag pan reach the
        video surface untouched.  On, it takes the pointer and hands back
        anything that is not a left-button gesture on a point.
        """
        enabled = bool(enabled)
        if enabled == self._edit_mode:
            return
        self._edit_mode = enabled
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not enabled)
        self.setMouseTracking(enabled)
        self._drag = None
        self._hover = None
        if enabled:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.unsetCursor()
        self.update()

    @property
    def edit_mode(self) -> bool:
        """Whether this pane is currently accepting point corrections."""
        return self._edit_mode

    # ── what the drag draws ──────────────────────────────────────────

    @staticmethod
    def draw_correction_ring(painter: QPainter, color: QColor, x: float, y: float) -> None:
        """Ring a coordinate a person moved, so it never reads as model output."""
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 220), 2, Qt.PenStyle.DotLine))
        painter.drawEllipse(
            int(x) - CORRECTION_RADIUS,
            int(y) - CORRECTION_RADIUS,
            CORRECTION_RADIUS * 2,
            CORRECTION_RADIUS * 2,
        )
        painter.setPen(QPen(color, 1))
        painter.setBrush(color)

    @staticmethod
    def draw_handle(painter: QPainter, color: QColor, x: float, y: float, *, held: bool) -> None:
        """Draw the grab target shown in edit mode."""
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Dark under-stroke: a thin coloured ring disappears over pale fur, and
        # a handle you cannot see is a handle you cannot aim at.
        painter.setPen(QPen(QColor(0, 0, 0, 170), 4 if held else 3))
        painter.drawEllipse(
            int(x) - HANDLE_RADIUS, int(y) - HANDLE_RADIUS, HANDLE_RADIUS * 2, HANDLE_RADIUS * 2
        )
        painter.setPen(QPen(QColor(255, 255, 255) if held else color, 2 if held else 1))
        painter.drawEllipse(
            int(x) - HANDLE_RADIUS, int(y) - HANDLE_RADIUS, HANDLE_RADIUS * 2, HANDLE_RADIUS * 2
        )
        painter.setBrush(color)

    # ── hit testing ──────────────────────────────────────────────────

    def point_at(self, widget_x: float, widget_y: float) -> ResolvedPoint | None:
        """Return the correctable point nearest *(widget_x, widget_y)*, if near.

        Resolution goes through the same method the painter uses, so the handle
        the user grabs is by construction the marker they can see.  The
        ensemble wins where markers overlap, matching what is drawn on top.
        """
        geometry = self._video_scale()
        if geometry is None:
            return None
        scale, offset_x, offset_y = geometry
        if scale <= 0.0:
            return None

        best: ResolvedPoint | None = None
        best_distance = float(HIT_RADIUS)
        best_is_ensemble = False
        for track in self.tracks:
            for point in self._resolve(track):
                if point.key is None:
                    continue
                dx = offset_x + point.x * scale - widget_x
                dy = offset_y + point.y * scale - widget_y
                distance = float(np.hypot(dx, dy))
                if distance > HIT_RADIUS:
                    continue
                better = distance < best_distance or (
                    track.is_ensemble and not best_is_ensemble and distance <= best_distance
                )
                if better:
                    best = point
                    best_distance = distance
                    best_is_ensemble = track.is_ensemble
        return best

    def _to_video(self, widget_x: float, widget_y: float) -> tuple[float, float] | None:
        """Convert widget coordinates to video pixels, clamped to the frame."""
        geometry = self._video_scale()
        if geometry is None:
            return None
        scale, offset_x, offset_y = geometry
        if scale <= 0.0:
            return None
        x = (widget_x - offset_x) / scale
        y = (widget_y - offset_y) / scale
        size = getattr(self.parent(), "video_size", None)
        if size:
            width, height = size
            if width and height:
                x = min(max(x, 0.0), float(width))
                y = min(max(y, 0.0), float(height))
        return x, y

    # ── the gesture ──────────────────────────────────────────────────

    def _forward(self, event: QEvent) -> None:
        """Hand an event we do not own back to the video surface.

        In edit mode this widget is opaque to the mouse, so wheel zoom, the
        middle-button pan, double-click fullscreen and the pane context menu
        would all stop working.  The surface shares this widget's geometry --
        both occupy the same grid cell -- so its local coordinates are ours.
        """
        surface = getattr(self.parent(), "surface", None)
        if surface is None:
            event.ignore()
            return
        QApplication.sendEvent(surface, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self._edit_mode or event.button() != Qt.MouseButton.LeftButton:
            self._forward(event)
            return
        position = event.position()
        point = self.point_at(position.x(), position.y())
        if point is None or point.key is None:
            # Not a grab: let the surface have it, so a stray click in edit
            # mode behaves as it does everywhere else.
            self._forward(event)
            return
        before = self._edits.get(point.key) if self._edits is not None else None
        self._drag = _Drag(
            key=point.key, name=point.name, before=before, position=(point.x, point.y)
        )
        self._hover = point.key
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._edit_mode:
            self._forward(event)
            return
        position = event.position()
        if self._drag is None:
            hovered = self.point_at(position.x(), position.y())
            key = hovered.key if hovered is not None else None
            if key != self._hover:
                self._hover = key
                self.setCursor(Qt.CursorShape.OpenHandCursor if key else Qt.CursorShape.CrossCursor)
                self.update()
            event.accept()
            return
        moved = self._to_video(position.x(), position.y())
        if moved is not None:
            self._drag.position = moved
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self._edit_mode or self._drag is None:
            self._forward(event)
            return
        drag = self._drag
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        event.accept()
        self.update()
        after = (float(drag.position[0]), float(drag.position[1]))
        if drag.before is not None and drag.before == after:
            # A click that put the point back exactly where it already was is
            # not an edit; pushing it would add an undo step that does nothing.
            return
        self.point_moved.emit(PointMove(key=drag.key, before=drag.before, after=after))

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self._forward(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self._forward(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self._forward(event)

    def leaveEvent(self, event: QEvent) -> None:
        """Drop the hover highlight when the pointer leaves the pane."""
        if self._hover is not None and self._drag is None:
            self._hover = None
            self.update()
        super().leaveEvent(event)
