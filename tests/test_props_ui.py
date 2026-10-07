"""The Props inspector retains irregular clicked ladder evidence end to end."""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.physical_props import (
    BallProp,
    BallSurface,
    BeltProp,
    BeltTrack,
    Ladder,
    LadderPoint,
    LadderStep,
    StepClick,
    UnitQuaternion,
)
from avialsync.core.prop_file import read_props, write_ladder
from avialsync.core.visual_prop_tracking import ball_visual_state, belt_visual_state
from avialsync.engine import prop_file_worker
from avialsync.engine.prop_file_worker import PropFileReadWorker, PropFileWriteWorker
from avialsync.ui.main_window import MainWindow
from avialsync.ui.prop_overlay import UNNAMED
from tests.wheel_fixture import CAMERAS
from tests.wheel_window import VIDEOS, build_window


@pytest.fixture
def window(qapp: QApplication, qtbot, monkeypatch, tmp_path: Path) -> MainWindow:
    frame = {"now": 7, "t": 0.0}
    win = build_window(qtbot, monkeypatch, tmp_path / "pose-3d", frame)
    win.show()
    yield win
    if isValid(win):
        win.close()


class _InertItem:
    """A plot item that is never on screen, for rows that only carry a reader."""

    def isVisible(self) -> bool:  # noqa: N802
        return False

    def minimumHeight(self) -> int:  # noqa: N802
        return 0

    def maximumHeight(self) -> int:  # noqa: N802
        return 0

    def __getattr__(self, _name: str):
        return lambda *_args, **_kwargs: None


def _hidden_row(reader: object) -> SimpleNamespace:
    """A plot row stand-in that survives a plot-pane resize (D-182 layouts resize it).

    Hidden, with inert graphics items, so ``enforce_channel_visibility`` has
    nothing to do; the props code under test reads only ``reader``.
    """
    return SimpleNamespace(
        reader=reader,
        visible=False,
        row_height=0,
        plot_item=_InertItem(),
        close_proxy=_InertItem(),
    )


def _fake_panes(window: MainWindow, monkeypatch) -> None:
    paths = list(VIDEOS.values())
    pane = SimpleNamespace(
        frame_record_at=lambda _t: (7, 0.0),
        time_map=SimpleNamespace(to_master=lambda t: t),
        paint_canvas=SimpleNamespace(update=lambda: None),
        set_marker_place_mode=lambda _enabled: None,
        close=lambda: None,
        deleteLater=lambda: None,
    )
    monkeypatch.setattr(window.video_grid, "pane_paths", lambda: paths)
    monkeypatch.setattr(window.video_grid, "panes", [pane for _ in paths])


def test_prop_geometry_shows_3d_pane_without_pose_source(window: MainWindow) -> None:
    """A props-only recording must expose its reconstructed viewer geometry."""
    pane = window.tracking_3d_pane
    assert pane.isHidden()
    window.props_app.store.set("ladder", Ladder("ladder"))
    assert pane.isHidden(), "an empty ladder has no 3D scene"

    world = np.asarray((0.0, 0.0, 70.0))
    clicks = tuple(
        StepClick(camera, 7, *map(float, CAMERAS[camera].project(world)[0]))
        for camera in ("Front", "Left")
    )
    ladder = Ladder("ladder", (LadderStep("one", "Rung", (LadderPoint(clicks),)),))
    window.props_app.store.set("ladder", ladder)
    assert pane.isVisible()
    window.props_app.store.set("ladder", None)
    assert pane.isHidden()

    window.props_app.store.set(
        "belt", BeltProp("belt", BeltTrack(((0.0, 0.0, 70.0), (10.0, 0.0, 70.0))))
    )
    assert pane.isVisible()
    window.props_app.store.set("belt", None)
    assert pane.isHidden()

    window.props_app.store.set("ball", BallProp("ball", BallSurface((0.0, 0.0, 70.0), 5.0)))
    assert pane.isVisible()


def test_measured_belt_surface_is_saved_and_drawn_as_a_mesh(window: MainWindow) -> None:
    panel = window.props_app.panel
    assert panel is not None
    window.props_app.show("belt")
    panel.belt_geometry_mode.setCurrentIndex(panel.belt_geometry_mode.findData("path"))
    panel.name.setText("mesh belt")
    for point in ((0.0, 0.0, 70.0), (20.0, 0.0, 70.0)):
        for field, value in zip(panel.belt_point_fields, point, strict=True):
            field.setValue(value)
        panel.belt_add_vertex.click()
    panel.belt_width.setValue(8.0)
    panel.belt_normal_fields[2].setValue(1.0)
    panel.save_belt.click()

    belt = window.props_app.store.get("mesh belt")
    assert isinstance(belt, BeltProp) and belt.surface_width == 8.0
    assert len(belt.surface_quads()) == 1
    camera = window.props_app.camera_drawing(VIDEOS["Front"], 0.0)
    assert any(not label and closed and len(points) == 4 for label, points, closed in camera)
    scene = window.props_app.scene_steps(0.0)
    assert any(not label and closed and len(points) == 4 for label, points, closed in scene)


def test_two_roller_belt_editor_saves_measured_geometry_and_viewer_mesh(window: MainWindow) -> None:
    panel = window.props_app.panel
    assert panel is not None
    window.props_app.show("belt")
    assert panel.belt_geometry_mode.currentData() == "rollers"
    panel.name.setText("treadmill")
    for fields, values in (
        (panel.belt_first_fields, (-30.0, 0.0, 60.0)),
        (panel.belt_second_fields, (30.0, 0.0, 60.0)),
    ):
        for field, value in zip(fields, values, strict=True):
            field.setValue(value)
    panel.belt_radius.setValue(10.0)
    panel.belt_width.setValue(16.0)
    panel.belt_normal_fields[2].setValue(1.0)
    panel.belt_direction_fields[0].setValue(1.0)
    panel.save_belt.click()
    belt = window.props_app.store.get("treadmill")
    assert isinstance(belt, BeltProp) and belt.rollers is not None, panel.status.text()
    assert belt.rollers.run_length == pytest.approx(60.0)
    assert len(belt.surface_quads()) > 20
    assert any(
        not label and closed and len(points) == 4
        for label, points, closed in window.props_app.camera_drawing(VIDEOS["Front"], 0.0)
    )
    panel.select_prop("treadmill", "belt")
    assert panel.belt_geometry_mode.currentData() == "rollers"
    assert panel.belt_radius.value() == 10.0


