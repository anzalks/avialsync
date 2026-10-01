"""The Props inspector retains irregular clicked ladder evidence end to end."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.physical_props import (
    BallProp,
    BeltProp,
    Ladder,
    LadderPoint,
    LadderStep,
    StepClick,
)
from avialsync.core.prop_file import read_props, write_ladder
from avialsync.engine import prop_file_worker
from avialsync.engine.prop_file_worker import PropFileReadWorker, PropFileWriteWorker
from avialsync.ui.main_window import MainWindow
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


def _fake_panes(window: MainWindow, monkeypatch) -> None:
    paths = list(VIDEOS.values())
    pane = SimpleNamespace(
        frame_record_at=lambda _t: (7, 0.0),
        paint_canvas=SimpleNamespace(update=lambda: None),
        set_marker_place_mode=lambda _enabled: None,
    )
    monkeypatch.setattr(window.video_grid, "pane_paths", lambda: paths)
    monkeypatch.setattr(window.video_grid, "panes", [pane for _ in paths])


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
    assert any(
        "belt" in label and "motion unknown" in label for label, _points, _closed in drawings
    )
    assert (
        sum(
            "ball" in label and "orientation unknown" in label
            for label, _points, _closed in drawings
        )
        == 3
    )
    scene = window.props_app.scene_steps(0.0)
    assert (
        sum("ball" in label and "orientation unknown" in label for label, _points, _closed in scene)
        == 3
    )

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
