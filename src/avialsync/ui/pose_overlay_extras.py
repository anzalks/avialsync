"""2D pose overlay rendering helpers: skeleton limbs, trails, confidence, loupe, epipolar."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF

from avialsync.core.settings_schema import setting_for
from avialsync.ui.app_settings import settings_revision
from avialsync.ui.preferences_dialog import read_setting
from avialsync.ui.tracking_colors import color_for_point

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow
    from avialsync.ui.marker_overlay import ResolvedPoint
    from avialsync.ui.video_overlay import OverlayTrack

__all__ = [
    "confidence_threshold",
    "draw_2d_skeleton",
    "draw_epipolar_guides",
    "draw_magnifier_loupe",
    "draw_motion_trails",
    "epipolar_guides_for",
    "infer_2d_edges",
    "invalidate_overlay_settings_cache",
    "marker_radius",
    "style_point_by_confidence",
    "trail_frame_count",
]

_LOUPE_SIZE = 136
_LOUPE_ZOOM = 5.0
_cached_settings_revision: int = -1
_cached_marker_radius: int | None = None
_cached_confidence_threshold: float | None = None
_cached_trail_frames: int | None = None


def invalidate_overlay_settings_cache() -> None:
    """Drop cached overlay settings so the next paint re-reads updated preferences."""
    global _cached_settings_revision, _cached_marker_radius
    global _cached_confidence_threshold, _cached_trail_frames
    _cached_settings_revision = -1
    _cached_marker_radius = None
    _cached_confidence_threshold = None
    _cached_trail_frames = None


def _sync_revision() -> None:
    global _cached_settings_revision, _cached_marker_radius
    global _cached_confidence_threshold, _cached_trail_frames
    rev = settings_revision()
    if rev != _cached_settings_revision:
        _cached_settings_revision = rev
        _cached_marker_radius = None
        _cached_confidence_threshold = None
        _cached_trail_frames = None


def marker_radius() -> int:
    """Read the configured pose marker radius in logical pixels (cached off paint path)."""
    global _cached_marker_radius
    _sync_revision()
    if _cached_marker_radius is None:
        setting = setting_for("overlays/marker_radius")
        val = int(read_setting(setting)) if setting is not None else 5
        _cached_marker_radius = max(2, min(12, val))
    return _cached_marker_radius


def confidence_threshold() -> float:
    """Read the configured pose likelihood cutoff in ``[0.0, 1.0]`` (cached off paint path)."""
    global _cached_confidence_threshold
    _sync_revision()
    if _cached_confidence_threshold is None:
        setting = setting_for("overlays/confidence_threshold")
        val = float(read_setting(setting)) if setting is not None else 0.3
        _cached_confidence_threshold = min(max(val, 0.0), 1.0)
    return _cached_confidence_threshold


def trail_frame_count() -> int:
    """Read the configured motion-trail window in frames (cached off paint path)."""
    global _cached_trail_frames
    _sync_revision()
    if _cached_trail_frames is None:
        setting = setting_for("overlays/trail_frames")
        val = int(read_setting(setting)) if setting is not None else 15
        _cached_trail_frames = max(1, min(120, val))
    return _cached_trail_frames


def infer_2d_edges(points: Sequence[ResolvedPoint]) -> list[tuple[str, str]]:
    """Build a lightweight 2D minimum spanning tree when no explicit skeleton is given.

    Connects points belonging to the same individual prefix (if any) without
    bridging two animals or long outlier jumps (> 40 % of the span).
    """
    if len(points) < 2:
        return []
    by_group: dict[str, list[ResolvedPoint]] = {}
    for pt in points:
        prefix = pt.name.split("_", 1)[0] if "_" in pt.name else ""
        # Group only when several points share a prefix (multi-animal naming).
        by_group.setdefault(prefix, []).append(pt)
    if all(len(members) == 1 for members in by_group.values()):
        groups = [list(points)]
    else:
        groups = [m for m in by_group.values() if len(m) >= 2]

    edges: list[tuple[str, str]] = []
    for members in groups:
        coords = np.array([(m.x, m.y) for m in members], dtype=np.float64)
        span = float(np.hypot(*(coords.max(axis=0) - coords.min(axis=0))))
        max_len = span * 1.01 if len(members) <= 3 else max(span * 0.75, 24.0)
        n = len(members)
        in_tree = [False] * n
        in_tree[0] = True
        for _ in range(n - 1):
            best_pair: tuple[int, int] | None = None
            best_dist = float("inf")
            for i in range(n):
                if not in_tree[i]:
                    continue
                for j in range(n):
                    if in_tree[j]:
                        continue
                    d = float(np.hypot(coords[i, 0] - coords[j, 0], coords[i, 1] - coords[j, 1]))
                    if d < best_dist:
                        best_dist = d
                        best_pair = (i, j)
            if best_pair is None:
                break
            in_tree[best_pair[1]] = True
            if best_dist <= max_len:
                edges.append((members[best_pair[0]].name, members[best_pair[1]].name))
    return edges


def draw_2d_skeleton(
    painter: QPainter,
    points: Sequence[ResolvedPoint],
    declared_edges: Sequence[tuple[str, str]],
    scale: float,
    offset_x: float,
    offset_y: float,
) -> None:
    """Paint limb segments behind the 2D pose markers."""
    if len(points) < 2:
        return
    by_name = {pt.name: pt for pt in points}
    edges = [(a, b) for a, b in declared_edges if a in by_name and b in by_name] or infer_2d_edges(
        points
    )
    if not edges:
        return
    painter.save()
    under_pen = QPen(QColor(0, 0, 0, 140), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    line_pen = QPen(QColor(235, 240, 245, 185), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    for name_a, name_b in edges:
        pa, pb = by_name[name_a], by_name[name_b]
        p1 = QPointF(offset_x + pa.x * scale, offset_y + pa.y * scale)
        p2 = QPointF(offset_x + pb.x * scale, offset_y + pb.y * scale)
        painter.setPen(under_pen)
        painter.drawLine(p1, p2)
        painter.setPen(line_pen)
        painter.drawLine(p1, p2)
    painter.restore()


def draw_motion_trails(
    painter: QPainter,
    track: OverlayTrack,
    resolved: Sequence[ResolvedPoint],
    scale: float,
    offset_x: float,
    offset_y: float,
    frames: int,
) -> None:
    """Draw fading recent-history comet tails from mmap'd reader columns."""
    if frames <= 0:
        return
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for pt in resolved:
        readers = track.points.get(pt.name)
        if readers is None or pt.key is None:
            continue
        rx, ry = readers
        cols_x = getattr(rx, "mapped_columns", None)
        cols_y = getattr(ry, "mapped_columns", None)
        if not callable(cols_x) or not callable(cols_y):
            continue
        try:
            _, vx, gx = cols_x()
            _, vy, gy = cols_y()
        except (OSError, ValueError):
            continue
        end_idx = min(pt.key.index, len(vx) - 1, len(vy) - 1)
        start_idx = max(0, end_idx - frames)
        if end_idx <= start_idx:
            continue
        xs = np.asarray(vx[start_idx : end_idx + 1], dtype=np.float64)
        ys = np.asarray(vy[start_idx : end_idx + 1], dtype=np.float64)
        gaps = np.asarray(gx[start_idx:end_idx], dtype=bool) | np.asarray(
            gy[start_idx:end_idx], dtype=bool
        )
        valid = (
            (~gaps)
            & np.isfinite(xs[:-1])
            & np.isfinite(ys[:-1])
            & np.isfinite(xs[1:])
            & np.isfinite(ys[1:])
        )
        if not np.any(valid):
            continue
        base_color = QColor(*pt.color)
        count = len(xs) - 1
        for k in np.flatnonzero(valid):
            idx = int(k)
            frac = (idx + 1) / count
            seg_color = QColor(base_color)
            seg_color.setAlpha(int(35 + 175 * frac))
            painter.setPen(QPen(seg_color, 1.0 + 1.4 * frac, Qt.PenStyle.SolidLine))
            painter.drawLine(
                QPointF(offset_x + float(xs[idx]) * scale, offset_y + float(ys[idx]) * scale),
                QPointF(
                    offset_x + float(xs[idx + 1]) * scale, offset_y + float(ys[idx + 1]) * scale
                ),
            )
    painter.restore()


