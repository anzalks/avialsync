"""Cached master-timeline evidence under the transport slider (D-170)."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider, QWidget

from avialsync.ui.theme import coverage_color, loop_pin_color


class ScrubBar(QSlider):
    """Seek slider whose evidence track is rebuilt only when its inputs change."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._bounds = (0.0, 0.0)
        self._coverage: tuple[tuple[float, float], ...] = ()
        self._markers: tuple[tuple[float, float | None, str], ...] = ()
        self._loop: tuple[float | None, float | None] = (None, None)
        self._track_cache: QPixmap | None = None
        self._track_build_count = 0

    @property
    def track_build_count(self) -> int:
        """Number of cache rebuilds, for performance evidence."""
        return self._track_build_count

    def set_track_data(
        self,
        bounds: tuple[float, float],
        coverage: tuple[tuple[float, float], ...],
        markers: tuple[tuple[float, float | None, str], ...],
        loop: tuple[float | None, float | None],
    ) -> None:
        """Replace evidence, invalidating the track only when it changed."""
        state = (bounds, coverage, markers, loop)
        if state == (self._bounds, self._coverage, self._markers, self._loop):
            return
        self._bounds, self._coverage, self._markers, self._loop = state
        self._invalidate_track()

    def _invalidate_track(self) -> None:
        self._track_cache = None
        self.update()

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._invalidate_track()
        super().resizeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self._invalidate_track()
        super().changeEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Keep the old JumpSlider's immediate click-to-position behavior."""
        if event.button() == Qt.MouseButton.LeftButton and self.width() > 0:
            fraction = max(0.0, min(1.0, event.position().x() / self.width()))
            value = self.minimum() + round((self.maximum() - self.minimum()) * fraction)
            self.setValue(value)
        super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Reuse evidence pixels while Qt draws the current handle as normal."""
        super().paintEvent(event)
        if self._track_cache is None:
            self._build_track()
        if self._track_cache is None:
            return
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._track_cache)
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        option.subControls = QStyle.SubControl.SC_SliderHandle
        self.style().drawComplexControl(QStyle.ComplexControl.CC_Slider, option, painter, self)
        painter.end()

    def _x(self, time: float, groove: QRect) -> int:
        low, high = self._bounds
        if not math.isfinite(time) or high <= low:
            return groove.left()
        fraction = max(0.0, min(1.0, (time - low) / (high - low)))
        return groove.left() + round(fraction * groove.width())

    def _build_track(self) -> None:
        """Rasterize coverage, loop, and annotation marks once per input change."""
        ratio = max(1.0, self.devicePixelRatioF())
        pixmap = QPixmap(max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio)))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self
        )
        painter = QPainter(pixmap)
        if groove.width() > 0 and self._bounds[1] > self._bounds[0]:
            self._paint_evidence(painter, groove)
        painter.end()
        self._track_cache = pixmap
        self._track_build_count += 1

    def _paint_evidence(self, painter: QPainter, groove: QRect) -> None:
        """Draw a few bounded strips and one distinct column per annotation."""
        middle = groove.center().y()
        tint = coverage_color(self.palette())
        tint.setAlpha(170)
        for start, end in self._coverage:
            left, right = self._x(start, groove), self._x(end, groove)
            if right > left:
                painter.fillRect(QRect(left, middle - 2, right - left, 4), tint)

        loop_start, loop_end = self._loop
        if loop_start is not None and loop_end is not None and loop_end > loop_start:
            left, right = self._x(loop_start, groove), self._x(loop_end, groove)
            ink = loop_pin_color(self.palette(), "in")
            ink.setAlpha(180)
            painter.fillRect(QRect(left, middle - 4, max(1, right - left), 2), ink)

        seen: set[int] = set()
        for time, marker_end, color in self._markers:
            x = self._x(time, groove)
            if x not in seen:
                ink = QColor(color)
                fallback = self.palette().color(self.foregroundRole())
                painter.setPen(ink if ink.isValid() else fallback)
                painter.drawLine(x, middle - 6, x, middle + 6)
                seen.add(x)
            if marker_end is not None and marker_end > time:
                right = self._x(marker_end, groove)
                painter.drawLine(x, middle - 5, right, middle - 5)