def test_visual_only_belt_and_ball_tracks_are_clicked_and_displayed(
    window: MainWindow, monkeypatch
) -> None:
    """The one Props inspector records visual motion without sensor channels."""
    panel = window.props_app.panel
    assert panel is not None
    _fake_panes(window, monkeypatch)
    moment = {"frame": 7, "time": 0.0}
    for pane in window.video_grid.panes:
        pane.frame_record_at = lambda _t: (moment["frame"], moment["time"])
    monkeypatch.setattr(
        "avialsync.ui.props_app.wheel_display.frame_and_time",
        lambda _window, _t: (moment["frame"], moment["time"]),
    )
    monkeypatch.setattr(
        "avialsync.ui.props_app.wheel_display.camera_models", lambda _window: CAMERAS
    )

    def click_mark(world: tuple[float, float, float]) -> None:
        for camera in ("Front", "Left"):
            xy = CAMERAS[camera].project(np.asarray(world))[0]
            assert window.props_app.on_clicked(VIDEOS[camera], float(xy[0]), float(xy[1]))

    window.props_app.show("belt")
    panel.belt_geometry_mode.setCurrentIndex(panel.belt_geometry_mode.findData("path"))
    panel.name.setText("visual belt")
    for vertex in ((0.0, 0.0, 70.0), (10.0, 0.0, 70.0)):
        for field, value in zip(panel.belt_point_fields, vertex, strict=True):
            field.setValue(value)
        panel.belt_add_vertex.click()
    panel.belt_direction_fields[0].setValue(1.0)
    panel.save_belt.click()
    assert panel.track_belt.isEnabled()
    panel.track_belt.click()
    moment.update(frame=-1)
    assert window.props_app.on_clicked(VIDEOS["Front"], 100.0, 100.0)
    assert "Show a video frame" in panel.status.text()
    moment.update(frame=7)
    click_mark((2.0, 0.0, 70.0))
    moment.update(frame=8, time=1.0)
    click_mark((7.0, 0.0, 70.0))
    belt = window.props_app.store.get("visual belt")
    assert isinstance(belt, BeltProp) and belt.binding is None
    assert len(belt.visual_frames) == 2
    panel.belt_vertices.setCurrentRow(1)
    panel.belt_point_fields[1].setValue(30.0)
    panel.belt_update_vertex.click()
    panel.save_belt.click()
    changed_belt = window.props_app.store.get("visual belt")
    assert isinstance(changed_belt, BeltProp)
    assert changed_belt.visual_frames == belt.visual_frames
    assert belt_visual_state(changed_belt, 8, CAMERAS) is None
    assert "off the declared belt path" in panel.status.text()
    click_mark((7.0, 0.0, 70.0))
    assert "off the declared belt path" in panel.status.text()
    panel.belt_vertices.setCurrentRow(1)
    panel.belt_point_fields[1].setValue(0.0)
    panel.belt_update_vertex.click()
    panel.save_belt.click()
    assert belt_visual_state(window.props_app.store.get("visual belt"), 8, CAMERAS) is not None
    assert any(
        label == "mark" and pixels[0] is not None and pixels[0][2]
        for label, pixels, _closed in window.props_app.camera_drawing(VIDEOS["Front"], 1.0)
    ), "the clicked mark is drawn solid"
    assert any(label == "mark" for label, *_ in window.props_app.scene_steps(1.0))
    moment.update(frame=9, time=2.0)
    assert not any(
        label == "mark"
        for label, _pixels, _closed in window.props_app.camera_drawing(VIDEOS["Front"], 2.0)
    )
    panel.track_belt.click()

    panel.kind.setCurrentIndex(panel.kind.findData("ball"))
    panel.name.setText("visual ball")
    panel.ball_centre_fields[2].setValue(70.0)
    panel.ball_radius.setValue(5.0)
    panel.save_ball.click()
    panel.track_ball.click()
    reference_marks = ((5.0, 0.0, 70.0), (0.0, 5.0, 70.0), (0.0, 0.0, 75.0))
    later_marks = ((0.0, 5.0, 70.0), (-5.0, 0.0, 70.0), (0.0, 0.0, 75.0))
    for frame, marks in ((7, reference_marks), (8, later_marks)):
        moment.update(frame=frame, time=float(frame - 7))
        for index, world in enumerate(marks):
            panel.ball_visual_mark.setCurrentIndex(index)
            click_mark(world)
    ball = window.props_app.store.get("visual ball")
    assert isinstance(ball, BallProp) and ball.binding is None
    assert len(ball.visual_frames) == 2
    panel.ball_radius.setValue(50.0)
    panel.save_ball.click()
    changed_ball = window.props_app.store.get("visual ball")
    assert isinstance(changed_ball, BallProp)
    assert changed_ball.visual_frames == ball.visual_frames
    assert ball_visual_state(changed_ball, 8, CAMERAS) is None
    assert "off the declared sphere" in panel.status.text()
    panel.kind.setCurrentIndex(panel.kind.findData("belt"))
    panel.kind.setCurrentIndex(panel.kind.findData("ball"))
    assert "off the declared sphere" in panel.status.text()
    panel.ball_visual_mark.setCurrentIndex(0)
    click_mark(later_marks[0])
    assert "off the declared sphere" in panel.status.text()
    panel.ball_radius.setValue(5.0)
    panel.save_ball.click()
    ball = window.props_app.store.get("visual ball")
    assert isinstance(ball, BallProp) and ball_visual_state(ball, 8, CAMERAS) is not None
    assert any(
        label == "A" and pixels[0] is not None and pixels[0][2]
        for label, pixels, _closed in window.props_app.camera_drawing(VIDEOS["Front"], 1.0)
    ), "the clicked ball mark is drawn solid"
    assert any(label == "A" for label, *_ in window.props_app.scene_steps(1.0))
    panel.clear_ball_visual.click()
    cleared = window.props_app.store.get("visual ball")
    assert isinstance(cleared, BallProp) and not cleared.visual_frames
    window.document.undo(window._mutations)
    assert window.props_app.store.get("visual ball") == ball