def style_point_by_confidence(
    painter: QPainter,
    color: QColor,
    confidence: float | None,
    threshold: float,
    *,
    enabled: bool,
    is_ensemble: bool,
) -> bool:
    """Configure *painter* pen/brush; returns True when styled as low-confidence."""
    width = 2 if is_ensemble else 1
    if not enabled or confidence is None or not np.isfinite(confidence) or confidence >= threshold:
        outline = QColor(12, 14, 18, 210) if is_ensemble else color
        painter.setPen(QPen(outline, 1.5 if is_ensemble else 1.0))
        painter.setBrush(color)
        return False
    ratio = max(0.15, float(confidence) / max(threshold, 1e-3))
    ring = QColor(color)
    ring.setAlpha(int(120 + 110 * ratio))
    fill = QColor(color)
    fill.setAlpha(int(45 * ratio))
    painter.setPen(QPen(ring, width, Qt.PenStyle.DashLine))
    painter.setBrush(fill)
    return True


def draw_epipolar_guides(
    painter: QPainter,
    guides: Sequence[tuple[str, np.ndarray]],
    scale: float,
    offset_x: float,
    offset_y: float,
) -> None:
    """Draw projected epipolar ray curves from clicks in other calibrated cameras."""
    if not guides:
        return
    painter.save()
    for name, pixels in guides:
        if len(pixels) < 2:
            continue
        poly = QPolygonF(
            [
                QPointF(offset_x + float(px) * scale, offset_y + float(py) * scale)
                for px, py in pixels
            ]
        )
        color = QColor(*color_for_point(name))
        halo = QPen(QColor(0, 0, 0, 175), 3.5, Qt.PenStyle.SolidLine)
        dash = QPen(color, 1.8, Qt.PenStyle.DashLine)
        painter.setPen(halo)
        painter.drawPolyline(poly)
        painter.setPen(dash)
        painter.drawPolyline(poly)
    painter.restore()


