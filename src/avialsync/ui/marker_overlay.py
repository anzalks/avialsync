"""What a camera's overlay draws besides the tracking (D-112, D-113).

Hand-placed 3D markers (rings), 3D points projected back into the camera
(crosses), and the wheel model (lines, :mod:`avialsync.ui.wheel_overlay`) --
three glyphs beside the tracked dot, told apart by shape rather than colour
(AGENTS rule 17). Split from :mod:`avialsync.ui.video_overlay` so that module
stays about the tracking itself; :class:`PaintCanvas` is the only host.

Hand-placed markers are also grabbable in Fix Tracker, so :meth:`_resolve_custom`
is the one place a marker's on-screen position is decided, for painting and
hit-testing alike -- the rule :class:`ResolvedPoint` exists for.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

from avialsync.core.point_edits import PointKey
from avialsync.ui.point_edit_tool import CUSTOM_MARKER_SOURCE, PointEditMixin
from avialsync.ui.tracking_colors import color_for_point
from avialsync.ui.wheel_overlay import WheelDrawing

__all__ = ["ResolvedPoint", "MarkerOverlayMixin"]

#: A hand-placed 3D marker is a hollow ring, wider than a prediction, so it is
#: never read as the model's own output (the 3D view draws it the same way).
_CUSTOM_RADIUS = 6
#: Half-length of a reprojected 3D point's cross: a third glyph, beside the
#: tracked dot and the hand-placed ring, so the three are told apart by shape
#: rather than by colour alone (AGENTS rule 17).
_REPROJECTION_ARM = 5
#: Marker-label text, as the tracking's own labels are drawn.
_LABEL_POINT_SIZE = 8


@dataclass(frozen=True)
class ResolvedPoint:
    """Where one body part is right now, and what identifies it.

    Painting and hit-testing both go through this, so the handle the user
    grabs is by construction the marker they can see — there is no second
    place that decides where a point is.
    """

    name: str
    x: float
    y: float
    color: tuple[int, int, int]
    #: ``None`` when the reader carries no source identity, which is the loose
    #: ``set_readers`` path.  Such a point is drawn but cannot be corrected,
    #: because there would be nothing stable to key the correction to.
    key: PointKey | None
    corrected: bool
    #: A hand-placed 3D marker rather than a prediction.
    custom: bool = False


class MarkerOverlayMixin(PointEditMixin):
    """Markers, reprojection and the wheel, for :class:`~avialsync.ui.video_overlay.PaintCanvas`."""

    # ── supplied by the host canvas ──────────────────────────────────
    #: Master time the canvas is showing.
    t: float

    @staticmethod
    def _draw_point_label(  # pragma: no cover - host
        painter: QPainter, font: QFont, color: QColor, name: str, x: float, y: float
    ) -> None:
        raise NotImplementedError

    # ── state ────────────────────────────────────────────────────────

    def _init_marker_overlay(self) -> None:
        #: Hand-placed 3D markers seen by this camera: frame -> ``(name, x, y)``.
        self._custom: dict[int, list[tuple[str, float, float]]] = {}
        self._custom_visible = True
        #: ``t_master -> [(name, x, y)]``: 3D points projected into this camera.
        self._reprojection: Callable[[float], list[tuple[str, float, float]]] | None = None
        self._reprojection_visible = False
        #: ``t_master -> WheelDrawing``: the wheel model projected into this
        #: camera (D-113), and its two layers.
        self._wheel: Callable[[float], WheelDrawing | None] | None = None
        self._wheel_visible = True
        self._wheel_hidden_visible = False

    def set_custom_markers(self, markers: dict[int, list[tuple[str, float, float]]]) -> None:
        """Replace this camera's hand-placed 3D markers, keyed by video frame."""
        self._custom = {int(frame): list(points) for frame, points in markers.items()}
        self.update()

    def set_reprojection_source(
        self, source: Callable[[float], list[tuple[str, float, float]]] | None
    ) -> None:
        """Where to ask for 3D points projected into this camera."""
        self._reprojection = source
        self.update()

    def set_wheel_source(self, source: Callable[[float], WheelDrawing | None] | None) -> None:
        """Where to ask for the wheel model, projected into this camera."""
        self._wheel = source
        self.update()

    def set_wheel_visible(self, facing: bool, hidden: bool) -> None:
        """Show or hide the wheel's bars this camera sees, and the ones it does not."""
        self._wheel_visible = bool(facing)
        self._wheel_hidden_visible = bool(hidden)
        self.update()

    def set_reprojection_visible(self, visible: bool) -> None:
        """Show or hide the 3D points projected back into this camera."""
        self._reprojection_visible = bool(visible)
        self.update()

    def _draw_reprojection(
        self, painter: QPainter, scale: float, offset_x: float, offset_y: float
    ) -> None:
        """Draw each reprojected 3D point as a cross in its body part's colour."""
        if self._reprojection is None:
            return
        arm = _REPROJECTION_ARM
        for name, px, py in self._reprojection(self.t):
            x = int(offset_x + px * scale)
            y = int(offset_y + py * scale)
            color = QColor(*color_for_point(name))
            for pen in (QPen(QColor(0, 0, 0, 200), 4), QPen(color, 2)):
                painter.setPen(pen)
                painter.drawLine(x - arm, y, x + arm, y)
                painter.drawLine(x, y - arm, x, y + arm)

    def set_custom_markers_visible(self, visible: bool) -> None:
        """Show or hide the hand-placed 3D markers on this camera."""
        self._custom_visible = bool(visible)
        self.update()

    def _current_frame(self) -> int | None:
        """The frame this pane shows now -- the one a custom marker is keyed by."""
        record = getattr(self.parent(), "frame_record_at", None)
        if record is None:
            return None
        try:
            return int(record(self.t)[0])
        except (TypeError, ValueError):
            return None

    def _resolve_custom(self) -> list[ResolvedPoint]:
        """Every hand-placed marker on the frame on screen, drag applied."""
        resolved: list[ResolvedPoint] = []
        if not self._custom:
            return resolved
        frame = self._current_frame()
        if frame is None:
            return resolved
        for name, x, y in self._custom.get(frame, ()):
            key = PointKey(CUSTOM_MARKER_SOURCE, name, frame)
            if self._drag is not None and self._drag.key == key:
                x, y = self._drag.position
            resolved.append(
                ResolvedPoint(
                    name=name,
                    x=float(x),
                    y=float(y),
                    color=color_for_point(name),
                    key=key,
                    corrected=False,
                    custom=True,
                )
            )
        return resolved

    def _draw_custom(
        self, painter: QPainter, scale: float, offset_x: float, offset_y: float
    ) -> None:
        """Draw hand-placed 3D markers as hollow rings, on top of predictions."""
        label_font = painter.font()
        label_font.setPointSize(_LABEL_POINT_SIZE)
        label_font.setBold(True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for point in self._resolve_custom():
            x = offset_x + point.x * scale
            y = offset_y + point.y * scale
            color = QColor(*point.color)
            # Dark underlay first: a 2 px ring alone vanishes over pale fur.
            painter.setPen(QPen(QColor(0, 0, 0, 200), 4))
            painter.drawEllipse(
                int(x) - _CUSTOM_RADIUS,
                int(y) - _CUSTOM_RADIUS,
                _CUSTOM_RADIUS * 2,
                _CUSTOM_RADIUS * 2,
            )
            painter.setPen(QPen(color, 2))
            painter.drawEllipse(
                int(x) - _CUSTOM_RADIUS,
                int(y) - _CUSTOM_RADIUS,
                _CUSTOM_RADIUS * 2,
                _CUSTOM_RADIUS * 2,
            )
            if self._edit_mode and point.key is not None:
                self.draw_handle(painter, color, x, y, held=point.key == self._hover)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            # Always named: there is no model legend to say what a ring is.
            self._draw_point_label(painter, label_font, color, point.name, x, y)
