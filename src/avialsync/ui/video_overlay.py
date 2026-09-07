"""Transparent tracking overlay used by :mod:`avialsync.ui.video_pane`.

Two jobs: draw the current tracking points over the frame, and — while "Fix
Tracker" is on — let them be dragged to where they belong.  The drag never
writes to the pose file or its cache; it emits a :class:`PointMove` that the
window turns into a reversible command against
:class:`~avialsync.core.point_edits.PointEditStore` (D-099).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from avialsync.core.point_edits import PointKey
from avialsync.ui.point_edit_tool import PointEditMixin
from avialsync.ui.tracking_colors import color_for_point

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
#: How far outside a pose source's coverage a time may fall and still show its
#: last sample.  Mirrors the tolerance in ``PyramidReader.value_at`` so the
#: overlay does not start pinning a stale coordinate at the ends of a recording.
_COVERAGE_SLACK_S = 0.1


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


def track_color(index: int, *, is_ensemble: bool) -> tuple[int, int, int]:
    """Return a stable colour for an overlaid prediction source."""
    if is_ensemble:
        return _ENSEMBLE_COLOR
    return _MODEL_COLORS[index % len(_MODEL_COLORS)]


class PaintCanvas(PointEditMixin):
    """Paint the current tracking points without obscuring video.

    The "Fix Tracker" gesture lives in :class:`PointEditMixin`; this class owns
    what is drawn and where each point resolves to, which is what the mixin
    hit-tests against.
    """

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
        #: The points themselves. Previously unconditional: there was no way to
        #: see the raw footage under a prediction, which is exactly what someone
        #: checking a track needs to do (D-090).
        self._points_visible = True
        self._corrections_visible = True
        self._init_point_editing()

    def set_readers(self, readers: list[Any]) -> None:
        """Draw a single unnamed track from loose ``*_x``/``*_y`` readers.

        Retained for sources that are not routed through the 2D pose pipeline.
        """
        self.readers = readers
        self.update()

    def set_tracks(self, tracks: list[OverlayTrack]) -> None:
        """Draw one or more named prediction sources over this camera."""
        self.tracks = list(tracks)
        self.update()

    def set_points_visible(self, visible: bool) -> None:
        """Show or hide every tracked point drawn over this camera."""
        self._points_visible = bool(visible)
        self.update()

    def set_point_labels_visible(self, visible: bool) -> None:
        """Show or hide the per-body-part name drawn beside each marker."""
        self._point_labels_visible = bool(visible)
        self.update()

    def set_corrections_visible(self, visible: bool) -> None:
        """Show or hide the ring marking hand-corrected coordinates."""
        self._corrections_visible = bool(visible)
        self.update()

    def set_legend_visible(self, visible: bool) -> None:
        """Show or hide the per-track legend."""
        self._show_legend = visible
        self.update()

    def _video_scale(self) -> tuple[float, float, float] | None:
        """Return ``(scale, offset_x, offset_y)`` mapping video pixels to widget.

        The transform comes from the video surface, which also draws the frame;
        it is never derived from a decoder during paint.
        """
        parent = self.parent()
        surface = getattr(parent, "surface", None)
        if surface is not None:
            geometry = cast(
                tuple[float, float, float] | None,
                surface.frame_geometry(self.width(), self.height()),
            )
            if geometry is not None:
                return geometry

        size = getattr(parent, "video_size", None)
        if size is None:
            return None
        video_width, video_height = size
        if not video_width or not video_height:
            return None
        scale = min(self.width() / video_width, self.height() / video_height)
        offset_x = (self.width() - video_width * scale) / 2.0
        offset_y = (self.height() - video_height * scale) / 2.0
        return scale, offset_x, offset_y

    # ── where the points are ─────────────────────────────────────────

    def _sample(self, reader: Any) -> tuple[int, float] | None:
        """Return the ``(index, value)`` shown at the current time, or None.

        ``sample_at`` is the authority, not ``value_at``: it answers with the
        last sample at or before *t*, which is the same rule the pane uses to
        pick the frame it is showing (architecture rule 6).  ``value_at``
        rounds to the nearest sample, so between two frames it can name the
        coordinate belonging to a frame that is not on screen — harmless while
        the overlay only drew, wrong once a drag has to say which frame it
        corrected.  ``sample_at`` clamps into range and does not consult the gap
        mask, so both are checked here: without that, a pose source with a
        genuinely missing stretch would show its last known coordinate pinned
        in place rather than nothing, which ``value_at`` never did.
        """
        sample_at = getattr(reader, "sample_at", None)
        if sample_at is None:
            value = float(reader.value_at(self.t))
            return (0, value)
        sample = sample_at(self.t)
        if sample is None:
            return None
        coverage = getattr(reader, "coverage", None)
        bounds = coverage() if coverage is not None else None
        if bounds is not None:
            start, end = bounds
            if not (start - _COVERAGE_SLACK_S <= self.t <= end + _COVERAGE_SLACK_S):
                return None
        index, value = sample
        columns = getattr(reader, "mapped_columns", None)
        if columns is not None:
            # An mmap view indexed once -- the access this method is documented
            # for -- never a reduction over the recording on the UI thread.
            _, _, gap = columns()
            if 0 <= index < len(gap) and bool(gap[index]):
                return None
        return int(index), float(value)

    def _resolve(self, track: OverlayTrack) -> list[ResolvedPoint]:
        """Return every body part of *track* that has a position right now.

        Sorted by name for deterministic paint order only; colour is name-keyed
        and does not depend on this ordering.
        """
        resolved: list[ResolvedPoint] = []
        for name, (reader_x, reader_y) in sorted(track.points.items()):
            sample_x = self._sample(reader_x)
            sample_y = self._sample(reader_y)
            if sample_x is None or sample_y is None:
                continue
            index, x_value = sample_x
            _, y_value = sample_y

            source_id = str(getattr(reader_x, "source_id", "") or "")
            key = PointKey(source_id, name, index) if source_id else None
            corrected = False
            if key is not None:
                if self._drag is not None and self._drag.key == key:
                    x_value, y_value = self._drag.position
                    corrected = True
                elif self._edits is not None:
                    override = self._edits.get(key)
                    if override is not None:
                        x_value, y_value = override
                        corrected = True

            if np.isnan(x_value) or np.isnan(y_value):
                continue
            resolved.append(
                ResolvedPoint(
                    name=name,
                    x=float(x_value),
                    y=float(y_value),
                    color=color_for_point(name),
                    key=key,
                    corrected=corrected,
                )
            )
        return resolved

    # ── painting ─────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw every complete XY point of every track at the current source time."""
        del event
        # Edit mode overrides a hidden points layer: a mode whose whole purpose
        # is grabbing markers must not start with nothing on screen to grab.
        if not self._points_visible and not self._edit_mode:
            return
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
        for point in self._resolve(track):
            x = offset_x + point.x * scale
            y = offset_y + point.y * scale

            color = QColor(*point.color)
            pen = QPen(color, 2 if track.is_ensemble else 1)
            painter.setPen(pen)
            painter.setBrush(color)

            painter.drawEllipse(int(x) - radius, int(y) - radius, radius * 2, radius * 2)
            if point.key is not None and point.key == self._highlight:
                self.draw_revisit_ring(painter, x, y)
            if point.corrected and self._corrections_visible:
                self.draw_correction_ring(painter, color, x, y)
            if self._edit_mode and point.key is not None:
                self.draw_handle(painter, color, x, y, held=point.key == self._hover)
            if self._point_labels_visible and point.name:
                self._draw_point_label(painter, label_font, color, point.name, x, y)
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
