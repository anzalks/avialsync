"""Tests for Domain 1: 2D pose confidence, trails, skeleton, loupe, epipolar lines, and suspects."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
from PySide6.QtGui import QColor, QImage, QPainter

from avialsync.core.calibration import CameraModel, ImageCorrection, epipolar_curve
from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.point_edits import PointKey
from avialsync.core.pose import PosePoint, PoseSchema
from avialsync.core.pyramid import PyramidBuilder, PyramidReader
from avialsync.core.timeline import TimeMap
from avialsync.ui.controllers.calibration_controller import CalibrationState
from avialsync.ui.controllers.custom_marker_controller import MarkerPlacement
from avialsync.ui.main_window import MainWindow
from avialsync.ui.marker_overlay import ResolvedPoint
from avialsync.ui.pose_overlay_extras import (
    draw_2d_skeleton,
    draw_epipolar_guides,
    draw_magnifier_loupe,
    draw_motion_trails,
    epipolar_guides_for,
    infer_2d_edges,
    style_point_by_confidence,
)
from avialsync.ui.pose_suspects import find_suspects_in_cache, jump_suspect_frame
from avialsync.ui.video_overlay import OverlayTrack, PaintCanvas
from avialsync.ui.video_pane import VideoPane
from tests.wheel_fixture import CAMERAS


def _point_to_polyline_distance(pixel: np.ndarray, polyline: np.ndarray) -> float:
    """Minimum Euclidean distance from *pixel* to any segment of *polyline*."""
    best = float("inf")
    for idx in range(len(polyline) - 1):
        a = polyline[idx]
        b = polyline[idx + 1]
        ab = b - a
        denom = float(np.dot(ab, ab))
        t = 0.0 if denom <= 1e-12 else float(np.clip(np.dot(pixel - a, ab) / denom, 0.0, 1.0))
        proj = a + t * ab
        best = min(best, float(np.linalg.norm(pixel - proj)))
    return best


def test_epipolar_curve_passes_through_true_correspondence() -> None:
    """A 3D point seen in Front lies directly on the epipolar curve projected into Left & Right."""
    truth = np.array([15.0, -25.0, 90.0], dtype=np.float64)
    px_front = tuple(CAMERAS["Front"].project(truth)[0])
    for name in ("Left", "Right"):
        target = CAMERAS[name]
        expected_px = target.project(truth)[0]
        curve = epipolar_curve(CAMERAS["Front"], target, px_front, samples=64)
        assert curve.shape[1] == 2
        assert len(curve) >= 4
        assert _point_to_polyline_distance(expected_px, curve) < 0.25


def test_epipolar_curve_handles_lens_distortion_and_image_correction() -> None:
    """Distortion and thin-plate-spline corrections round-trip through epipolar sampling."""
    distorted_src = dataclasses.replace(
        CAMERAS["Front"],
        distortions=np.array([-0.08, 0.02, 0.001, -0.001, 0.0], dtype=np.float64),
    )
    grid_x, grid_y = np.meshgrid(np.linspace(50, 590, 4), np.linspace(50, 430, 4))
    ctrl = tuple((float(x), float(y)) for x, y in zip(grid_x.ravel(), grid_y.ravel(), strict=True))
    disp = tuple((1.5, -1.0) for _ in ctrl)
    correction = ImageCorrection(
        affine=((1.0, 0.0, 2.5), (0.0, 1.0, -1.5), (0.0, 0.0, 1.0)),
        control_pixels=ctrl,
        displacements=disp,
        size=CAMERAS["Left"].size,
    )
    corrected_tgt = dataclasses.replace(CAMERAS["Left"], correction=correction)

    truth = np.array([8.0, -20.0, 100.0], dtype=np.float64)
    px_src = tuple(distorted_src.project(truth)[0])
    px_tgt = corrected_tgt.project(truth)[0]
    curve = epipolar_curve(distorted_src, corrected_tgt, px_src, samples=64)
    assert len(curve) >= 4
    assert _point_to_polyline_distance(px_tgt, curve) < 0.5


def test_epipolar_curve_returns_empty_when_ray_stays_behind_target_camera() -> None:
    """A ray pointing away from *target_camera* yields a clean (0, 2) array."""
    src = CameraModel(
        name="Src",
        size=(640, 480),
        matrix=np.array([[500.0, 0.0, 320.0], [0.0, 500.0, 240.0], [0.0, 0.0, 1.0]]),
        distortions=np.zeros(5),
        rotation=np.zeros(3),
        translation=np.zeros(3),
    )
    # Target camera sits at z = +5 looking further along +z, while src looks along -z:
    # rotate src 180 deg around Y so its +z ray goes to world z < 0, behind tgt.
    src_away = dataclasses.replace(src, rotation=np.array([0.0, np.pi, 0.0]))
    tgt = dataclasses.replace(src, translation=np.array([0.0, 0.0, -5.0]))
    curve = epipolar_curve(src_away, tgt, (320.0, 240.0), samples=16)
    assert curve.shape == (0, 2)


def _build_pose_cache(tmp_path: Path) -> tuple[Path, PoseSchema]:
    cache_dir = tmp_path / "pose_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    n = 40
    times = np.arange(n, dtype=np.float64) * 0.05  # 20 Hz -> 0.0 to 1.95 s
    xs = 100.0 + np.arange(n, dtype=np.float64) * 1.5
    ys = 120.0 + np.sin(np.arange(n, dtype=np.float64) * 0.2) * 4.0
    # Inject an abrupt 95 px teleport spike at frame 25
    xs[25] += 95.0
    lik = np.full(n, 0.96, dtype=np.float64)
    # Inject a low-confidence dip around frame 10
    lik[9:12] = [0.22, 0.08, 0.19]

    snout_x = xs.copy()
    snout_y = ys.copy() + 18.0
    snout_lik = np.full(n, 0.92, dtype=np.float64)

    for name, arr in (
        ("paw_x", xs),
        ("paw_y", ys),
        ("paw_likelihood", lik),
        ("snout_x", snout_x),
        ("snout_y", snout_y),
        ("snout_likelihood", snout_lik),
    ):
        PyramidBuilder(cache_dir, name).build_and_save(times, arr)

    schema = PoseSchema(
        points=(
            PosePoint(individual="", bodypart="paw", axes=("x", "y"), has_likelihood=True),
            PosePoint(individual="", bodypart="snout", axes=("x", "y"), has_likelihood=True),
        ),
    )
    return cache_dir, schema


def test_find_suspects_and_jump_actions_navigate_low_confidence_and_jumps(
    qtbot, tmp_path: Path
) -> None:
    cache_dir, schema = _build_pose_cache(tmp_path)
    tmap = TimeMap(offset=0.0, drift_ms_per_hour=0.0)
    suspects = find_suspects_in_cache("pose.csv", cache_dir, schema, tmap, threshold=0.3)
    indices = [s.sample_index for s in suspects]
    assert 10 in indices  # peak of low-confidence dip
    assert 25 in indices  # abrupt 95 px jump

    window = MainWindow()
    qtbot.addWidget(window)
    assert not window._act_next_suspect.isEnabled()
    assert not window._act_prev_suspect.isEnabled()

    window.clock.set_bounds(0.0, 2.0)
    window._pose_schemas["pose.csv"] = schema
    window._pose_cache_dirs["pose.csv"] = cache_dir
    window._refresh_action_availability()
    assert window._act_next_suspect.isEnabled()
    assert window._act_prev_suspect.isEnabled()

    window.player.seek(0.0, exact=True)
    jump_suspect_frame(window, 1)
    qtbot.waitUntil(lambda: abs(window.clock.state.t - 0.50) < 1e-3, timeout=3000)

    jump_suspect_frame(window, 1)
    qtbot.waitUntil(lambda: abs(window.clock.state.t - 1.25) < 1e-3, timeout=3000)

    jump_suspect_frame(window, -1)
    qtbot.waitUntil(lambda: abs(window.clock.state.t - 0.50) < 1e-3, timeout=3000)


def test_pose_overlay_painting_confidence_trails_skeleton_loupe_and_epipolar(
    qtbot, tmp_path: Path
) -> None:
    cache_dir, _schema = _build_pose_cache(tmp_path)
    tmap = TimeMap()
    rx_paw = MappedChannelReader(PyramidReader(cache_dir, "paw_x"), tmap, source_id="pose.csv")
    ry_paw = MappedChannelReader(PyramidReader(cache_dir, "paw_y"), tmap, source_id="pose.csv")
    rl_paw = MappedChannelReader(
        PyramidReader(cache_dir, "paw_likelihood"), tmap, source_id="pose.csv"
    )
    rx_snout = MappedChannelReader(PyramidReader(cache_dir, "snout_x"), tmap, source_id="pose.csv")
    ry_snout = MappedChannelReader(PyramidReader(cache_dir, "snout_y"), tmap, source_id="pose.csv")

    pane = VideoPane()
    qtbot.addWidget(pane)
    pane.resize(400, 300)
    frame = QImage(320, 240, QImage.Format.Format_RGB888)
    frame.fill(QColor(25, 30, 35))
    pane.surface._image = frame

    track = OverlayTrack(
        label="DLC",
        points={"paw": (rx_paw, ry_paw), "snout": (rx_snout, ry_snout)},
        likelihood={"paw": rl_paw},
        edges=(("paw", "snout"),),
    )
    canvas: PaintCanvas = pane.paint_canvas
    canvas.resize(400, 300)
    canvas.set_tracks([track])
    canvas.set_trails_visible(True)
    canvas.set_skeleton_2d_visible(True)
    canvas.set_confidence_visible(True)
    canvas.set_loupe_visible(True)
    canvas.set_epipolar_visible(True)
    canvas.set_epipolar_source(
        lambda _t: [("paw", np.array([[10.0, 20.0], [150.0, 120.0], [290.0, 210.0]]))]
    )

    # Frame 10 has paw likelihood 0.08 (< 0.30 threshold) and 10 frames of trail history
    canvas.update_time(0.50)
    canvas.set_place_mode(True)
    canvas._loupe_video_xy = (80.0, 90.0)
    rendered = canvas.grab()
    assert not rendered.isNull()

    # Exercise right-half cursor loupe placement + multi-animal edge inference directly
    img = QImage(320, 240, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    painter = QPainter(img)
    try:
        assert style_point_by_confidence(
            painter, QColor(0, 255, 255), 0.1, 0.3, enabled=True, is_ensemble=True
        )
        assert not style_point_by_confidence(
            painter, QColor(0, 255, 255), 0.9, 0.3, enabled=True, is_ensemble=True
        )
        pts = [
            ResolvedPoint("mouse1_nose", 30.0, 40.0, (0, 255, 255), PointKey("s", "a", 5), False),
            ResolvedPoint("mouse1_tail", 60.0, 75.0, (255, 180, 0), PointKey("s", "b", 5), False),
            ResolvedPoint("mouse2_nose", 200.0, 140.0, (0, 255, 120), PointKey("s", "c", 5), False),
            ResolvedPoint(
                "mouse2_tail", 230.0, 170.0, (255, 90, 190), PointKey("s", "d", 5), False
            ),
        ]
        inferred = infer_2d_edges(pts)
        assert len(inferred) == 2
        draw_2d_skeleton(painter, pts, (), 1.0, 0.0, 0.0)
        draw_motion_trails(painter, track, canvas._resolve(track), 1.0, 0.0, 0.0, 8)
        draw_epipolar_guides(
            painter, [("paw", np.array([[10.0, 10.0], [200.0, 160.0]]))], 1.0, 0.0, 0.0
        )
        draw_magnifier_loupe(painter, frame, (260.0, 120.0), 320, 240, 1.0, 0.0, 0.0)
    finally:
        painter.end()

    for reader in (rx_paw, ry_paw, rl_paw, rx_snout, ry_snout):
        reader.source_reader.close()


def test_epipolar_guides_for_marker_placement_and_active_drag(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    cam_front = "/tmp/Front.mp4"
    cam_left = "/tmp/Left.mp4"
    window._calibration_state = CalibrationState(
        path=Path("calibration.toml"),
        cameras={cam_front: CAMERAS["Front"], cam_left: CAMERAS["Left"]},
    )
    truth = np.array([10.0, -25.0, 95.0])
    click_front = tuple(CAMERAS["Front"].project(truth)[0])
    window._marker_placement = MarkerPlacement(
        name="bar_tip", frame=0, clicks={cam_front: click_front}
    )

    guides_left = epipolar_guides_for(window, cam_left, 0.0)
    assert len(guides_left) == 1
    assert guides_left[0][0] == "bar_tip"
    assert _point_to_polyline_distance(CAMERAS["Left"].project(truth)[0], guides_left[0][1]) < 0.3
    assert epipolar_guides_for(window, cam_front, 0.0) == []
