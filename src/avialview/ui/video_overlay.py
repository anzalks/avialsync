"""Transparent tracking overlay used by :mod:`avialview.ui.video_pane`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from avialview.ui.tracking_colors import color_for_point

_ENSEMBLE_COLOR = (0, 255, 255)
_MODEL_COLORS = (
    (255, 145, 0),
    (124, 220, 90),
    (235, 100, 190),
    (255, 220, 60),
    (150, 160, 255),
)
_ENSEMBLE_RADIUS = 4
_MODEL_RADIUS = 2
#: Point-label text. Small and offset off the marker so it never hides the very
#: coordinate it is naming.
_LABEL_POINT_SIZE = 8
_LABEL_DX = 6
_LABEL_DY = -6


@dataclass(frozen=True)
class OverlayTrack:
    """One prediction source drawn over a camera's video.

    ``points`` maps a body-part name to its ``(x_reader, y_reader)`` pair. Each
    track owns readers from its own sidecar cache, so two models that both emit
    a channel called ``head_bar_x`` never collide.
    """

    label: str
    points: dict[str, tuple[Any, Any]]
    color: tuple[int, int, int] = _ENSEMBLE_COLOR
    is_ensemble: bool = True
    likelihood: dict[str, Any] = field(default_factory=dict)


def track_color(index: int, *, is_ensemble: bool) -> tuple[int, int, int]:
    """Return a stable colour for an overlaid prediction source."""
    if is_ensemble:
        return _ENSEMBLE_COLOR
    return _MODEL_COLORS[index % len(_MODEL_COLORS)]


class PaintCanvas(QWidget):
    """Paint the current tracking points without obscuring video."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAutoFillBackground(False)
        self.readers: list[Any] = []
        self.tracks: list[OverlayTrack] = []
        self.t = 0.0
        self._show_legend = True
        self._point_labels_visible = True

    def set_readers(self, readers: list[Any]) -> None:
        """Draw a single unnamed track from loose ``*_x``/``*_y`` readers.

        Retained for sources that are not routed through the AOL 2D pipeline.
        """
        self.readers = readers
        self.update()

    def set_tracks(self, tracks: list[OverlayTrack]) -> None:
        """Draw one or more named prediction sources over this camera."""
        self.tracks = list(tracks)
        self.update()

    def set_point_labels_visible(self, visible: bool) -> None:
        """Show or hide the per-body-part name drawn beside each marker."""
        self._point_labels_visible = bool(visible)
        self.update()

    def set_legend_visible(self, visible: bool) -> None:
        """Show or hide the per-track legend."""
        self._show_legend = visible
        self.update()

    def _video_scale(self) -> tuple[float, float, float] | None:
        """Return ``(scale, offset_x, offset_y)`` mapping video pixels to widget.

        The size comes from the pane's mirrored copy of libmpv's
        ``video-out-params``, never from libmpv itself.  Reading ``dwidth``
        here would take libmpv's core lock inside ``paintEvent``, on the UI
        thread, while the decoder threads are contending for it — measured at
        26-34 us typical and 165 us at p99, paid once per pane per frame.
        """
        size = getattr(self.parent(), "video_size", None)
        if size is None:
            return None
        video_width, video_height = size
        if not video_width or not video_height:
            return None
        scale = min(self.width() / video_width, self.height() / video_height)
        offset_x = (self.width() - video_width * scale) / 2.0
        offset_y = (self.height() - video_height * scale) / 2.0
        return scale, offset_x, offset_y

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw every complete XY point of every track at the current source time."""
        del event
        if not self.readers and not self.tracks:
            return
        geometry = self._video_scale()
        if geometry is None:
            return
        scale, offset_x, offset_y = geometry

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.tracks:
            drawn: list[tuple[str, tuple[int, int, int]]] = []
            # Models first, ensemble last, so the fused result stays readable.
            ordered = sorted(self.tracks, key=lambda track: track.is_ensemble)
            for track in ordered:
                if self._draw_track(painter, track, scale, offset_x, offset_y):
                    drawn.append((track.label, track.color))
            if self._show_legend and len(drawn) > 1:
                self._draw_legend(painter, drawn)

        if self.readers:
            self._draw_loose_readers(painter, scale, offset_x, offset_y)

    def _draw_track(
        self,
        painter: QPainter,
        track: OverlayTrack,
        scale: float,
        offset_x: float,
        offset_y: float,
    ) -> bool:
        """Draw one prediction source; returns whether anything was visible.

        Each marker is named in place.  A dot alone tells you a body part was
        tracked but not *which* one, which is the question being asked when
        several parts sit close together.
        """
        radius = _ENSEMBLE_RADIUS if track.is_ensemble else _MODEL_RADIUS

        label_font = painter.font()
        label_font.setPointSize(_LABEL_POINT_SIZE)
        label_font.setBold(track.is_ensemble)

        any_drawn = False
        # Sorted for deterministic paint order only; colour is name-keyed and
        # does not depend on this ordering (see tracking_colors.color_for_point).
        for name, (reader_x, reader_y) in sorted(track.points.items()):
            x_value = reader_x.value_at(self.t)
            y_value = reader_y.value_at(self.t)
            if np.isnan(x_value) or np.isnan(y_value):
                continue
            x = offset_x + x_value * scale
            y = offset_y + y_value * scale

            color = QColor(*color_for_point(name))
            pen = QPen(color, 2 if track.is_ensemble else 1)
            painter.setPen(pen)
            painter.setBrush(color)

            painter.drawEllipse(int(x) - radius, int(y) - radius, radius * 2, radius * 2)
            if self._point_labels_visible and name:
                self._draw_point_label(painter, label_font, color, name, x, y)
            any_drawn = True
        return any_drawn

    @staticmethod
    def _draw_point_label(
        painter: QPainter,
        font: QFont,
        color: QColor,
        name: str,
        x: float,
        y: float,
    ) -> None:
        """Write a body-part name beside its marker, legible over any footage.

        A dark outline is drawn under the text because the overlay sits on top
        of arbitrary video: plain coloured text vanishes over pale fur or a lit
        background.
        """
        painter.setFont(font)
        text_x = int(x) + _LABEL_DX
        text_y = int(y) + _LABEL_DY
        painter.setPen(QPen(QColor(0, 0, 0, 200), 3))
        painter.drawText(text_x, text_y, name)
        painter.setPen(QPen(color, 1))
        painter.drawText(text_x, text_y, name)

    def _draw_loose_readers(
        self, painter: QPainter, scale: float, offset_x: float, offset_y: float
    ) -> None:
        points: dict[str, dict[str, float]] = {}
        for reader in self.readers:
            value = reader.value_at(self.t)
            if np.isnan(value):
                continue
            for suffix in ("_x", "_y"):
                if reader.channel_id.endswith(suffix):
                    points.setdefault(reader.channel_id[:-2], {})[suffix[1:]] = value

        for name, point in sorted(points.items()):
            if "x" not in point or "y" not in point:
                continue
            color = color_for_point(name)
            painter.setPen(QPen(QColor(*color), 3))
            painter.setBrush(QColor(*color))
            x = offset_x + point["x"] * scale
            y = offset_y + point["y"] * scale
            painter.drawEllipse(int(x) - 3, int(y) - 3, 6, 6)

    def _draw_legend(
        self, painter: QPainter, entries: list[tuple[str, tuple[int, int, int]]]
    ) -> None:
        """Name each overlaid source so colour is never the only distinction."""
        font = QFont(painter.font())
        font.setPointSize(max(7, font.pointSize() - 1))
        painter.setFont(font)
        metrics = painter.fontMetrics()

        swatch = 8
        padding = 6
        spacing = 4
        line_height = max(metrics.height(), swatch) + spacing
        width = max(metrics.horizontalAdvance(label) for label, _ in entries) + swatch + padding * 3
        height = line_height * len(entries) + padding
        left = self.width() - width - 8
        top = self.height() - height - 8

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 140))
        painter.drawRoundedRect(left, top, width, height, 4, 4)

        y = top + padding
        for label, color in entries:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*color))
            painter.drawEllipse(left + padding, y + 2, swatch, swatch)
            painter.setPen(QColor(240, 240, 240))
            painter.drawText(
                left + padding * 2 + swatch,
                y + metrics.ascent(),
                label,
            )
            y += line_height

    def update_time(self, t: float) -> None:
        """Move the overlay to *t*, repainting only if it has marks to move.

        A pane with no tracking data still runs this once per presented frame.
        ``paintEvent`` would return immediately, but scheduling the repaint at
        all still costs a composite of a translucent widget stacked over the
        video surface — per pane, per frame, for nothing.  Sources without an
        overlay are the common case.
        """
        self.t = t
        if self.readers or self.tracks:
            self.update()