def test_belt_and_ball_bind_verify_and_persist_later_frame_evidence(
    window: MainWindow, monkeypatch, tmp_path: Path
) -> None:
    """The inspector's commands bind live rows and keep real check clicks."""
    panel = window.props_app.panel
    assert panel is not None
    _fake_panes(window, monkeypatch)
    pane = window.video_grid.panes[0]
    moment = {"frame": 7, "time": 0.0}
    pane.frame_record_at = lambda _t: (moment["frame"], moment["time"])
    monkeypatch.setattr(
        "avialsync.ui.props_app.wheel_display.frame_and_time",
        lambda _window, _t: (moment["frame"], moment["time"]),
    )
    window._sensor_cache_dirs.update({"sensor": Path("/cache/sensor"), "imu": Path("/cache/imu")})
    rotated = UnitQuaternion.about_axis((0.0, 0.0, 1.0), np.pi / 2)
    quaternion = (rotated.w, rotated.x, rotated.y, rotated.z)
    rows = []
    for channel, values, cache, source in [
        ("distance", (100.0, 102.0), "sensor", "sensor"),
        *(
            (name, (start, end), "imu", "imu")
            for name, start, end in zip(
                ("qw", "qx", "qy", "qz"), (1.0, 0.0, 0.0, 0.0), quaternion, strict=True
            )
        ),
    ]:
        reader = SimpleNamespace(
            source_id=source,
            channel_id=channel,
            cache_dir=Path(f"/cache/{cache}"),
            available_sample_at=lambda t, values=values: (int(t), values[int(t)]),
        )
        rows.append(_hidden_row(reader))
    monkeypatch.setattr(window.plot_pane, "channels", rows)
    window.props_app.show("belt")
    panel.name.setText("belt")
    panel.belt_geometry_mode.setCurrentIndex(panel.belt_geometry_mode.findData("path"))
    for vertex in ((0.0, 0.0, 70.0), (10.0, 0.0, 70.0)):
        for field, value in zip(panel.belt_point_fields, vertex, strict=True):
            field.setValue(value)
        panel.belt_add_vertex.click()
    panel.belt_direction_fields[0].setValue(1.0)
    panel.save_belt.click()
    panel.select_channel(panel.belt_channel, ("sensor", "distance"))
    assert panel.belt_channel.currentData() == ("sensor", "distance")
    panel.belt_reference_distance.setValue(5.0)
    panel.bind_belt.click()
    belt = window.props_app.store.get("belt")
    assert isinstance(belt, BeltProp) and belt.binding is not None, panel.status.text()
    assert belt.binding.reference_reading == 100.0
    moment.update(frame=8, time=1.0)
    panel.check_belt.click()
    xy = CAMERAS["Front"].project(np.asarray((7.0, 0.0, 70.0)))[0]
    window._on_marker_clicked(VIDEOS["Front"], float(xy[0]), float(xy[1]))
    belt = window.props_app.store.get("belt")
    assert isinstance(belt, BeltProp) and belt.binding is not None
    assert belt.binding.checks[0].residual_px == pytest.approx(0.0)
    assert belt.binding.checks[0].source_values == (102.0,)
    available = rows[0].reader.available_sample_at
    rows[0].reader.available_sample_at = lambda _t: None
    belt_drawings = window.props_app.camera_drawing(VIDEOS["Front"], 1.0)
    assert any(label == "belt" for label, *_ in belt_drawings)
    assert not any(label == "mark" for label, *_ in belt_drawings)
    rows[0].reader.available_sample_at = available

    moment.update(frame=7, time=0.0)
    panel.kind.setCurrentIndex(panel.kind.findData("ball"))
    panel.name.setText("ball")
    panel.ball_centre_fields[2].setValue(70.0)
    panel.ball_radius.setValue(2.0)
    panel.save_ball.click()
    for combo, channel in zip(panel.ball_channels, ("qw", "qx", "qy", "qz"), strict=True):
        panel.select_channel(combo, ("imu", channel))
    panel.bind_ball.click()
    ball = window.props_app.store.get("ball")
    assert isinstance(ball, BallProp) and ball.binding is not None
    assert ball.binding.reference_values == (1.0, 0.0, 0.0, 0.0)
    moment.update(frame=8, time=1.0)
    panel.check_ball.click()
    xy = CAMERAS["Front"].project(np.asarray((0.0, 2.0, 70.0)))[0]
    window._on_marker_clicked(VIDEOS["Front"], float(xy[0]), float(xy[1]))
    ball = window.props_app.store.get("ball")
    assert isinstance(ball, BallProp) and ball.binding is not None
    assert ball.binding.checks[0].residual_px == pytest.approx(0.0, abs=1e-8)
    assert ball.binding.checks[0].source_values == pytest.approx(quaternion)
    available = rows[-1].reader.available_sample_at
    rows[-1].reader.available_sample_at = lambda _t: None
    ball_drawings = window.props_app.camera_drawing(VIDEOS["Front"], 1.0)
    assert any(label == "ball" for label, *_ in ball_drawings)
    assert window.props_app._motion_at(ball, 8, 1.0) == ()
    rows[-1].reader.available_sample_at = available
    assert read_props(tmp_path / "pose-3d")[0] == [ball, belt]


