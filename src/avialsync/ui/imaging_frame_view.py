"""The two-photon picture: fitted, zoomable and pannable, or a message in its place.

It behaves like the video surface (``ui/video_pane.py``): the wheel zooms around
the cursor, the middle button pans a magnified picture, and the zoom strip in
the corner zooms about the centre or resets. The zoom belongs to this view
alone; the video and 3D panes keep their own.

Enlarged, every imaging pixel stays a sharp square, the field's convention for
reading single-cell detail. Shrunk, the reduction filters, because dropping
whole rows and columns would alias the picture.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPaintEvent, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import QGridLayout, QSizePolicy, QWidget

from avialsync.ui.zoom_controls import ZOOM_STEP, ZoomControls

__all__ = ["ImagingFrameView"]

#: Largest magnification over the fitted picture.
MAX_ZOOM = 40.0


class ImagingFrameView(QWidget):
    """Paint one composed imaging frame with its own zoom and pan."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Ignored: the picture fills whatever room the pane gives it and never
        # holds the pane at the size of the last frame shown.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(80, 80)
        self._image: QImage | None = None
        self._message = ""
        self._zoom = 1.0
        self._pan = QPointF()
        self._pan_origin: QPointF | None = None

        self.zoom_controls = ZoomControls(self)
        self.zoom_controls.zoom_in_requested.connect(lambda: self.zoom_by(ZOOM_STEP))
        self.zoom_controls.zoom_out_requested.connect(lambda: self.zoom_by(1.0 / ZOOM_STEP))
        self.zoom_controls.reset_requested.connect(self.reset_view)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(
            self.zoom_controls, 0, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft
        )

    # ── content ──────────────────────────────────────────────────────

    def text(self) -> str:
        """The message shown instead of a picture, or ``""`` while one is shown."""
        return self._message

    def setText(self, text: str) -> None:  # noqa: N802 - mirrors QLabel, which this replaced
        """Show *text* in place of the picture."""
        self._image = None
        self._message = text
        self.zoom_controls.setVisible(False)
        self.update()

    def set_image(self, image: QImage) -> None:
        """Show *image*, keeping the zoom and pan the user chose."""
        resized = self._image is None or self._image.size() != image.size()
        self._image = image
        self._message = ""
        self.zoom_controls.setVisible(True)
        if resized:
            self._clamp_pan()
        self.update()

    def zoom(self) -> float:
        """Magnification over the fitted picture; 1.0 is fitted."""
        return self._zoom

    def visible_fraction(self) -> tuple[float, float, float, float] | None:
        """The part of the picture on screen as ``(x, y, width, height)`` fractions.

        ``None`` while the whole picture is shown, so an export of it takes all
        of it; zoomed in, an export takes exactly this part (D-210).
        """
        geometry = self._geometry()
        if geometry is None or self._image is None or self._zoom == 1.0:
            return None
        scale, left, top = geometry
        width, height = self._image.width(), self._image.height()
        x0 = min(max(-left / scale, 0.0), width)
        y0 = min(max(-top / scale, 0.0), height)
        x1 = min(max((self.width() - left) / scale, 0.0), width)
        y1 = min(max((self.height() - top) / scale, 0.0), height)
        if x1 <= x0 or y1 <= y0:
            return None
        return x0 / width, y0 / height, (x1 - x0) / width, (y1 - y0) / height

    # ── zoom and pan ─────────────────────────────────────────────────

    def zoom_by(self, factor: float, anchor: QPointF | None = None) -> None:
        """Scale around *anchor* (the centre by default), keeping that pixel under it."""
        if factor <= 0.0:
            return
        next_zoom = min(max(self._zoom * factor, 1.0), MAX_ZOOM)
        if next_zoom == self._zoom:
            return
        before = self._geometry()
        if anchor is None:
            anchor = QPointF(self.width() / 2.0, self.height() / 2.0)
        self._zoom = next_zoom
        after = self._geometry()
        if before is not None and after is not None:
            scale, left, top = before
            source_x = (anchor.x() - left) / scale
            source_y = (anchor.y() - top) / scale
            new_scale, new_left, new_top = after
            self._pan += QPointF(
                anchor.x() - new_left - source_x * new_scale,
                anchor.y() - new_top - source_y * new_scale,
            )
        self._clamp_pan()
        self.update()

    def pan_by(self, delta: QPointF) -> None:
        """Shift a magnified picture by *delta* widget pixels, clamped to its edges."""
        self._pan += delta
        self._clamp_pan()
        self.update()

    def reset_view(self) -> None:
        """Back to the fitted, centred picture."""
        self._zoom = 1.0
        self._pan = QPointF()
        self.update()

    def _geometry(self) -> tuple[float, float, float] | None:
        """``(scale, left, top)`` of the picture in widget pixels, pan included."""
        if self._image is None or self.width() <= 0 or self.height() <= 0:
            return None
        image_width, image_height = self._image.width(), self._image.height()
        if image_width <= 0 or image_height <= 0:
            return None
        scale = min(self.width() / image_width, self.height() / image_height) * self._zoom
        left = (self.width() - image_width * scale) / 2.0 + self._pan.x()
        top = (self.height() - image_height * scale) / 2.0 + self._pan.y()
        return scale, left, top

    def _clamp_pan(self) -> None:
        """Keep a panned picture from uncovering empty space past its edges."""
        if self._image is None or self._image.isNull():
            self._pan = QPointF()
            return
        fitted = min(self.width() / self._image.width(), self.height() / self._image.height())
        scale = fitted * self._zoom
        max_x = max(0.0, (self._image.width() * scale - self.width()) / 2.0)
        max_y = max(0.0, (self._image.height() * scale - self.height()) / 2.0)
        self._pan = QPointF(
            min(max(self._pan.x(), -max_x), max_x), min(max(self._pan.y(), -max_y), max_y)
        )

    # ── Qt events ────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the picture at its zoom, or the message centred."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        geometry = self._geometry()
        if self._image is not None and geometry is not None:
            scale, left, top = geometry
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, scale < 1.0)
            target = QRectF(left, top, self._image.width() * scale, self._image.height() * scale)
            painter.drawImage(target, self._image)
        elif self._message:
            painter.setPen(self.palette().windowText().color())
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._message
            )
        painter.end()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep the retained pan inside the picture at the new size."""
        super().resizeEvent(event)
        self._clamp_pan()

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Zoom around the cursor with the scroll wheel."""
        steps = event.angleDelta().y() / 120.0
        if steps and self._image is not None:
            self.zoom_by(1.15**steps, event.position())
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start a middle-button pan when the picture is magnified."""
        if event.button() == Qt.MouseButton.MiddleButton and self._zoom > 1.0:
            self._pan_origin = event.position()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Pan with the held middle button."""
        if self._pan_origin is None or not event.buttons() & Qt.MouseButton.MiddleButton:
            super().mouseMoveEvent(event)
            return
        position = event.position()
        self.pan_by(position - self._pan_origin)
        self._pan_origin = position
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish a middle-button pan."""
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_origin is not None:
            self._pan_origin = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Fit the picture again on double click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
