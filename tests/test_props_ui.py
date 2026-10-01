"""The Props inspector retains irregular clicked ladder evidence end to end."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.physical_props import Ladder, LadderPoint, LadderStep, StepClick
from avialsync.core.prop_file import read_props, write_ladder
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
