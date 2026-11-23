"""Prop labels share a reference frame across staggered camera exposures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtGui import QImage
from shiboken6 import isValid

from avialsync.core.physical_props import (
    BallProp,
    BallSurface,
    BallVisualFrame,
    BeltProp,
    BeltTrack,
    BeltVisualFrame,
    LadderPoint,
    StepClick,
)
from avialsync.core.timeline import TimeMap
from avialsync.core.wheel import EncoderBinding, Wheel, WheelSpec
from avialsync.core.wheel_fit import fit_wheel
from avialsync.ui.controllers import calibration_controller, wheel_controller, wheel_display
from avialsync.ui.controllers.wheel_state import RotationPreview
from avialsync.ui.main_window import MainWindow
from avialsync.ui.video_pane import VideoPane
from tests.wheel_fixture import CAMERAS, TRUTH, clicks_for
from tests.wheel_window import FRAME, start_placing


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path: Path) -> Iterator[MainWindow]:
    """Real panes and frame lookup, with synthetic timestamps and no decoder IO."""
    monkeypatch.setattr(VideoPane, "open", lambda _self, _path: None)
    win = MainWindow()
    qtbot.addWidget(win)
    times = np.arange(30, dtype=np.float64) / 30.0
    cameras = {}
    for index, (name, model) in enumerate(CAMERAS.items()):
        path = str(tmp_path / f"{name}.mp4")
        pane = win.video_grid.add_pane(path)
        pane.set_frame_times(times)
        pane.time_map = TimeMap(offset=index * 0.005)
        win._video_frame_times[path] = times
        cameras[path] = model
    win._calibration_state = calibration_controller.CalibrationState(
        path=tmp_path / "calibration.toml", cameras=cameras
    )
    win.clock.set_bounds(0.0, float(times[-1]))
    win.clock.seek(float(times[FRAME]))
    win.resize(1800, 1000)
    win.show()
    yield win
    if isValid(win):
        win.close()


def _present(window: MainWindow) -> None:
    """Deliver each selected frame's own presentation time to its overlay."""
    for pane in window.video_grid.panes:
        _index, pts = pane.frame_record_at(window.clock.state.t)
        pane.surface.set_frame(np.zeros((1024, 1280, 3), dtype=np.uint8))
        pane._update_osd(pts, 30.0)


def test_prop_overlay_callbacks_follow_saved_props_and_unfinished_placement(
    window: MainWindow,
) -> None:
    """A session without props must keep the no-overlay repaint fast path."""
    canvases = [pane.paint_canvas for pane in window.video_grid.panes]
    assert all(canvas._props is None for canvas in canvases)

    window.props_app.start_belt_placement("side")
    assert all(canvas._props is not None for canvas in canvases)
    window.props_app.cancel_step()
    assert all(canvas._props is None for canvas in canvases)

    belt = BeltProp("belt", BeltTrack(((0.0, 0.0, 70.0), (25.0, 0.0, 70.0)), closed=False))
    window.props_app.store.set(belt.name, belt)
    assert all(canvas._props is not None for canvas in canvases)
    window.props_app.store.set(belt.name, None)
    assert all(canvas._props is None for canvas in canvases)