def draw_magnifier_loupe(
    painter: QPainter,
    image: QImage | None,
    video_xy: tuple[float, float],
    widget_width: int,
    widget_height: int,
    scale: float,
    offset_x: float,
    offset_y: float,
) -> None:
    """Paint a 5x corner magnifier inset around *video_xy* during precision edits."""
    if image is None or image.isNull() or widget_width < 180 or widget_height < 180:
        return
    vx, vy = video_xy
    cursor_wx = offset_x + vx * scale
    # Place inset in top-right unless the cursor is already in the right half, in
    # which case place it in top-left (below the header readout).
    margin = 10
    top = 34
    left = (
        margin
        if cursor_wx > widget_width * 0.5
        else max(margin, widget_width - _LOUPE_SIZE - margin)
    )
    target = QRectF(left, top, _LOUPE_SIZE, _LOUPE_SIZE)

    half_patch = (_LOUPE_SIZE / _LOUPE_ZOOM) * 0.5
    ix0 = max(0, int(round(vx - half_patch)))
    iy0 = max(0, int(round(vy - half_patch)))
    ix1 = min(image.width(), int(round(vx + half_patch)))
    iy1 = min(image.height(), int(round(vy + half_patch)))
    if ix1 <= ix0 or iy1 <= iy0:
        return
    cropped = image.copy(QRect(ix0, iy0, ix1 - ix0, iy1 - iy0))

    painter.save()
    clip = QPainterPath()
    clip.addRoundedRect(target, 8.0, 8.0)
    painter.fillPath(clip, QColor(0, 0, 0, 220))
    painter.setClipPath(clip)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    painter.drawImage(target, cropped)
    painter.setClipping(False)

    # Frame + precision crosshair at exact sub-pixel target
    painter.setPen(QPen(QColor(0, 0, 0, 200), 3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(target, 8.0, 8.0)
    painter.setPen(QPen(QColor(255, 255, 255, 230), 1.5))
    painter.drawRoundedRect(target, 8.0, 8.0)

    cx = left + ((vx - ix0) / max(1, ix1 - ix0)) * _LOUPE_SIZE
    cy = top + ((vy - iy0) / max(1, iy1 - iy0)) * _LOUPE_SIZE
    painter.setPen(QPen(QColor(0, 255, 255, 220), 1.2))
    painter.drawLine(QPointF(cx - 10, cy), QPointF(cx + 10, cy))
    painter.drawLine(QPointF(cx, cy - 10), QPointF(cx, cy + 10))
    painter.restore()


def epipolar_guides_for(
    window: MainWindow, target_video: str, _t_master: float
) -> list[tuple[str, np.ndarray]]:
    """Return ``[(name, pixels)]`` epipolar curves for *target_video* from sibling clicks/drags."""
    from avialsync.core.calibration import epipolar_curve

    state = window._calibration_state
    if state is None or target_video not in state.cameras:
        return []
    target_cam = state.cameras[target_video]
    sources: list[tuple[str, str, tuple[float, float]]] = []
    placement = window._marker_placement
    if placement is not None:
        for clicked_video, xy in placement.clicks.items():
            sources.append((placement.name, clicked_video, xy))
    for pane_path, pane in zip(
        window.video_grid.pane_paths(), window.video_grid.panes, strict=False
    ):
        canvas = getattr(pane, "paint_canvas", None)
        active = getattr(canvas, "active_drag_point", None) if canvas is not None else None
        if active is not None:
            sources.append((active[0], pane_path, active[1]))
    guides: list[tuple[str, np.ndarray]] = []
    for name, src_video, pixel in sources:
        if src_video == target_video or src_video not in state.cameras:
            continue
        curve = epipolar_curve(state.cameras[src_video], target_cam, pixel)
        if len(curve) >= 2:
            guides.append((name, curve))
    return guides
