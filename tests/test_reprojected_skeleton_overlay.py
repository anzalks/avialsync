"""Tests for 3D-to-2D reprojection skeleton overlay, layer independence, and skeleton colors."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.pyramid import PyramidBuilder, PyramidReader
from avialsync.core.timeline import TimeMap
from avialsync.ui import recovery
from avialsync.ui.cvd import DEFICIENCIES, perceptual_distance, simulate
from avialsync.ui.main_window import MainWindow
from avialsync.ui.pose_overlay_extras import (
    DUAL_REPROJECTION_SKELETON_COLOR,
    SOLO_SKELETON_COLOR,
    skeleton_comparison_colors,
)
from avialsync.ui.tracking_colors import REGISTRY, color_for_point, register_points
from avialsync.ui.video_overlay import OverlayTrack, PaintCanvas
from tests.test_palette_cvd import REQUIRED_SEPARATION


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    folder = tmp_path / "appdata"
    folder.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: folder)
    REGISTRY.reset()
    yield folder
    REGISTRY.reset()


def _make_canvas(qtbot, size: tuple[int, int] = (200, 200)) -> tuple[QWidget, PaintCanvas]:
    host = QWidget()
    host.video_size = size  # type: ignore[attr-defined]
    qtbot.addWidget(host)
    canvas = PaintCanvas(host)
    canvas.resize(*size)
    return host, canvas


def _render_opaque(canvas: PaintCanvas) -> QImage:
    image = QImage(canvas.width(), canvas.height(), QImage.Format.Format_RGB32)
    image.fill(QColor(20, 22, 26))
    canvas.render(image)
    return image


def _build_two_point_track(
    tmp_path: Path,
    p1: tuple[float, float],
    p2: tuple[float, float],
) -> tuple[OverlayTrack, list[MappedChannelReader]]:
    cache_dir = tmp_path / "raw2d_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    times = np.array([0.0, 0.1], dtype=np.float64)
    readers: list[MappedChannelReader] = []
    for name, (x, y) in (("nose", p1), ("tail", p2)):
        PyramidBuilder(cache_dir, f"{name}_x").build_and_save(times, np.array([x, x]))
        PyramidBuilder(cache_dir, f"{name}_y").build_and_save(times, np.array([y, y]))
    tmap = TimeMap()
    rx_n = MappedChannelReader(PyramidReader(cache_dir, "nose_x"), tmap, "raw.csv")
    ry_n = MappedChannelReader(PyramidReader(cache_dir, "nose_y"), tmap, "raw.csv")
    rx_t = MappedChannelReader(PyramidReader(cache_dir, "tail_x"), tmap, "raw.csv")
    ry_t = MappedChannelReader(PyramidReader(cache_dir, "tail_y"), tmap, "raw.csv")
    readers.extend([rx_n, ry_n, rx_t, ry_t])
    track = OverlayTrack(
        label="DLC",
        points={"nose": (rx_n, ry_n), "tail": (rx_t, ry_t)},
        is_ensemble=False,
        edges=(("nose", "tail"),),
    )
    return track, readers


def _is_whiteish(color: QColor) -> bool:
    return (
        color.red() > 180
        and color.green() > 180
        and color.blue() > 180
        and abs(color.blue() - color.red()) < 15
    )


def _is_pastel_blue(color: QColor) -> bool:
    return color.blue() > 175 and (color.blue() - color.red()) > 55 and color.green() > 130


def _matches_rgb(color: QColor, expected: tuple[int, int, int], tol: int = 35) -> bool:
    return (
        abs(color.red() - expected[0]) <= tol
        and abs(color.green() - expected[1]) <= tol
        and abs(color.blue() - expected[2]) <= tol
    )


# ── Skeleton palette & CVD validation ────────────────────────────────


def test_solo_and_dual_skeleton_colors_survive_cvd_simulation() -> None:
    assert skeleton_comparison_colors(raw_active=True, reprojection_active=False) == (
        SOLO_SKELETON_COLOR,
        SOLO_SKELETON_COLOR,
    )
    assert skeleton_comparison_colors(raw_active=False, reprojection_active=True) == (
        SOLO_SKELETON_COLOR,
        SOLO_SKELETON_COLOR,
    )
    assert skeleton_comparison_colors(raw_active=True, reprojection_active=True) == (
        SOLO_SKELETON_COLOR,
        DUAL_REPROJECTION_SKELETON_COLOR,
    )
    assert perceptual_distance(SOLO_SKELETON_COLOR, DUAL_REPROJECTION_SKELETON_COLOR) > 0.25
    for deficiency in DEFICIENCIES:
        sep = perceptual_distance(
            simulate(SOLO_SKELETON_COLOR, deficiency),
            simulate(DUAL_REPROJECTION_SKELETON_COLOR, deficiency),
        )
        assert sep >= REQUIRED_SEPARATION * 3, f"{deficiency} separation too low: {sep:.3f}"


# ── Marker sync with 3D viewer + solo-white / dual-pastel skeletons ──


def test_markers_keep_3d_viewer_pastel_palette_while_solo_raw_skeleton_is_white(
    qtbot, tmp_path: Path
) -> None:
    register_points(["nose", "tail"])
    nose_rgb = color_for_point("nose")
    tail_rgb = color_for_point("tail")
    assert nose_rgb != tail_rgb

    _host, canvas = _make_canvas(qtbot)
    track, readers = _build_two_point_track(tmp_path, (40.0, 60.0), (160.0, 60.0))
    canvas.set_tracks([track])
    canvas.set_points_visible(True)
    canvas.set_skeleton_2d_visible(True)

    img = _render_opaque(canvas)
    assert _matches_rgb(img.pixelColor(40, 60), nose_rgb), "nose keeps 3D-synced pastel color"
    assert _matches_rgb(img.pixelColor(160, 60), tail_rgb), "tail keeps 3D-synced pastel color"
    assert _is_whiteish(img.pixelColor(100, 60)), "solo raw 2D skeleton renders white"

    # Hide markers while keeping 2D skeleton ON -> skeleton still renders white!
    canvas.set_points_visible(False)
    img_skel_only = _render_opaque(canvas)
    assert _is_whiteish(img_skel_only.pixelColor(100, 60)), "2D skeleton draws without points"

    for r in readers:
        r.source_reader.close()


def test_solo_reprojection_keeps_3d_synced_marker_colors_and_draws_white_skeleton(
    qtbot,
) -> None:
    register_points(["nose", "tail"])
    nose_rgb = color_for_point("nose")
    tail_rgb = color_for_point("tail")

    _host, canvas = _make_canvas(qtbot)
    canvas.set_points_visible(False)
    canvas.set_skeleton_2d_visible(False)
    canvas.set_reprojection_source(lambda _t: [("nose", 40.0, 120.0), ("tail", 160.0, 120.0)])
    canvas.set_skeleton_edges_source(lambda: [("nose", "tail")])
    canvas.set_reprojection_visible(True)
    canvas.set_reprojection_skeleton_visible(True)

    img = _render_opaque(canvas)
    assert _matches_rgb(img.pixelColor(40, 120), nose_rgb), (
        "reprojected nose cross matches 3D viewer color"
    )
    assert _matches_rgb(img.pixelColor(160, 120), tail_rgb), (
        "reprojected tail cross matches 3D viewer color"
    )
    assert _is_whiteish(img.pixelColor(100, 120)), (
        "solo reprojected skeleton is white when raw tracking is off"
    )

    # Hide reprojected crosses while keeping reprojection skeleton ON -> limb still draws white!
    canvas.set_reprojection_visible(False)
    img_skel_only = _render_opaque(canvas)
    assert _is_whiteish(img_skel_only.pixelColor(100, 120)), (
        "reprojection skeleton draws without crosses"
    )


def test_dual_overlay_keeps_marker_colors_and_splits_skeletons_into_white_and_pastel_blue(
    qtbot, tmp_path: Path
) -> None:
    register_points(["nose", "tail"])
    nose_rgb = color_for_point("nose")
    tail_rgb = color_for_point("tail")

    _host, canvas = _make_canvas(qtbot)
    track, readers = _build_two_point_track(tmp_path, (40.0, 50.0), (160.0, 50.0))
    canvas.set_tracks([track])
    canvas.set_reprojection_source(lambda _t: [("nose", 40.0, 140.0), ("tail", 160.0, 140.0)])
    canvas.set_skeleton_edges_source(lambda: [("nose", "tail")])

    canvas.set_points_visible(True)
    canvas.set_skeleton_2d_visible(True)
    canvas.set_reprojection_visible(True)
    canvas.set_reprojection_skeleton_visible(True)

    img = _render_opaque(canvas)
    # Both raw dots and reprojected crosses stay synced with the 3D viewer per body part!
    assert _matches_rgb(img.pixelColor(40, 50), nose_rgb)
    assert _matches_rgb(img.pixelColor(160, 50), tail_rgb)
    assert _matches_rgb(img.pixelColor(40, 140), nose_rgb)
    assert _matches_rgb(img.pixelColor(160, 140), tail_rgb)

    # Raw 2D skeleton stays white (solid); reprojected skeleton uses pastel sky blue (dashed).
    assert _is_whiteish(img.pixelColor(100, 50)), "raw 2D skeleton stays white in dual mode"
    assert any(_is_pastel_blue(img.pixelColor(x, 140)) for x in range(85, 116)), (
        "dashed reprojected skeleton switches to pastel sky blue in dual mode"
    )

    for r in readers:
        r.source_reader.close()


@pytest.mark.parametrize(
    ("reproj_pts", "reproj_skel", "expected"),
    [
        (True, False, True),
        (False, True, True),
        (False, False, False),
    ],
)
def test_reprojection_only_overlays_repaint_on_time_advance(
    qtbot,
    monkeypatch: pytest.MonkeyPatch,
    reproj_pts: bool,
    reproj_skel: bool,
    expected: bool,
) -> None:
    _host, canvas = _make_canvas(qtbot)
    canvas.set_reprojection_source(lambda _t: [("nose", 50.0, 50.0), ("tail", 90.0, 90.0)])
    canvas.set_reprojection_visible(reproj_pts)
    canvas.set_reprojection_skeleton_visible(reproj_skel)
    repaints: list[bool] = []
    monkeypatch.setattr(canvas, "update", lambda: repaints.append(True))

    canvas.update_time(0.25)
    assert bool(repaints) is expected


def test_window_wires_reprojection_skeleton_toggle_per_camera_undo_and_3d_sync(
    qapp: QApplication, qtbot
) -> None:
    win = MainWindow()
    qtbot.addWidget(win)
    try:
        assert "tracking.reprojection_skeleton" in win._overlay_actions
        assert win.overlay_state.is_visible("tracking.reprojection_skeleton") is False

        win._on_overlay_toggled("tracking.reprojection_skeleton", True)
        assert win.overlay_state.is_visible("tracking.reprojection_skeleton") is True
        assert win._overlay_actions["tracking.reprojection_skeleton"].isChecked() is True
        win.document.undo(win._mutations)
        assert win.overlay_state.is_visible("tracking.reprojection_skeleton") is False

        win._on_overlay_toggled("tracking.reprojection_skeleton", True, camera="/tmp/camA.mp4")
        assert win.overlay_state.is_visible("tracking.reprojection_skeleton", "/tmp/camA.mp4")
        assert not win.overlay_state.is_visible("tracking.reprojection_skeleton", "/tmp/camB.mp4")

        assert win.video_grid._skeleton_edges_source is not None
        win.tracking_3d_pane.set_skeleton([("head", "spine")])
        assert tuple(win.video_grid._skeleton_edges_source()) == (("head", "spine"),)
    finally:
        if isValid(win):
            win.close()