def test_wheel_click_labels_paint_in_every_staggered_camera(
    window: MainWindow, monkeypatch
) -> None:
    start_placing(window, monkeypatch)
    click = clicks_for([0])[0]
    paths = window.video_grid.pane_paths()
    for path, (_camera, x, y) in zip(paths, click.views, strict=True):
        window.video_grid.marker_clicked.emit(path, x, y)
    _present(window)
    placement = window.wheel_state.placement
    assert placement is not None and placement.count(0) == 3
    labels: list[str] = []
    monkeypatch.setattr(
        "avialsync.ui.label_layout.LabelLayout.label",
        lambda _self, _anchor, text, _color, **_kwargs: labels.append(text),
    )

    for pane in window.video_grid.panes:
        labels.clear()
        canvas = pane.paint_canvas
        canvas.setFixedSize(640, 512)
        drawing = canvas._wheel(canvas.t)
        assert drawing is not None and drawing.clicks, (
            pane._label_text,
            canvas.t,
            window.clock.state.t,
            placement.clicks,
        )
        image = QImage(canvas.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        canvas.render(image)
        assert "1a" in labels, f"missing real-click label in {pane._label_text}"

    window.wheel_panel._undo.click()
    placement = window.wheel_state.placement
    assert placement is not None and placement.count(0) == 2
    assert len(placement.estimates) == 1, "undo restores a projection, never a real click"


def test_wheel_click_labels_leave_and_return_with_the_reference_frame(
    window: MainWindow, monkeypatch
) -> None:
    start_placing(window, monkeypatch)
    for path, (_camera, x, y) in zip(
        window.video_grid.pane_paths(), clicks_for([0])[0].views, strict=True
    ):
        assert wheel_controller.on_clicked(window, path, x, y)
    for frame, visible in ((FRAME + 1, False), (FRAME, True)):
        window.clock.seek(frame / 30.0)
        _present(window)
        for pane in window.video_grid.panes:
            drawing = pane.paint_canvas._wheel(pane.paint_canvas.t)
            assert bool(drawing and drawing.clicks) == visible


def test_a_saved_unbound_wheel_draws_in_every_camera_on_its_reference_frame(
    window: MainWindow,
) -> None:
    spec = WheelSpec("wheel", 36)
    clicks = clicks_for([0, 1])
    window.props_app.store.set(
        "wheel", Wheel(spec, FRAME, clicks, fit_wheel(spec, clicks, CAMERAS))
    )
    wheel_display.refresh(window)
    _present(window)

    for pane in window.video_grid.panes:
        drawing = pane.paint_canvas._wheel(pane.paint_canvas.t)
        assert drawing is not None and drawing.bars


def test_rotation_uses_shared_evidence_and_each_cameras_own_exposure(
    window: MainWindow, monkeypatch
) -> None:
    spec = WheelSpec("wheel", 36)
    clicks = clicks_for([0, 1])
    wheel = Wheel(
        spec,
        FRAME,
        clicks,
        fit_wheel(spec, clicks, CAMERAS),
        binding=EncoderBinding("encoder.csv", "angle", 0.0),
    )
    monkeypatch.setattr(wheel_display, "sample", lambda _w, _channel, t: 360.0 * t)
    window.wheel_state.rotation_preview[wheel.name] = RotationPreview(FRAME, 2.0)
    _present(window)

    for path, pane in zip(window.video_grid.pane_paths(), window.video_grid.panes, strict=True):
        exposure = pane.paint_canvas.t
        aligned = wheel_display.alignment(window, wheel, exposure, path)
        assert aligned is not None and aligned[0] == FRAME
        assert aligned[2] == pytest.approx(360.0 * (exposure - FRAME / 30.0))
        assert aligned[3] == 2.0, "every camera uses the adjustment for the shared frame"


@pytest.mark.parametrize("kind", ["belt", "ball"])
def test_saved_visual_prop_clicks_keep_their_labels_in_every_camera(
    window: MainWindow, kind: str
) -> None:
    clicks = []
    for name, model in CAMERAS.items():
        x, y = model.project(np.asarray([TRUTH.bar_ends()[0, 0]]))[0]
        clicks.append(StepClick(name, FRAME, float(x), float(y)))
    point = LadderPoint(clicks=tuple(clicks))
    prop: BeltProp | BallProp
    if kind == "belt":
        prop = BeltProp(
            "belt",
            BeltTrack(((-25.0, 0.0, 100.0), (25.0, 0.0, 100.0)), closed=False),
            travel_direction=(1.0, 0.0, 0.0),
            visual_reference_frame=FRAME,
            visual_frames=(BeltVisualFrame(FRAME, point),),
        )
        label = "mark"
    else:
        prop = BallProp(
            "ball",
            BallSurface((0.0, 0.0, 0.0), 100.0),
            visual_reference_frame=FRAME,
            visual_frames=(BallVisualFrame(FRAME, (point, LadderPoint(), LadderPoint())),),
        )
        label = "A"
    window.props_app.store.set(prop.name, prop)
    _present(window)

    for pane in window.video_grid.panes:
        drawings = pane.paint_canvas._props(pane.paint_canvas.t)
        assert any(
            name == label and pixels and pixels[0] is not None and pixels[0][2]
            for name, pixels, _closed in drawings
        ), "a saved real click must stay solid and labelled in its own camera"


def test_channel_bound_belt_and_ball_sample_each_cameras_own_exposure(
    window: MainWindow, tmp_path: Path
) -> None:
    """Staggered cameras draw channel-driven belt/ball marks at their own exposure timestamp."""
    from types import SimpleNamespace

    from avialsync.core.channel_reader import MappedChannelReader
    from avialsync.core.physical_props import BeltBinding
    from avialsync.core.pyramid import PyramidBuilder, PyramidReader
    from avialsync.ui import prop_motion

    sensor_cache = tmp_path / "belt_sensor"
    sensor_cache.mkdir()
    times = np.linspace(0.0, 2.0, 201, dtype=np.float64)
    # 100 units/s so a 5 ms camera stagger moves the mark by 0.5 units along X.
    PyramidBuilder(sensor_cache, "dist").build_and_save(times, times * 100.0)
    window._sensor_cache_dirs["belt_sensor"] = sensor_cache
    window.plot_pane.channels.append(
        SimpleNamespace(
            reader=MappedChannelReader(
                PyramidReader(sensor_cache, "dist"), TimeMap(), "belt_sensor"
            )
        )
    )
    belt = BeltProp(
        "staggered_belt",
        BeltTrack(((0.0, 0.0, 70.0), (200.0, 0.0, 70.0)), closed=False),
        travel_direction=(1.0, 0.0, 0.0),
        binding=BeltBinding("belt_sensor", "dist", 0, 0.0, 0.0, 1.0),
    )
    window.props_app.store.set(belt.name, belt)
    _present(window)

    seen_xs: list[float] = []
    for path, pane in zip(window.video_grid.pane_paths(), window.video_grid.panes, strict=True):
        drawings = window.props_app.camera_drawing(path, pane.paint_canvas.t)
        mark_drawings = [pts for name, pts, _c in drawings if name == "mark"]
        assert len(mark_drawings) == 1 and mark_drawings[0][0] is not None
        px, py, _solid = mark_drawings[0][0]
        seen_xs.append(px)
        # Drawn mark in each staggered camera agrees to 0.0 px with check_click on that camera!
        chk = prop_motion.check_click(window, belt, path, px, py)
        assert chk is not None and chk.residual_px == pytest.approx(0.0, abs=1e-6)
    # Staggered camera exposures yield distinct mark positions rather than cloning camera 0's time.
    assert len({round(v, 4) for v in seen_xs}) == len(seen_xs)
