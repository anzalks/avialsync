"""Transparent tracking overlay used by :mod:`avialsync.ui.video_pane`.

Two jobs: draw the current tracking points over the frame, and — while "Fix
Tracker" is on — let them be dragged to where they belong.  The drag never
writes to the pose file or its cache; it emits a :class:`PointMove` that the
window turns into a reversible command against
:class:`~avialsync.core.point_edits.PointEditStore`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, cast

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from avialsync.core.point_edits import PointKey
from avialsync.core.pose import split_channel
from avialsync.ui.i18n import tr
from avialsync.ui.marker_overlay import (
    MarkerOverlayMixin,
    ResolvedPoint,
    overlay_label_point_size,
)
from avialsync.ui.overlay_registry import default_visible_for
from avialsync.ui.pose_overlay_extras import (
    SOLO_SKELETON_COLOR,
    confidence_threshold,
    draw_2d_skeleton,
    draw_epipolar_guides,
    draw_magnifier_loupe,
    draw_motion_trails,
    marker_radius,
    skeleton_comparison_colors,
    style_point_by_confidence,
    trail_frame_count,
)
from avialsync.ui.prop_overlay import PropDrawing, draw_props
from avialsync.ui.tracking_colors import color_for_point
from avialsync.ui.wheel_overlay import WheelDrawing, draw_wheel, draw_wheel_clicks

logger = logging.getLogger(__name__)

_ENSEMBLE_COLOR = (0, 255, 255)
_MODEL_COLORS = (
    (255, 145, 0),
    (124, 220, 90),
    (235, 100, 190),
    (255, 220, 60),
    (150, 160, 255),
)
_MODEL_RADIUS = 2
#: Point-label text is sized by `marker_overlay.overlay_label_point_size`: small
#: and offset off the marker so it never hides the very coordinate it is naming.

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
    track owns readers from its own cache entry, so two models that both emit
    a channel called ``head_bar_x`` never collide.
    """

    label: str
    points: dict[str, tuple[Any, Any]]
    color: tuple[int, int, int] = _ENSEMBLE_COLOR
    is_ensemble: bool = True
    likelihood: dict[str, Any] = field(default_factory=dict)
    edges: tuple[tuple[str, str], ...] = ()


def track_color(index: int, *, is_ensemble: bool) -> tuple[int, int, int]:
    """Return a stable colour for an overlaid prediction source."""
    if is_ensemble:
        return _ENSEMBLE_COLOR
    return _MODEL_COLORS[index % len(_MODEL_COLORS)]


