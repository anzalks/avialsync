"""Cached master-timeline evidence under the transport slider."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider, QWidget

from avialsync.ui.theme import coverage_color, loop_pin_color, separator_color, system_accent

_TRACK_HEIGHT = 4
_TRACK_RADIUS = 2.0


def _merge_spans(spans: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    """Union overlapping or touching intervals so multi-source alpha never stacks."""
    finite = sorted(
        (float(start), float(end))
        for start, end in spans
        if math.isfinite(start) and math.isfinite(end) and end > start
    )
    merged: list[tuple[float, float]] = []
    for start, end in finite:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


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

    def track_rect(self) -> QRect:
        """Single authoritative 4 px groove aligned vertically to the slider thumb."""
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self
        )
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
        )
        middle = handle.center().y() if handle.height() > 0 else self.height() // 2
        left = groove.left() if groove.width() > 0 else 0
        width = groove.width() if groove.width() > 0 else max(0, self.width())
        return QRect(left, middle - (_TRACK_HEIGHT // 2), width, _TRACK_HEIGHT)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the cached evidence track, played progress on the same band, and one handle."""
        del event
        if self._track_cache is None:
            self._build_track()
        if self._track_cache is None:
            return
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._track_cache)
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        track = self.track_rect()
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
        )
        played_w = min(track.width(), max(0, handle.center().x() - track.left()))
        if played_w > 0 and track.width() > 0:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(track), _TRACK_RADIUS, _TRACK_RADIUS)
            painter.setClipPath(clip)
            painter.fillRect(
                QRect(track.left(), track.top(), played_w, track.height()),
                system_accent(self.palette()),
            )
            painter.restore()
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
        """Rasterize base groove, merged coverage, loop, and markers once per input change."""
        ratio = max(1.0, self.devicePixelRatioF())
        pixmap = QPixmap(max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio)))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        track = self.track_rect()
        painter = QPainter(pixmap)
        if track.width() > 0:
            self._paint_base_groove(painter, track)
            if self._bounds[1] > self._bounds[0]:
                self._paint_evidence(painter, track)
        painter.end()
        self._track_cache = pixmap
        self._track_build_count += 1

    def _paint_base_groove(self, painter: QPainter, track: QRect) -> None:
        bed = QColor(separator_color(self.palette()))
        bed.setAlpha(150)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bed)
        painter.drawRoundedRect(QRectF(track), _TRACK_RADIUS, _TRACK_RADIUS)
        painter.restore()

    def _paint_evidence(self, painter: QPainter, track: QRect) -> None:
        """Draw unioned coverage strips inside the rounded track plus loop and markers."""
        middle = track.center().y()
        tint = coverage_color(self.palette())
        tint.setAlpha(185)
        merged = _merge_spans(self._coverage)
        if merged:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(track), _TRACK_RADIUS, _TRACK_RADIUS)
            painter.setClipPath(clip)
            for start, end in merged:
                left, right = self._x(start, track), self._x(end, track)
                if right > left:
                    painter.fillRect(QRect(left, track.top(), right - left, track.height()), tint)
            painter.restore()

        loop_start, loop_end = self._loop
        if loop_start is not None and loop_end is not None and loop_end > loop_start:
            left, right = self._x(loop_start, track), self._x(loop_end, track)
            ink = loop_pin_color(self.palette(), "in")
            ink.setAlpha(190)
            painter.fillRect(QRect(left, track.top() - 3, max(1, right - left), 2), ink)

        seen: set[int] = set()
        for time, marker_end, color in self._markers:
            x = self._x(time, track)
            if x not in seen:
                ink = QColor(color)
                fallback = self.palette().color(self.foregroundRole())
                painter.setPen(ink if ink.isValid() else fallback)
                painter.drawLine(x, middle - 6, x, middle + 6)
                seen.add(x)
            if marker_end is not None and marker_end > time:
                right = self._x(marker_end, track)
                painter.drawLine(x, middle - 5, right, middle - 5)