def test_clicked_uneven_ladder_add_undo_reopen_and_draw(
    window: MainWindow, qtbot, monkeypatch, tmp_path: Path
) -> None:
    panel = window.props_app.panel
    assert panel is not None
    window._act_add_prop.trigger()
    assert window._left_tabs.currentWidget() is window.props_app.tab
    panel.name.setText("uneven ladder")
    panel.create_button.click()
    assert window.props_app.store.get("uneven ladder") is not None

    with monkeypatch.context() as patches:
        _fake_panes(window, patches)
        first, second = list(CAMERAS)[:2]
        xyz = np.asarray([[0.1, 0.2, 0.3]])
        panel.add_point.click()
        for camera in (first, second):
            x, y = CAMERAS[camera].project(xyz)[0]
            window._on_marker_clicked(VIDEOS[camera], float(x), float(y))
        panel.save_step.click()
        ladder = window.props_app.store.get("uneven ladder")
        assert ladder is not None and len(ladder.steps) == 1
        assert ladder.steps[0].points[0].xyz is not None

        panel.add_rung.click()
        window._on_marker_clicked(VIDEOS[first], 17.0, 31.0)
        panel.next_point.click()
        window._on_marker_clicked(VIDEOS[second], 94.0, 12.0)
        panel.save_step.click()
        ladder = window.props_app.store.get("uneven ladder")
        assert ladder is not None and len(ladder.steps) == 2
        assert ladder.steps[1].points[0].clicks[0].x == 17.0
        assert ladder.steps[1].points[1].clicks[0].x == 94.0
        assert all(point.xyz is None for point in ladder.steps[1].points)
        # A rung is never drawn across a camera where one endpoint was not clicked.
        drawing = window.props_app.camera_drawing(VIDEOS[first], 0.0)
        assert drawing[1][1] == ((17.0, 31.0, True), None)

        folder = tmp_path / "pose-3d"
        qtbot.waitUntil(lambda: len(read_props(folder)[0][0].steps) == 2, timeout=3000)
        assert window.document.undo(window._mutations)
        assert len(window.props_app.store.get("uneven ladder").steps) == 1
        qtbot.waitUntil(lambda: len(read_props(folder)[0][0].steps) == 1, timeout=3000)
        assert window.document.redo(window._mutations)
        qtbot.waitUntil(lambda: len(read_props(folder)[0][0].steps) == 2, timeout=3000)
        loaded, issues = read_props(folder)
        assert not issues and loaded == [window.props_app.store.get("uneven ladder")]


def test_props_overlay_is_independent_of_wheel_and_tracking(window: MainWindow) -> None:
    assert window._overlay_actions["tracking.props"].isChecked()
    window._overlay_actions["tracking.props"].trigger()
    assert not window.overlay_state.is_visible("tracking.props")
    assert window.overlay_state.is_visible("tracking.wheel")
    assert window.overlay_state.is_visible("tracking.points")


def test_reclick_and_rename_change_only_the_selected_step(window: MainWindow, monkeypatch) -> None:
    panel = window.props_app.panel
    assert panel is not None
    window._act_add_prop.trigger()
    panel.name.setText("steps")
    panel.create_button.click()
    front, side = list(CAMERAS)[:2]
    with monkeypatch.context() as patches:
        _fake_panes(window, patches)
        panel.add_rung.click()
        window._on_marker_clicked(VIDEOS[front], 10.0, 20.0)
        panel.next_point.click()
        window._on_marker_clicked(VIDEOS[side], 30.0, 40.0)
        panel.save_step.click()
        before = window.props_app.store.get("steps")
        assert before is not None
        step = before.steps[0]

        panel.steps.setCurrentRow(0)
        panel.step_label.setText("Raised rung")
        panel.relabel_step.click()
        renamed = window.props_app.store.get("steps").steps[0]
        assert renamed.label == "Raised rung"
        assert renamed.points == step.points

        panel.steps.setCurrentRow(0)
        panel.reclick_step.click()
        window._on_marker_clicked(VIDEOS[front], 11.0, 25.0)
        panel.save_step.click()
        corrected = window.props_app.store.get("steps").steps[0]
        assert corrected.step_id == step.step_id
        assert corrected.points[0].clicks[0].x == 11.0
        assert corrected.points[1] == step.points[1]
        assert window.document.undo(window._mutations)
        assert window.props_app.store.get("steps").steps[0] == renamed


def test_saved_ladder_reopens_with_original_clicks(
    window: MainWindow, qtbot, tmp_path: Path
) -> None:
    """Discovery never turns a one-camera click into an invented 3D point."""
    click = StepClick("Front", 23, 118.5, 92.0)
    saved = Ladder(
        "reopened",
        (LadderStep("uneven", "Raised step", (LadderPoint().with_click(click),)),),
    )
    write_ladder(tmp_path / "pose-3d", saved)
    window.props_app.adopt()
    qtbot.waitUntil(lambda: window.props_app.store.get("reopened") is not None, timeout=3000)
    assert window.props_app.store.get("reopened") == saved
    assert window.props_app.camera_drawing(VIDEOS["Front"], 0.0) == [
        ("Raised step", ((118.5, 92.0, True),), False)
    ]
    assert window.props_app.scene_steps(0.0) == []


def test_failed_discovery_can_be_retried_without_losing_a_saved_ladder(
    window: MainWindow, qtbot, monkeypatch, tmp_path: Path
) -> None:
    saved = Ladder(
        "recovered",
        (LadderStep("one", "step", (LadderPoint((StepClick("Front", 7, 1.0, 2.0),)),)),),
    )
    write_ladder(tmp_path / "pose-3d", saved)
    original_read = prop_file_worker.read_props
    attempts = 0

    def fail_once(folder: Path):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("temporary read failure")
        return original_read(folder)

    monkeypatch.setattr(prop_file_worker, "read_props", fail_once)
    window.props_app.adopt()
    qtbot.waitUntil(lambda: attempts == 1, timeout=3000)
    window.props_app.adopt()
    qtbot.waitUntil(lambda: window.props_app.store.get("recovered") is not None, timeout=3000)
    assert attempts == 2
    assert window.props_app.store.get("recovered") == saved