class PaintCanvas(MarkerOverlayMixin):
    """Paint the current tracking points without obscuring video.

    The "Fix Tracker" gesture lives in :class:`PointEditMixin`; hand-placed
    markers, reprojection and the wheel in :class:`MarkerOverlayMixin`. This
    class owns the tracking drawn and where each point resolves to, which is
    what the gesture hit-tests against.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAutoFillBackground(False)
        self.readers: list[Any] = []
        self._loose_cache_sig: tuple[int, int] | None = None
        self._loose_xy_readers: list[tuple[Any, str, str]] = []
        self.tracks: list[OverlayTrack] = []
        self._reported_reader_errors: set[int] = set()
        self.t = 0.0
        #: Seeded from the registry, never from literals here: these are the
        #: same defaults View -> Overlays checks its boxes against, and a second
        #: copy of them is what let the canvas draw a layer the menu called off.
        #: Each is replaced by the resolved state in
        #: `VideoPane.apply_overlay_visibility` as soon as one exists.
        self._show_legend = default_visible_for("tracking.legend")
        self._point_labels_visible = default_visible_for("tracking.point_labels")
        #: The points themselves. Previously unconditional: there was no way to
        #: see the raw footage under a prediction, which is exactly what someone
        #: checking a track needs to do.
        self._points_visible = default_visible_for("tracking.points")
        self._corrections_visible = default_visible_for("tracking.corrections")
        self._skeleton_2d_visible = default_visible_for("tracking.skeleton_2d")
        self._trails_visible = default_visible_for("tracking.trails")
        self._confidence_visible = default_visible_for("tracking.confidence")
        self._loupe_visible = default_visible_for("camera.loupe")
        self._init_point_editing()
        self._init_marker_overlay()

    def set_readers(self, readers: list[Any]) -> None:
        """Draw a single track from loose ``*_x``/``*_y`` readers.

        Retained for sources that are not routed through the 2D pose pipeline:
        a pose file imported as plain data channels reaches the overlay this
        way, broadcast to every camera rather than routed to one.
        """
        self.readers = readers
        self._loose_cache_sig = None
        self._reported_reader_errors.clear()
        self.update()

    def _active_loose_xy(self) -> list[tuple[Any, str, str]]:
        """Return only loose readers that form complete ``(x, y)`` pairs."""
        sig = (id(self.readers), len(self.readers))
        if self._loose_cache_sig == sig:
            return self._loose_xy_readers
        axes_by_name: dict[str, set[str]] = {}
        candidates: list[tuple[Any, str, str]] = []
        for reader in self.readers:
            split = split_channel(getattr(reader, "channel_id", ""))
            if split is not None and split[1] in ("x", "y"):
                axes_by_name.setdefault(split[0], set()).add(split[1])
                candidates.append((reader, split[0], split[1]))
        complete = {name for name, axes in axes_by_name.items() if "x" in axes and "y" in axes}
        self._loose_xy_readers = [item for item in candidates if item[1] in complete]
        self._loose_cache_sig = sig
        return self._loose_xy_readers

    def set_tracks(self, tracks: list[OverlayTrack]) -> None:
        """Draw one or more named prediction sources over this camera."""
        self.tracks = list(tracks)
        self._reported_reader_errors.clear()
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

    def set_skeleton_2d_visible(self, visible: bool) -> None:
        """Show or hide 2D limb connections between tracked points."""
        self._skeleton_2d_visible = bool(visible)
        self.update()

    def set_trails_visible(self, visible: bool) -> None:
        """Show or hide fading recent-frame motion trails."""
        self._trails_visible = bool(visible)
        self.update()

    def set_confidence_visible(self, visible: bool) -> None:
        """Show or hide low-confidence point styling."""
        self._confidence_visible = bool(visible)
        self.update()

    def set_loupe_visible(self, visible: bool) -> None:
        """Show or hide the corner magnifier loupe during precision edits."""
        self._loupe_visible = bool(visible)
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
        pick the frame it is showing.  ``value_at``
        rounds to the nearest sample, so between two frames it can name the
        coordinate belonging to a frame that is not on screen — harmless while
        the overlay only drew, wrong once a drag has to say which frame it
        corrected. Mapped readers use the shared availability policy for gaps
        and coverage; legacy readers use the local fallback below.
        """
        try:
            sample = self._sample_readable(reader)
        except (OSError, ValueError) as error:
            self._reader_unavailable(reader, error)
            return None
        self._reported_reader_errors.discard(id(reader))
        return sample

    def _sample_readable(self, reader: Any) -> tuple[int, float] | None:
        """Read a point after the paint boundary has installed its error guard."""
        available = getattr(reader, "available_sample_at", None)
        if available is not None:
            return cast(tuple[int, float] | None, available(self.t))
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

    def _reader_unavailable(self, reader: Any, error: OSError | ValueError) -> None:
        """Report a lost channel once while letting later paints retry it."""
        identity = id(reader)
        if identity in self._reported_reader_errors:
            return
        self._reported_reader_errors.add(identity)
        logger.warning(
            "Tracking overlay skipped unavailable channel %s: %s",
            getattr(reader, "channel_id", "<unknown>"),
            error,
        )

    def _resolve(self, track: OverlayTrack) -> list[ResolvedPoint]:
        """Return every body part of *track* that has a position right now.

        Sorted by name for deterministic paint order only; colour is name-keyed
        from the shared 2D/3D body-part palette (:func:`color_for_point`).
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
            # Keyed by the column this marker is *drawing*, which is another
            # point's once a flip has been accepted: a correction is a fact
            # about the trajectory under the pointer, not about the label on
            # it. The label rides along as provenance.
            key = (
                PointKey(source_id, self.data_point(source_id, name, index), index)
                if source_id
                else None
            )
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
            conf_value: float | None = None
            lik_reader = track.likelihood.get(name)
            if lik_reader is not None and not corrected:
                lik_sample = self._sample(lik_reader)
                if lik_sample is not None and np.isfinite(lik_sample[1]):
                    conf_value = float(lik_sample[1])
            resolved.append(
                ResolvedPoint(
                    name=name,
                    x=float(x_value),
                    y=float(y_value),
                    color=color_for_point(name),
                    key=key,
                    corrected=corrected,
                    confidence=conf_value,
                )
            )
        return resolved

    def _resolve_loose_points(self) -> list[ResolvedPoint]:
        """Return complete XY loose-reader points at ``self.t``."""
        points: dict[str, dict[str, float]] = {}
        for reader, point_name, axis in self._active_loose_xy():
            sample = self._sample(reader)
            if sample is None or not np.isfinite(sample[1]):
                continue
            points.setdefault(point_name, {})[axis] = sample[1]
        return [
            ResolvedPoint(
                name=name,
                x=float(coords["x"]),
                y=float(coords["y"]),
                color=color_for_point(name),
                key=None,
                corrected=False,
            )
            for name, coords in sorted(points.items())
            if "x" in coords and "y" in coords
        ]

    # ── painting ─────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw every active pose, reprojection, prop, and guide layer at ``self.t``."""
        del event
        draw_raw_points = self._points_visible or self._edit_mode
        want_raw = (draw_raw_points or self._skeleton_2d_visible) and bool(
            self._active_loose_xy() or self.tracks
        )
        draw_custom = bool(self._custom) and (self._custom_visible or self._edit_mode)
        wheel = self._wheel(self.t) if self._wheel is not None else None
        props = self._props(self.t) if self._props is not None and self._props_visible else []
        want_reproject = (
            self._reprojection_visible or self._reprojection_skeleton_visible
        ) and self._reprojection is not None
        epipolar = (
            self._epipolar(self.t) if self._epipolar is not None and self._epipolar_visible else []
        )
        loupe = self._loupe_visible and self._loupe_video_xy is not None
        if (
            not want_raw
            and not draw_custom
            and not want_reproject
            and wheel is None
            and not props
            and not epipolar
            and not loupe
        ):
            return
        geometry = self._video_scale()
        if geometry is None:
            return
        scale, offset_x, offset_y = geometry

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._paint_layers(
                painter,
                draw_raw_points,
                want_raw,
                draw_custom,
                want_reproject,
                wheel,
                props,
                epipolar,
                scale,
                offset_x,
                offset_y,
            )
        finally:
            # A Python exception must not return control to Qt with this widget
            # still being painted; that leaves the backing store in an invalid
            # state and can turn one read error into a native crash.
            painter.end()

    def _paint_layers(
        self,
        painter: QPainter,
        draw_raw_points: bool,
        want_raw: bool,
        draw_custom: bool,
        want_reproject: bool,
        wheel: WheelDrawing | None,
        props: list[PropDrawing],
        epipolar: list[tuple[str, Any]],
        scale: float,
        offset_x: float,
        offset_y: float,
    ) -> None:
        """Draw the registered video layers with an active painter."""
        bounds, chrome = self._label_area(scale, offset_x, offset_y)
        if props:
            draw_props(painter, props, scale, offset_x, offset_y, bounds, chrome)
        if epipolar:
            draw_epipolar_guides(painter, epipolar, scale, offset_x, offset_y)

        if wheel is not None:
            # Under the tracking, so a bar never hides the paw standing on it.
            draw_wheel(
                painter,
                wheel,
                scale,
                offset_x,
                offset_y,
                show_facing=self._wheel_visible,
                show_hidden=self._wheel_hidden_visible,
            )

        reproj_points = self._resolve_reprojection() if want_reproject else []
        ordered_tracks = sorted(self.tracks, key=lambda track: track.is_ensemble) if want_raw else []
        has_ensemble = any(track.is_ensemble for track in ordered_tracks)
        track_batches = [
            (
                track,
                bool(track.is_ensemble or (not has_ensemble and len(ordered_tracks) == 1)),
                self._resolve(track),
            )
            for track in ordered_tracks
        ]
        loose_active = bool(want_raw and self._active_loose_xy())
        loose_points = self._resolve_loose_points() if loose_active else []
        raw_has_visible = any(bool(pts) for _t, _p, pts in track_batches) or bool(loose_points)
        reproj_has_visible = bool(reproj_points)
        raw_skel_rgb, reproj_skel_rgb = skeleton_comparison_colors(
            raw_active=raw_has_visible,
            reprojection_active=reproj_has_visible,
        )

        drawn: list[tuple[str, tuple[int, int, int]]] = []
        for track, is_primary, resolved in track_batches:
            if self._draw_track(
                painter,
                track,
                scale,
                offset_x,
                offset_y,
                resolved=resolved,
                is_primary=is_primary,
                draw_markers=draw_raw_points,
                skeleton_color=raw_skel_rgb,
            ):
                drawn.append((track.label, track.color))

        if loose_active:
            self._draw_loose_readers(
                painter, scale, offset_x, offset_y, skeleton_color=raw_skel_rgb
            )

        if reproj_has_visible:
            self._draw_reprojection(
                painter,
                scale,
                offset_x,
                offset_y,
                points=reproj_points,
                skeleton_color=reproj_skel_rgb,
                dashed_skeleton=raw_has_visible,
                show_labels=self._point_labels_visible and not (raw_has_visible and draw_raw_points),
            )

        legend_entries = list(drawn) if len(drawn) > 1 else []
        if (
            raw_has_visible
            and reproj_has_visible
            and self._skeleton_2d_visible
            and self._reprojection_skeleton_visible
        ):
            legend_entries.append((tr("2D skeleton"), raw_skel_rgb))
            legend_entries.append((tr("3D reprojection skeleton"), reproj_skel_rgb))
        if self._show_legend and len(legend_entries) > 1:
            self._draw_legend(painter, legend_entries)

        if draw_custom:
            self._draw_custom(painter, scale, offset_x, offset_y)

        if wheel is not None and (wheel.clicks or wheel.projections or wheel.prompt):
            draw_wheel_clicks(painter, wheel, scale, offset_x, offset_y, bounds, chrome)
        if self._loupe_visible and self._loupe_video_xy is not None:
            surface = getattr(self.parent(), "surface", None)
            image = getattr(surface, "_image", None) if surface is not None else None
            draw_magnifier_loupe(
                painter,
                image,
                self._loupe_video_xy,
                self.width(),
                self.height(),
                scale,
                offset_x,
                offset_y,
            )

    def _label_area(
        self, scale: float, offset_x: float, offset_y: float
    ) -> tuple[QRectF, tuple[QRectF, ...]]:
        """The visible picture labels stay inside, and the pane chrome they avoid.

        Labels belong on the picture, not on the letterbox, and never under the
        file name, the timing readout, or the zoom buttons drawn over it.
        """
        area = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        parent = self.parent()
        size = getattr(getattr(parent, "surface", None), "video_size", None)
        if size is not None:
            picture = QRectF(offset_x, offset_y, size[0] * scale, size[1] * scale)
            area = area.intersected(picture.adjusted(2, 2, -2, -2))
        chrome: list[QRectF] = []
        # The pane's declared contract, not its widgets looked up by name.
        chrome_rects = getattr(parent, "chrome_rects", None)
        if isinstance(parent, QWidget) and callable(chrome_rects):
            for rect in chrome_rects():
                corner = self.mapFrom(parent, rect.topLeft())
                chrome.append(QRectF(QPointF(corner), QSizeF(rect.size())).adjusted(-3, -3, 3, 3))
        return area, tuple(chrome)

    def _draw_track(
        self,
        painter: QPainter,
        track: OverlayTrack,
        scale: float,
        offset_x: float,
        offset_y: float,
        *,
        resolved: list[ResolvedPoint] | None = None,
        is_primary: bool | None = None,
        draw_markers: bool = True,
        skeleton_color: tuple[int, int, int] = SOLO_SKELETON_COLOR,
    ) -> bool:
        """Draw one prediction source; returns whether anything was visible."""
        primary = track.is_ensemble if is_primary is None else is_primary
        radius = marker_radius() if primary else _MODEL_RADIUS

        label_font = painter.font()
        label_font.setPointSizeF(overlay_label_point_size())
        label_font.setBold(primary)

        pts = self._resolve(track) if resolved is None else resolved
        if self._trails_visible and draw_markers and pts:
            draw_motion_trails(
                painter, track, pts, scale, offset_x, offset_y, trail_frame_count()
            )
        any_drawn = False
        if self._skeleton_2d_visible and primary and len(pts) >= 2:
            draw_2d_skeleton(
                painter,
                pts,
                self.active_skeleton_edges(track.edges),
                scale,
                offset_x,
                offset_y,
                color=skeleton_color,
                dashed=False,
            )
            any_drawn = True
        if not draw_markers:
            return any_drawn

        thresh = confidence_threshold()
        for point in pts:
            x = offset_x + point.x * scale
            y = offset_y + point.y * scale

            color = QColor(*point.color)
            low_conf = style_point_by_confidence(
                painter,
                color,
                point.confidence,
                thresh,
                enabled=self._confidence_visible,
                is_ensemble=primary,
            )
            r = (radius + 2) if low_conf else radius
            painter.drawEllipse(int(x) - r, int(y) - r, r * 2, r * 2)
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
        # A stroked path, not two `drawText` calls: `drawText` fills glyphs and
        # ignores pen width, so the "outline" sat exactly under the coloured
        # text and a cyan label on a cyan blob was unreadable.
        path = QPainterPath()
        path.addText(QPointF(int(x) + _LABEL_DX, int(y) + _LABEL_DY), font, name)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.strokePath(
            path,
            QPen(
                QColor(0, 0, 0, 200),
                3,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            ),
        )
        painter.fillPath(path, color)
        painter.restore()

    def _draw_loose_readers(
        self,
        painter: QPainter,
        scale: float,
        offset_x: float,
        offset_y: float,
        *,
        skeleton_color: tuple[int, int, int] = SOLO_SKELETON_COLOR,
    ) -> None:
        resolved = self._resolve_loose_points()
        if self._skeleton_2d_visible and len(resolved) >= 2:
            draw_2d_skeleton(
                painter,
                resolved,
                self.active_skeleton_edges(),
                scale,
                offset_x,
                offset_y,
                color=skeleton_color,
                dashed=False,
            )
        if not (self._points_visible or self._edit_mode):
            return
        label_font = painter.font()
        label_font.setPointSizeF(overlay_label_point_size())
        for point in resolved:
            qcolor = QColor(*point.color)
            painter.setPen(QPen(qcolor, 3))
            painter.setBrush(qcolor)
            x = offset_x + point.x * scale
            y = offset_y + point.y * scale
            painter.drawEllipse(int(x) - 3, int(y) - 3, 6, 6)
            if self._point_labels_visible and point.name:
                self._draw_point_label(painter, label_font, qcolor, point.name, x, y)

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
        if (
            self._active_loose_xy()
            or self.tracks
            or self._custom
            or self._wheel is not None
            or (self._props is not None and self._props_visible)
            or (
                self._reprojection is not None
                and (self._reprojection_visible or self._reprojection_skeleton_visible)
            )
        ):
            self.update()
