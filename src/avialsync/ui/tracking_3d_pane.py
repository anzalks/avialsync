"""Interactive 3D view for cached tracking-coordinate channels."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.timeline import TimeMap
from avialsync.ui.tracking_colors import color_for_point, register_points

_MAX_LABELS = 24
_SAMPLE_TOLERANCE_S = 0.1

# Landmark name fragments used to orient the view anatomically (D-046).
# Matching is substring-based and case-insensitive; unmatched data keeps the
# neutral Z-up default rather than guessing.
_HEAD_HINTS = ("head", "nose", "snout", "skull", "ear", "eye", "beak")
_FOOT_HINTS = ("toe", "foot", "feet", "ankle", "heel", "paw", "hoof")
# Samples used to estimate the anatomical axis; bounded so a long session does
# not turn view setup into a full-trajectory scan.
_ORIENT_SAMPLE_LIMIT = 4096


def _view_matrix(up_axis: int, up_sign: float) -> np.ndarray:
    """Build a right-handed basis whose third row is the chosen 'up' direction.

    Rows map world XYZ onto view XYZ, so ``points @ matrix.T`` puts the
    anatomical vertical on view +Z, which is what the camera math treats as up.
    """
    identity = np.eye(3, dtype=np.float64)
    others = [index for index in range(3) if index != up_axis]
    matrix = np.stack((identity[others[0]], identity[others[1]], identity[up_axis] * up_sign))
    if np.linalg.det(matrix) < 0:
        matrix[[0, 1]] = matrix[[1, 0]]
    return matrix


@dataclass(frozen=True)
class _PointChannels:
    """Memory-mapped coordinate arrays for one named point."""

    name: str
    values: tuple[np.ndarray, np.ndarray, np.ndarray]
    gaps: tuple[np.ndarray, np.ndarray, np.ndarray]


@dataclass(frozen=True)
class _SourceSamples:
    """Tracking points whose coordinates share one source timestamp array.

    ``times`` stays in the source's own time base — mapping a whole trajectory
    to master time would copy it.  ``time_map`` converts the scalar cursor query
    instead, which is what keeps pose sampling inside the ≤2 ms tick budget.
    """

    times: np.ndarray
    points: tuple[_PointChannels, ...]
    time_map: TimeMap


def _coordinate_name(channel_id: str) -> tuple[str, str] | None:
    """Return ``(point_name, axis)`` for the standard ``name_axis`` convention."""
    name, separator, axis = channel_id.rpartition("_")
    axis = axis.lower()
    if separator and name and axis in {"x", "y", "z"}:
        return name, axis
    return None


def _nearest_index(times: np.ndarray, target: float) -> int | None:
    """Find the nearest timestamp without scanning a trajectory."""
    if len(times) == 0:
        return None
    right = int(np.searchsorted(times, target))
    if right == 0:
        index = 0
    elif right == len(times):
        index = len(times) - 1
    elif target - float(times[right - 1]) <= float(times[right]) - target:
        index = right - 1
    else:
        index = right
    if abs(float(times[index]) - target) > _SAMPLE_TOLERANCE_S:
        return None
    return index


def _build_sources(readers: Iterable[MappedChannelReader]) -> tuple[_SourceSamples, ...]:
    """Group complete XYZ triplets by source cache and pre-warm their mmap arrays."""
    by_source: dict[Path, dict[str, dict[str, MappedChannelReader]]] = {}
    for reader in readers:
        coordinate = _coordinate_name(reader.channel_id)
        if coordinate is None:
            continue
        point_name, axis = coordinate
        source_points = by_source.setdefault(reader.cache_dir, {})
        source_points.setdefault(point_name, {})[axis] = reader

    sources: list[_SourceSamples] = []
    for source_points in by_source.values():
        points: list[_PointChannels] = []
        reference_times: np.ndarray | None = None
        reference_length = -1
        source_time_map = TimeMap()
        for point_name, axes in source_points.items():
            if set(axes) != {"x", "y", "z"}:
                continue
            arrays = [axes[axis].mapped_columns() for axis in ("x", "y", "z")]
            # All rows of one source share a TimeMap, so any axis reports it.
            source_time_map = getattr(axes["x"], "time_map", source_time_map)
            lengths = {len(item[0]) for item in arrays}
            if len(lengths) != 1:
                continue
            sample_count = lengths.pop()
            if reference_times is None:
                reference_times = arrays[0][0]
                reference_length = sample_count
            if sample_count != reference_length:
                continue
            points.append(
                _PointChannels(
                    name=point_name,
                    values=(arrays[0][1], arrays[1][1], arrays[2][1]),
                    gaps=(arrays[0][2], arrays[1][2], arrays[2][2]),
                )
            )
        if reference_times is not None and points:
            sources.append(
                _SourceSamples(
                    times=reference_times,
                    points=tuple(points),
                    time_map=source_time_map,
                )
            )
    return tuple(sources)


def _mean_axis_position(
    sources: tuple[_SourceSamples, ...], hints: tuple[str, ...]
) -> np.ndarray | None:
    """Mean XYZ of every point whose name matches *hints*, or None if none match."""
    totals = np.zeros(3, dtype=np.float64)
    matched = 0
    for source in sources:
        for point in source.points:
            lowered = point.name.lower()
            if not any(hint in lowered for hint in hints):
                continue
            sample_count = len(point.values[0])
            if sample_count == 0:
                continue
            step = max(1, sample_count // _ORIENT_SAMPLE_LIMIT)
            means = []
            for axis in range(3):
                window = point.values[axis][::step]
                with np.errstate(invalid="ignore"):
                    means.append(np.nanmean(window))
            if not all(np.isfinite(value) for value in means):
                continue
            totals += np.asarray(means, dtype=np.float64)
            matched += 1
    if matched == 0:
        return None
    return totals / matched


def detect_up_axis(sources: tuple[_SourceSamples, ...]) -> tuple[int, bool] | None:
    """Infer which world axis is anatomically vertical, and whether it is flipped.

    Returns ``(axis_index, inverted)`` where *inverted* means larger coordinate
    values are anatomically lower -- the usual case for image-derived
    reconstructions, whose vertical axis grows downward. Returns ``None`` when
    the data carries no recognisable head/foot landmarks, so the caller can keep
    a neutral default instead of guessing (AGENTS: never silently invent).
    """
    head = _mean_axis_position(sources, _HEAD_HINTS)
    foot = _mean_axis_position(sources, _FOOT_HINTS)
    if head is None or foot is None:
        return None
    separation = head - foot
    axis = int(np.argmax(np.abs(separation)))
    if not np.isfinite(separation[axis]) or separation[axis] == 0.0:
        return None
    # head below foot in raw coordinates => the axis grows downward
    return axis, bool(separation[axis] < 0)


class Tracking3DCanvas(QWidget):
    """Custom-painted current-pose view with mouse orbit and wheel zoom."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(160, 140)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Interactive 3D tracking plot")
        self.setMouseTracking(True)

        self._sources: tuple[_SourceSamples, ...] = ()
        self._names: tuple[str, ...] = ()
        self._positions = np.empty((0, 3), dtype=np.float64)
        self._valid = np.empty(0, dtype=bool)
        self._time = 0.0
        self._skeleton_edges: list[tuple[str, str]] = []

        # Which world axis renders upward. Z-up is the neutral default; loading
        # data with recognisable head/foot landmarks re-orients it (D-046).
        self._up_axis = 2
        self._up_inverted = False
        self._up_auto = True
        self._view_basis = _view_matrix(self._up_axis, 1.0)

        self._azimuth = math.radians(40.0)
        self._elevation = math.radians(25.0)
        self._zoom = 1.0
        self._center = np.zeros(3, dtype=np.float64)
        self._radius = 1.0
        self._scene_min = np.zeros(3, dtype=np.float64)
        self._scene_max = np.zeros(3, dtype=np.float64)
        self._has_scene_bounds = False
        self._drag_origin: QPoint | None = None

    @property
    def point_count(self) -> int:
        """Number of complete XYZ points available to the view."""
        return len(self._names)

    @property
    def point_names(self) -> tuple[str, ...]:
        """Names of complete XYZ coordinate triplets."""
        return self._names

    @property
    def positions(self) -> np.ndarray:
        """Copy of the currently sampled XYZ positions, including NaN placeholders."""
        return self._positions.copy()

    @property
    def up_axis(self) -> int:
        """Index of the world axis currently rendered upward."""
        return self._up_axis

    @property
    def up_inverted(self) -> bool:
        """Whether larger values on :attr:`up_axis` render downward."""
        return self._up_inverted

    def set_up_axis(self, axis: int, inverted: bool, *, automatic: bool = False) -> None:
        """Choose which world axis renders upward, and its direction.

        Setting this explicitly (``automatic=False``) pins the choice, so later
        data loads do not silently re-orient a view the user has adjusted.
        """
        self._up_axis = int(axis) % 3
        self._up_inverted = bool(inverted)
        self._up_auto = automatic
        self._view_basis = _view_matrix(self._up_axis, -1.0 if self._up_inverted else 1.0)
        self._has_scene_bounds = False
        self.set_cursor(self._time)
        self.fit_current_pose()

    def _to_view(self, points: np.ndarray) -> np.ndarray:
        """Rotate world coordinates so the anatomical vertical is view +Z."""
        rotated: np.ndarray = np.asarray(points, dtype=np.float64) @ self._view_basis.T
        return rotated

    def set_readers(self, readers: Iterable[MappedChannelReader]) -> None:
        """Select complete XYZ triplets and retain only their mmap-backed arrays."""
        self._sources = _build_sources(readers)
        self._names = tuple(point.name for source in self._sources for point in source.points)
        # Colours are decided here, on the whole point set, rather than at paint
        # time: a body part the 2D overlay already named keeps that colour, and
        # one only this view knows about gets its own.
        register_points(self._names)
        self._positions = np.full((len(self._names), 3), np.nan, dtype=np.float64)
        self._valid = np.zeros(len(self._names), dtype=bool)
        self._has_scene_bounds = False
        if self._up_auto:
            detected = detect_up_axis(self._sources)
            if detected is not None:
                axis, inverted = detected
                self._up_axis = axis
                self._up_inverted = inverted
                self._view_basis = _view_matrix(axis, -1.0 if inverted else 1.0)
        self.set_cursor(self._time)

    def set_skeleton(self, edges: list[tuple[str, str]]) -> None:
        """Set explicit skeleton edges between named points.

        Each edge is a ``(name_a, name_b)`` pair referencing point names.
        Edges whose endpoints are not both present/valid are silently skipped.
        This never infers topology from names (D-041).
        """
        self._skeleton_edges = list(edges)
        self.update()

    def set_cursor(self, t_master: float) -> None:
        """Sample and display the pose nearest to the master-clock time."""
        self._time = t_master
        position_index = 0
        for source in self._sources:
            sample_index = _nearest_index(source.times, source.time_map.to_source(t_master))
            for point in source.points:
                values = np.full(3, np.nan, dtype=np.float64)
                if sample_index is not None:
                    for axis in range(3):
                        if not point.gaps[axis][sample_index]:
                            values[axis] = point.values[axis][sample_index]
                self._positions[position_index] = values
                position_index += 1
        self._valid = np.all(np.isfinite(self._positions), axis=1)
        self._expand_scene_bounds()
        self.update()

    def fit_current_pose(self) -> None:
        """Fit the camera to the valid points at the current master time."""
        valid_positions = self._to_view(self._positions[self._valid])
        if len(valid_positions) == 0:
            return
        self._scene_min = np.min(valid_positions, axis=0)
        self._scene_max = np.max(valid_positions, axis=0)
        self._has_scene_bounds = True
        self._update_camera_bounds()
        self._zoom = 1.0
        self.update()

    def reset_view(self) -> None:
        """Restore the default orbit and fit the current pose."""
        self._azimuth = math.radians(40.0)
        self._elevation = math.radians(25.0)
        self.fit_current_pose()

    def _expand_scene_bounds(self) -> None:
        valid_positions = self._to_view(self._positions[self._valid])
        if len(valid_positions) == 0:
            return
        current_min = np.min(valid_positions, axis=0)
        current_max = np.max(valid_positions, axis=0)
        if self._has_scene_bounds:
            self._scene_min = np.minimum(self._scene_min, current_min)
            self._scene_max = np.maximum(self._scene_max, current_max)
        else:
            self._scene_min = current_min
            self._scene_max = current_max
            self._has_scene_bounds = True
        self._update_camera_bounds()

    def _update_camera_bounds(self) -> None:
        self._center = (self._scene_min + self._scene_max) / 2.0
        span = self._scene_max - self._scene_min
        self._radius = max(float(np.max(span)) * 0.65, 1e-6)

    def _camera_basis(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        cos_elevation = math.cos(self._elevation)
        direction = np.array(
            [
                cos_elevation * math.cos(self._azimuth),
                cos_elevation * math.sin(self._azimuth),
                math.sin(self._elevation),
            ]
        )
        right = np.array([-math.sin(self._azimuth), math.cos(self._azimuth), 0.0])
        up = np.cross(direction, right)
        return right, up, direction

    def _project(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Project world points to screen; the anatomical vertical maps to screen up."""
        return self._project_view(self._to_view(points))

    def _project_view(self, view_points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Project points already expressed in view space (see :meth:`_to_view`)."""
        right, up, direction = self._camera_basis()
        relative = np.asarray(view_points, dtype=np.float64) - self._center
        scale = 0.38 * min(self.width(), self.height()) * self._zoom / self._radius
        screen = np.column_stack((relative @ right, relative @ up))
        screen *= scale
        screen[:, 0] += self.width() / 2.0
        screen[:, 1] = self.height() / 2.0 - screen[:, 1]
        return screen, relative @ direction

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw a bounded current pose; trajectory history is never rendered here."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)
        self._draw_grid(painter)

        valid_indices = np.flatnonzero(self._valid)
        if len(valid_indices) == 0:
            painter.setPen(QColor(120, 120, 120))
            message = (
                "Load tracking channels ending in _x, _y, and _z"
                if self.point_count == 0
                else "No 3D tracking at the current time"
            )
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, message)
            self._draw_corner_axes(painter)
            return

        # Build a name→screen-position map for skeleton drawing.
        screen, depth = self._project(self._positions[valid_indices])
        name_to_screen: dict[str, tuple[float, float]] = {}
        for i, vi in enumerate(valid_indices):
            name_to_screen[self._names[int(vi)]] = (float(screen[i, 0]), float(screen[i, 1]))

        # Draw skeleton edges behind the points.
        self._draw_skeleton(painter, name_to_screen)

        # Draw points depth-sorted (back to front).
        order = np.argsort(depth)
        for draw_order in order:
            point_index = int(valid_indices[draw_order])
            x, y = screen[draw_order]
            color = color_for_point(self._names[point_index])
            painter.setPen(QPen(QColor(80, 80, 80), 1))
            painter.setBrush(_qcolor(color))
            painter.drawEllipse(QPoint(round(float(x)), round(float(y))), 5, 5)
            if len(valid_indices) <= _MAX_LABELS:
                painter.setPen(QColor(40, 40, 40))
                painter.drawText(round(float(x)) + 7, round(float(y)) - 5, self._names[point_index])

        self._draw_corner_axes(painter)

    def _draw_skeleton(
        self,
        painter: QPainter,
        name_to_screen: dict[str, tuple[float, float]],
    ) -> None:
        """Draw explicit edges between connected named points."""
        if not self._skeleton_edges:
            return
        bone_pen = QPen(QColor(100, 100, 100), 2)
        painter.setPen(bone_pen)
        for name_a, name_b in self._skeleton_edges:
            pos_a = name_to_screen.get(name_a)
            pos_b = name_to_screen.get(name_b)
            if pos_a is not None and pos_b is not None:
                painter.drawLine(QPointF(*pos_a), QPointF(*pos_b))

    def _draw_grid(self, painter: QPainter) -> None:
        """Draw a light ground-plane grid behind the pose."""
        if not self._has_scene_bounds:
            return
        grid_color = QColor(200, 200, 200, 80)
        painter.setPen(QPen(grid_color, 1))

        radius = self._radius
        grid_points: list[np.ndarray] = []
        for step in np.linspace(-radius, radius, 7):
            grid_points.extend(
                [
                    self._center + np.array([-radius, step, 0.0]),
                    self._center + np.array([radius, step, 0.0]),
                    self._center + np.array([step, -radius, 0.0]),
                    self._center + np.array([step, radius, 0.0]),
                ]
            )
        # Grid points are constructed around the view-space centre already.
        grid_screen, _ = self._project_view(np.asarray(grid_points))
        for index in range(0, len(grid_screen), 2):
            start = grid_screen[index]
            end = grid_screen[index + 1]
            painter.drawLine(
                round(float(start[0])),
                round(float(start[1])),
                round(float(end[0])),
                round(float(end[1])),
            )

    def _draw_corner_axes(self, painter: QPainter) -> None:
        """Draw a compact orientation indicator in the bottom-left corner."""
        right, up, _direction = self._camera_basis()
        ax_len = 28  # pixels
        margin = 40
        cx = margin
        cy = self.height() - margin

        # Unit world axes carried into view space, so the labels keep naming the
        # source coordinate system even when a different axis renders upward.
        axes_3d = self._to_view(np.eye(3))
        labels = ("X", "Y", "Z")
        colors = ((220, 70, 70), (70, 180, 90), (70, 120, 230))
        for i in range(3):
            dx = float(np.dot(axes_3d[i], right)) * ax_len
            dy = -float(np.dot(axes_3d[i], up)) * ax_len  # screen Y is flipped
            painter.setPen(QPen(_qcolor(colors[i]), 2))
            painter.drawLine(cx, cy, round(cx + dx), round(cy + dy))
            painter.drawText(round(cx + dx * 1.25) - 3, round(cy + dy * 1.25) + 4, labels[i])

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin orbiting on a primary-button drag."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Orbit around the stable scene bounds."""
        if self._drag_origin is None or not event.buttons() & Qt.MouseButton.LeftButton:
            super().mouseMoveEvent(event)
            return
        current = event.position().toPoint()
        delta = current - self._drag_origin
        self._drag_origin = current
        self._azimuth += math.radians(delta.x() * 0.5)
        self._elevation = float(
            np.clip(self._elevation + math.radians(delta.y() * 0.5), -1.48, 1.48)
        )
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish an orbit gesture."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Zoom around the current scene center."""
        steps = event.angleDelta().y() / 120.0
        self._zoom = float(np.clip(self._zoom * (1.15**steps), 0.1, 20.0))
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Fit the current pose on double click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


def _qcolor(rgb: tuple[int, int, int]) -> QColor:
    """Construct QColor from an RGB tuple."""
    return QColor(*rgb)


class Tracking3DPane(QWidget):
    """Timeline-synchronized 3D tracking pane."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tracking_3d_pane")
        self.setAccessibleName("3D Tracking pane")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 4, 8, 4)
        self.title_label = QLabel("3D Tracking", header)
        self.status_label = QLabel("No XYZ tracking channels", header)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.up_axis_combo = QComboBox(header)
        self.up_axis_combo.setAccessibleName("Vertical axis")
        self.up_axis_combo.setToolTip(
            "Which source axis points up. Detected from head/foot landmarks on load; "
            "choose one here to override it."
        )
        for label, axis, inverted in (
            ("Up: X", 0, False),
            ("Up: -X", 0, True),
            ("Up: Y", 1, False),
            ("Up: -Y", 1, True),
            ("Up: Z", 2, False),
            ("Up: -Z", 2, True),
        ):
            self.up_axis_combo.addItem(label, (axis, inverted))
        self.up_axis_combo.activated.connect(self._on_up_axis_selected)
        self.fit_button = QPushButton("Fit View", header)
        self.fit_button.setToolTip("Fit the 3D camera to the current tracked pose")
        self.fit_button.clicked.connect(self._fit_view)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.status_label)
        header_layout.addWidget(self.up_axis_combo)
        header_layout.addWidget(self.fit_button)

        self.canvas = Tracking3DCanvas(self)
        layout.addWidget(header)
        layout.addWidget(self.canvas, 1)

    def set_readers(self, readers: list[MappedChannelReader]) -> None:
        """Use complete XYZ channel triplets from the active cached readers."""
        self.canvas.set_readers(readers)
        count = self.canvas.point_count
        suffix = "" if count == 1 else "s"
        self.status_label.setText(
            f"{count} tracked point{suffix}" if count else "No XYZ tracking channels"
        )
        self.fit_button.setEnabled(count > 0)
        self._sync_up_axis_combo()
        if count:
            self.canvas.fit_current_pose()

    def _sync_up_axis_combo(self) -> None:
        """Reflect the canvas's current orientation without re-triggering it."""
        target = (self.canvas.up_axis, self.canvas.up_inverted)
        index = self.up_axis_combo.findData(target)
        if index >= 0:
            self.up_axis_combo.blockSignals(True)
            self.up_axis_combo.setCurrentIndex(index)
            self.up_axis_combo.blockSignals(False)

    def _on_up_axis_selected(self, index: int) -> None:
        """Pin an explicit vertical axis chosen by the user."""
        data = self.up_axis_combo.itemData(index)
        if data is None:
            return
        axis, inverted = data
        self.canvas.set_up_axis(axis, inverted, automatic=False)

    def set_up_axis(self, axis: int, inverted: bool) -> None:
        """Pin which source axis renders upward (see :meth:`Tracking3DCanvas.set_up_axis`)."""
        self.canvas.set_up_axis(axis, inverted, automatic=False)
        self._sync_up_axis_combo()

    def set_skeleton(self, edges: list[tuple[str, str]]) -> None:
        """Set explicit skeleton connectivity for the 3D view."""
        self.canvas.set_skeleton(edges)

    def set_cursor(self, t_master: float) -> None:
        """Update from the same master-clock value used by video and 2D plots."""
        self.canvas.set_cursor(t_master)

    def _fit_view(self) -> None:
        self.canvas.reset_view()