def test_incomplete_rung_cannot_be_saved_and_cancelling_keeps_no_partial_step(
    window: MainWindow, monkeypatch
) -> None:
    window._act_add_prop.trigger()
    panel = window.props_app.panel
    assert panel is not None
    panel.name.setText("incomplete")
    panel.create_button.click()
    with monkeypatch.context() as patches:
        _fake_panes(window, patches)
        panel.add_rung.click()
        window._on_marker_clicked(VIDEOS["Front"], 12.0, 34.0)
        panel.save_step.click()
        assert window.props_app.draft is not None
        assert window.props_app.store.get("incomplete").steps == ()
        panel.next_point.click()
        panel.save_step.click()
        assert window.props_app.store.get("incomplete").steps == ()
        panel.cancel_step.click()
    assert window.props_app.draft is None
    assert window.props_app.store.get("incomplete").steps == ()


def test_closed_outline_requires_three_explicit_points_and_keeps_their_shape(
    window: MainWindow, monkeypatch
) -> None:
    window._act_add_prop.trigger()
    panel = window.props_app.panel
    assert panel is not None
    panel.name.setText("outline")
    panel.create_button.click()
    with monkeypatch.context() as patches:
        _fake_panes(window, patches)
        panel.closed.setChecked(True)
        panel.add_point.click()
        window._on_marker_clicked(VIDEOS["Front"], 10.0, 20.0)
        panel.save_step.click()
        assert window.props_app.store.get("outline").steps == ()
        for x, y in ((30.0, 12.0), (24.0, 44.0)):
            panel.next_point.click()
            window._on_marker_clicked(VIDEOS["Front"], x, y)
        panel.save_step.click()
    step = window.props_app.store.get("outline").steps[0]
    assert step.closed
    assert [(point.clicks[0].x, point.clicks[0].y) for point in step.points] == [
        (10.0, 20.0),
        (30.0, 12.0),
        (24.0, 44.0),
    ]
    assert window.props_app.camera_drawing(VIDEOS["Front"], 0.0)[0][2] is True


def test_belt_and_ball_geometry_are_editable_and_reopen_from_the_props_tab(
    window: MainWindow, qtbot, monkeypatch, tmp_path: Path
) -> None:
    panel = window.props_app.panel
    assert panel is not None
    panel.kind.setCurrentIndex(panel.kind.findData("belt"))
    assert panel.editor_stack.currentWidget() is panel.belt_editor
    panel.name.setText("belt")
    panel.belt_geometry_mode.setCurrentIndex(panel.belt_geometry_mode.findData("path"))
    for values in ((0.0, 0.0, 70.0), (10.0, 0.0, 70.0)):
        for field, value in zip(panel.belt_point_fields, values, strict=True):
            field.setValue(value)
        panel.belt_add_vertex.click()
    panel.belt_direction_fields[0].setValue(1.0)
    panel.belt_units.setCurrentIndex(panel.belt_units.findData("mm"))
    panel.save_belt.click()
    belt = window.props_app.store.get("belt")
    assert isinstance(belt, BeltProp)
    assert belt.track.vertices == ((0.0, 0.0, 70.0), (10.0, 0.0, 70.0))
    assert "unknown" in panel.belt_motion_status.text().lower()

    panel.belt_direction_fields[1].setValue(1.0)
    panel.save_belt.click()
    changed_belt = window.props_app.store.get("belt")
    assert isinstance(changed_belt, BeltProp)
    assert changed_belt.travel_direction == pytest.approx((2**-0.5, 2**-0.5, 0.0))
    assert window.document.undo(window._mutations)
    assert window.props_app.store.get("belt") == belt
    assert window.document.redo(window._mutations)

    panel.kind.setCurrentIndex(panel.kind.findData("ball"))
    assert panel.editor_stack.currentWidget() is panel.ball_editor
    assert panel.name.text() == ""
    panel.name.setText("ball")
    for field, value in zip(panel.ball_centre_fields, (20.0, 0.0, 75.0), strict=True):
        field.setValue(value)
    panel.ball_radius.setValue(5.0)
    panel.ball_units.setCurrentIndex(panel.ball_units.findData("cm"))
    panel.save_ball.click()
    ball = window.props_app.store.get("ball")
    assert isinstance(ball, BallProp)
    assert ball.surface.centre == (20.0, 0.0, 75.0)
    assert ball.surface.radius == 5.0
    assert "unknown" in panel.ball_motion_status.text().lower()

    folder = tmp_path / "pose-3d"
    qtbot.waitUntil(lambda: len(read_props(folder)[0]) == 2, timeout=3000)
    reopened, issues = read_props(folder)
    assert issues == []
    reopened_by_name = {prop.name: prop for prop in reopened}
    reopened_belt = reopened_by_name["belt"]
    assert isinstance(reopened_belt, BeltProp)
    assert reopened_belt.track == changed_belt.track
    assert reopened_belt.travel_direction == pytest.approx(changed_belt.travel_direction)
    assert reopened_by_name["ball"] == ball

    monkeypatch.setattr(
        "avialsync.ui.props_app.wheel_display.camera_models", lambda _window: dict(CAMERAS)
    )
    drawings = window.props_app.camera_drawing(VIDEOS["Front"], 0.0)
    assert any(label == "belt" for label, _points, _closed in drawings)
    ball_rings = [item for item in drawings if item[2] and len(item[1]) > 3]
    assert len(ball_rings) == 9
    assert sum(label == "ball" for label, *_ in ball_rings) == 1
    scene = window.props_app.scene_steps(0.0)
    scene_rings = [item for item in scene if item[2] and len(item[1]) > 3]
    assert len(scene_rings) == 9
    assert sum(label == "ball" for label, *_ in scene_rings) == 1

    panel.remove_ball.click()
    assert window.props_app.store.get("ball") is None
    assert window.document.undo(window._mutations)
    assert window.props_app.store.get("ball") == ball


def test_reordering_and_removing_irregular_steps_preserves_clicks_and_undo(
    window: MainWindow, monkeypatch
) -> None:
    window._act_add_prop.trigger()
    panel = window.props_app.panel
    assert panel is not None
    panel.name.setText("ordered")
    panel.create_button.click()
    with monkeypatch.context() as patches:
        _fake_panes(window, patches)
        for label, x in (("low", 10.0), ("high", 42.0), ("uneven", 27.0)):
            panel.step_label.setText(label)
            panel.add_point.click()
            window._on_marker_clicked(VIDEOS["Front"], x, x + 2.0)
            panel.save_step.click()
    before = window.props_app.store.get("ordered")
    assert before is not None
    assert [step.points[0].clicks[0].x for step in before.steps] == [10.0, 42.0, 27.0]
    panel.steps.setCurrentRow(2)
    panel.up.click()
    moved = window.props_app.store.get("ordered")
    assert moved is not None
    assert [step.step_id for step in moved.steps] == [
        before.steps[0].step_id,
        before.steps[2].step_id,
        before.steps[1].step_id,
    ]
    assert moved.steps[1] == before.steps[2]
    assert window.document.undo(window._mutations)
    assert window.props_app.store.get("ordered") == before
    panel.steps.setCurrentRow(1)
    panel.remove_step.click()
    reduced = window.props_app.store.get("ordered")
    assert reduced is not None and reduced.steps == (before.steps[0], before.steps[2])
    assert window.document.undo(window._mutations)
    assert window.props_app.store.get("ordered") == before


def test_third_camera_projection_does_not_become_an_observed_click(
    window: MainWindow, monkeypatch
) -> None:
    window._act_add_prop.trigger()
    panel = window.props_app.panel
    assert panel is not None
    panel.name.setText("projection")
    panel.create_button.click()
    world = np.asarray([[0.1, 0.2, 0.3]])
    with monkeypatch.context() as patches:
        _fake_panes(window, patches)
        panel.add_point.click()
        for camera in ("Front", "Left"):
            x, y = CAMERAS[camera].project(world)[0]
            window._on_marker_clicked(VIDEOS[camera], float(x), float(y))
        panel.save_step.click()
    point = window.props_app.store.get("projection").steps[0].points[0]
    assert {click.camera for click in point.clicks} == {"Front", "Left"}
    front = window.props_app.camera_drawing(VIDEOS["Front"], 0.0)[0][1][0]
    right = window.props_app.camera_drawing(VIDEOS["Right"], 0.0)[0][1][0]
    assert front is not None and front[2] is True
    assert right is not None and right[2] is False
    assert right[:2] == pytest.approx(CAMERAS["Right"].project(world)[0], abs=0.01)
    scene = window.props_app.scene_steps(0.0)
    assert len(scene) == 1 and scene[0][1][0] == pytest.approx(world[0], abs=0.01)

    behind = dataclasses.replace(
        CAMERAS["Right"],
        translation=-(CAMERAS["Right"].rotation_matrix() @ world[0]) - np.asarray((0.0, 0.0, 1.0)),
    )
    window._calibration_state = SimpleNamespace(
        cameras={
            VIDEOS["Front"]: CAMERAS["Front"],
            VIDEOS["Left"]: CAMERAS["Left"],
            VIDEOS["Right"]: behind,
        }
    )
    assert window.props_app.camera_drawing(VIDEOS["Right"], 0.0) == []

    window._calibration_state = None
    assert window.props_app.scene_steps(0.0) == []
    assert window.props_app.camera_drawing(VIDEOS["Front"], 0.0)[0][1][0] == front
    assert window.props_app.camera_drawing(VIDEOS["Right"], 0.0) == []


def test_rapid_edits_write_the_latest_accepted_revision_in_order(
    window: MainWindow, qtbot, monkeypatch, tmp_path: Path
) -> None:
    queued: list[PropFileWriteWorker] = []

    def hold_writes(worker, label: str = "Working", configure=None):
        del label
        if configure is not None:
            configure(QThread())
        if isinstance(worker, PropFileWriteWorker):
            queued.append(worker)
        else:
            worker.run()
        return QThread()

    monkeypatch.setattr(window, "_run_job", hold_writes)
    window._act_add_prop.trigger()
    panel = window.props_app.panel
    assert panel is not None
    panel.name.setText("rapid")
    panel.create_button.click()
    assert len(queued) == 1
    with monkeypatch.context() as patches:
        _fake_panes(window, patches)
        panel.add_point.click()
        window._on_marker_clicked(VIDEOS["Front"], 10.0, 20.0)
        panel.save_step.click()
        panel.add_point.click()
        window._on_marker_clicked(VIDEOS["Front"], 30.0, 40.0)
        panel.save_step.click()
    assert len(queued) == 1
    queued[0].run()
    qtbot.waitUntil(lambda: len(queued) == 2, timeout=3000)
    queued[1].run()
    folder = tmp_path / "pose-3d"
    qtbot.waitUntil(lambda: len(read_props(folder)[0][0].steps) == 2, timeout=3000)
    assert read_props(folder)[0] == [window.props_app.store.get("rapid")]


def test_creation_during_discovery_keeps_the_unread_sidecar_intact(
    window: MainWindow, qtbot, monkeypatch, tmp_path: Path
) -> None:
    folder = tmp_path / "pose-3d"
    saved = Ladder(
        "occupied",
        (LadderStep("old", "Existing step", (LadderPoint((StepClick("Front", 7, 9.0, 8.0),)),)),),
    )
    target = write_ladder(folder, saved)
    original = target.read_bytes()
    held_reads: list[PropFileReadWorker] = []

    def hold_read(worker, label: str = "Working", configure=None):
        del label
        if configure is not None:
            configure(QThread())
        if isinstance(worker, PropFileReadWorker):
            held_reads.append(worker)
        else:
            worker.run()
        return QThread()

    monkeypatch.setattr(window, "_run_job", hold_read)
    window.props_app.adopt()
    assert len(held_reads) == 1
    window._act_add_prop.trigger()
    panel = window.props_app.panel
    assert panel is not None
    panel.name.setText("occupied")
    panel.create_button.click()
    qtbot.waitUntil(lambda: window.props_app.store.get("occupied") is not None, timeout=3000)
    assert target.read_bytes() == original
    held_reads[0].run()
    assert target.read_bytes() == original
    assert window.props_app.store.get("occupied") == Ladder("occupied")
    with monkeypatch.context() as patches:
        _fake_panes(window, patches)
        panel.add_point.click()
        window._on_marker_clicked(VIDEOS["Front"], 12.0, 34.0)
        panel.save_step.click()
    assert target.read_bytes() == original


@pytest.mark.parametrize("kind", ["ladder", "wheel", "belt", "ball"])
def test_every_prop_editor_fits_the_sidebar_without_scrolling_sideways(qtbot, kind: str) -> None:
    """The stack took its widest page's width, hidden pages included, and the
    belt editor put three long buttons on one line: 453 px in a 280 px
    sidebar, with every button clipped at its right edge.

    Asserted against the panel's own widest control rather than a pixel
    width, so it holds under any platform font: a panel no wider than its
    widest single control plus its margins is one with nothing side by side
    and no hidden page setting its width.
    """
    from PySide6.QtWidgets import (
        QAbstractButton,
        QAbstractItemView,
        QAbstractSpinBox,
        QComboBox,
        QLabel,
        QLineEdit,
    )

    from avialsync.core.physical_props import PropStore
    from avialsync.ui.props_panel import PropsPanel, PropsTab

    panel = PropsPanel(PropStore())
    tab = PropsTab(panel)
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitExposed(tab)
    panel.kind.setCurrentIndex(panel.kind.findData(kind))
    QApplication.processEvents()

    controls = [
        child.minimumSizeHint().width()
        for kind_of in (
            QAbstractButton,
            QAbstractItemView,
            QAbstractSpinBox,
            QComboBox,
            QLabel,
            QLineEdit,
        )
        for child in panel.findChildren(kind_of)
        if child.isVisibleTo(panel)
    ]
    widest = max(controls)
    margins = panel.layout().contentsMargins()
    allowance = margins.left() + margins.right() + 24
    assert panel.minimumSizeHint().width() <= widest + allowance, (
        f"the {kind} editor needs {panel.minimumSizeHint().width()} px "
        f"for controls no wider than {widest} px"
    )


def _patch_rig(window: MainWindow, monkeypatch) -> None:
    _fake_panes(window, monkeypatch)
    monkeypatch.setattr(
        "avialsync.ui.props_app.wheel_display.frame_and_time", lambda _window, _t: (7, 0.0)
    )
    monkeypatch.setattr(
        "avialsync.ui.props_app.wheel_display.camera_models", lambda _window: CAMERAS
    )


def _click_world(window: MainWindow, world: tuple[float, ...], cameras: tuple[str, ...]) -> None:
    for camera in cameras:
        x, y = CAMERAS[camera].project(np.asarray(world))[0]
        assert window.props_app.on_clicked(VIDEOS[camera], float(x), float(y))


def test_belt_is_placed_in_3d_from_four_clicked_top_corners(
    window: MainWindow, monkeypatch
) -> None:
    panel = window.props_app.panel
    assert panel is not None
    _patch_rig(window, monkeypatch)
    window.props_app.show("belt")
    panel.name.setText("treadmill")
    panel.belt_units.setCurrentIndex(panel.belt_units.findData("mm"))
    panel.belt_radius.setValue(10.0)
    panel.belt_centre_distance.setValue(60.0)
    assert panel.belt_placement.isVisibleTo(panel)
    panel.belt_placement.start.click()
    corners = ((-25.0, -8.0, 70.0), (-25.0, 8.0, 70.0), (25.0, -8.0, 70.0), (25.0, 8.0, 70.0))
    for index, corner in enumerate(corners):
        if index:
            panel.belt_placement.next_point.click()
        _click_world(window, corner, ("Front", "Left"))
    # Every clicked corner stays visible while placing, not only the latest one.
    labels = [label for label, _p, _c in window.props_app.camera_drawing(VIDEOS["Front"], 0.0)]
    assert {"corner 1", "corner 2", "corner 3", "corner 4"} <= set(labels)
    panel.belt_placement.place.click()
    panel.save_belt.click()

    belt = window.props_app.store.get("treadmill")
    assert isinstance(belt, BeltProp) and belt.corners is not None, panel.status.text()
    assert belt.rollers is not None
    assert belt.rollers.first == pytest.approx((-30.0, 0.0, 60.0), abs=1e-3)
    assert belt.rollers.second == pytest.approx((30.0, 0.0, 60.0), abs=1e-3)
    assert belt.rollers.width == pytest.approx(16.0, abs=1e-3)
    assert belt.travel_direction == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)
    # Saved corners stay as uncaptioned marks: evidence, not captions.
    right = [
        points[0]
        for label, points, _closed in window.props_app.camera_drawing(VIDEOS["Right"], 0.0)
        if label == UNNAMED
    ]
    assert len(right) == 4 and not any(pixel is None or pixel[2] for pixel in right), (
        "Right clicked nothing, so it shows projections only"
    )
    scene = [label for label, _points, _closed in window.props_app.scene_steps(0.0)]
    assert scene.count(UNNAMED) == 4
    assert "3D" in panel.belt_placement.status.text()


def test_one_camera_belt_uses_measurements_and_draws_only_in_its_view(
    window: MainWindow, monkeypatch
) -> None:
    panel = window.props_app.panel
    assert panel is not None
    _patch_rig(window, monkeypatch)
    window.props_app.show("belt")
    panel.belt_geometry_mode.setCurrentIndex(panel.belt_geometry_mode.findData("side"))
    assert not panel.belt_roller_controls.isVisibleTo(panel)
    panel.name.setText("side belt")
    panel.belt_radius.setValue(10.0)
    panel.belt_centre_distance.setValue(80.0)
    panel.belt_width.setValue(20.0)

    def seen(along: float, up: float) -> tuple[float, float]:
        x, y = CAMERAS["Left"].project(np.asarray((along - 40.0, -30.0, 60.0 + up)))[0]
        return (float(x), float(y))

    panel.belt_placement.start.click()
    for index, (along, up) in enumerate(((0, 0), (80, 0), (0, 10), (80, 10))):
        if index:
            panel.belt_placement.next_point.click()
        assert window.props_app.on_clicked(VIDEOS["Left"], *seen(along, up))
    panel.belt_placement.place.click()
    panel.save_belt.click()

    belt = window.props_app.store.get("side belt")
    assert isinstance(belt, BeltProp) and belt.side_view is not None, panel.status.text()
    assert belt.side_view.camera == "Left"
    left = window.props_app.camera_drawing(VIDEOS["Left"], 0.0)
    profile = next(points for label, points, _c in left if label == "side belt")
    # The far wrap's outermost point lands exactly where the camera sees it.
    assert any(p is not None and math.dist(p[:2], seen(90.0, 0.0)) < 1e-6 for p in profile)
    assert sum(label == UNNAMED for label, _p, _c in left) == 4, "hubs and tops stay marked"
    front = window.props_app.camera_drawing(VIDEOS["Front"], 0.0)
    assert not any(label == "side belt" for label, _p, _c in front)
    assert not any(label == "side belt" for label, _p, _c in window.props_app.scene_steps(0.0))
    assert "Left" in panel.belt_placement.status.text()

    # One camera also tracks a belt mark: its click maps back onto the profile.
    assert panel.track_belt.isEnabled()
    panel.track_belt.click()
    assert window.props_app.on_clicked(VIDEOS["Left"], *seen(25.0, 10.0))
    tracked = window.props_app.store.get("side belt")
    assert isinstance(tracked, BeltProp) and tracked.visual_frames
    state = belt_visual_state(tracked, tracked.visual_frames[0].frame, {})
    assert state is not None and state.path_distance == pytest.approx(25.0, abs=1e-6)


def test_ladder_support_irregular_tags_and_clicking_every_rung(
    window: MainWindow, monkeypatch
) -> None:
    panel = window.props_app.panel
    assert panel is not None
    _patch_rig(window, monkeypatch)
    window.props_app.show("ladder")
    panel.name.setText("walkway")
    panel.create_button.click()
    rungs = (
        ((0.0, -10.0, 70.0), (0.0, 10.0, 70.0)),
        ((15.0, 10.0, 70.0), (15.0, -10.0, 70.0)),
        ((33.0, -10.0, 74.0), (33.0, 10.0, 74.0)),
    )
    panel.add_rung.click()
    for index, (first, second) in enumerate(rungs):
        if index == 2:
            panel.step_irregular.setCurrentIndex(panel.step_irregular.findData("raised"))
        _click_world(window, first, ("Front", "Left"))
        panel.next_point.click()
        _click_world(window, second, ("Front", "Left"))
        (panel.save_step if index == 2 else panel.save_next_step).click()
    ladder = window.props_app.store.get("walkway")
    assert isinstance(ladder, Ladder) and len(ladder.steps) == 3, panel.status.text()
    assert [step.irregular for step in ladder.steps] == ["", "", "raised"]
    assert window.props_app.draft is None
    assert panel.step_irregular.currentData() == ""

    panel.steps.setCurrentRow(1)
    panel.step_irregular.setCurrentIndex(panel.step_irregular.findData("missing"))
    panel.tag_step.click()
    ladder = window.props_app.store.get("walkway")
    assert isinstance(ladder, Ladder) and ladder.steps[1].irregular == "missing"
    labels = [label for label, _p, _c in window.props_app.camera_drawing(VIDEOS["Front"], 0.0)]
    assert "Step 2 · missing rung" in labels

    panel.ladder_support.setCurrentIndex(panel.ladder_support.findData("side_rails"))
    panel.ladder_support.activated.emit(panel.ladder_support.currentIndex())
    ladder = window.props_app.store.get("walkway")
    assert isinstance(ladder, Ladder) and ladder.support == "side_rails"
    bars = [
        points
        for label, points, _closed in window.props_app.camera_drawing(VIDEOS["Front"], 0.0)
        if not label and len(points) == 3
    ]
    assert len(bars) == 2 and all(
        pixel is not None and not pixel[2] for bar in bars for pixel in bar
    )
    scene_bars = [
        points
        for label, points, _closed in window.props_app.scene_steps(0.0)
        if not label and len(points) == 3
    ]
    assert len(scene_bars) == 2
    # The rails run along the clicked ends without crossing, whatever click order.
    ends = sorted(round(float(points[0][1])) for points in scene_bars)
    assert ends == [-10, 10]
    assert all(
        round(float(position[1])) == round(float(points[0][1]))
        for points in scene_bars
        for position in points
    )
    assert window.document.undo(window._mutations)
    ladder = window.props_app.store.get("walkway")
    assert isinstance(ladder, Ladder) and ladder.support == "none"
    assert panel.ladder_support.currentData() == "none"

    # A regular run of 6 from the first two rungs; the clicked third rung is
    # raised and 3 mm off-pattern, so it replaces rung 3 rather than doubling it.
    panel.rung_count.setValue(6)
    panel.extrapolate.click()
    ladder = window.props_app.store.get("walkway")
    assert isinstance(ladder, Ladder) and ladder.pattern is not None
    assert ladder.pattern.count == 6
    right = window.props_app.camera_drawing(VIDEOS["Right"], 0.0)
    estimated = {label: points for label, points, _c in right if label.endswith("(est.)")}
    # A run is captioned at its first and last estimate; rungs between are dashed only.
    assert sorted(estimated) == ["Rung 4 (est.)", "Rung 6 (est.)"]
    between = [points for label, points, _c in right if label == UNNAMED and len(points) == 2]
    assert len(between) == 1
    assert all(
        not pixel[2] for points in (*estimated.values(), *between) for pixel in points if pixel
    )
    scene = {
        label: points
        for label, points, _c in window.props_app.scene_steps(0.0)
        if label.endswith("(est.)")
    }
    assert float(scene["Rung 6 (est.)"][0][0]) == pytest.approx(75.0, abs=1e-6)
    panel.rung_count.setValue(0)
    panel.extrapolate.click()
    ladder = window.props_app.store.get("walkway")
    assert isinstance(ladder, Ladder) and ladder.pattern is None
