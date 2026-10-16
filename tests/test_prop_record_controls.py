"""Every prop can be explicitly saved, removed, reopened, and restored by Undo."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton
from shiboken6 import isValid

from avialsync.core.physical_props import (
    BallProp,
    BallSurface,
    BeltProp,
    BeltTrack,
    Ladder,
    LadderPoint,
    LadderStep,
    RungPattern,
    StepClick,
)
from avialsync.core.prop_file import PropRecord, prop_kind, read_prop_records, read_props
from avialsync.core.wheel import Wheel, WheelFit, WheelSpec
from avialsync.engine import prop_file_worker
from avialsync.ui.controllers import rig_paths, wheel_controller, wheel_display
from avialsync.ui.main_window import MainWindow
from avialsync.ui.props_app import StepDraft
from tests.test_props_ui import _fake_panes
from tests.wheel_fixture import TRUTH, clicks_for
from tests.wheel_window import VIDEOS, build_window


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path: Path):
    win = build_window(qtbot, monkeypatch, tmp_path / "pose-3d", {"now": 7, "t": 0.0})
    win.show()
    yield win
    if isValid(win):
        win.close()


def _record(kind: str) -> PropRecord:
    if kind == "ladder":
        point = LadderPoint((StepClick("Front", 7, 20.0, 30.0),))
        return Ladder("selected", (LadderStep("one", "Rung", (point,)),))
    if kind == "belt":
        return BeltProp("selected", BeltTrack(((0.0, 0.0, 70.0), (10.0, 0.0, 70.0))))
    if kind == "ball":
        return BallProp("selected", BallSurface((0.0, 0.0, 75.0), 5.0))
    return Wheel(
        WheelSpec("selected", 36),
        7,
        clicks_for([0, 1]),
        WheelFit(TRUTH, (0, 1), (), (0.0, 0.0), (0.0, 0.0)),
    )


def _buttons(window: MainWindow, record: PropRecord) -> tuple[QPushButton, QPushButton]:
    kind = prop_kind(record)
    window.props_app.show(kind)
    panel = window.props_app.panel
    assert panel is not None
    panel.select(record.name)
    wheel_display.refresh(window)
    return panel.records.save_button, panel.records.remove_button


def _click(window: MainWindow, qtbot, button: QPushButton) -> None:
    tab = window.props_app.tab
    assert tab is not None
    tab.ensureWidgetVisible(button)
    assert button.isVisibleTo(tab) and button.isEnabled()
    assert button.accessibleName() and button.accessibleDescription()
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


@pytest.mark.parametrize("kind", ["ladder", "wheel", "belt", "ball"])
def test_each_prop_saves_removes_and_undo_restores_its_sidecar(
    window: MainWindow, qtbot, tmp_path: Path, kind: str
) -> None:
    record = _record(kind)
    other = Ladder("another prop")
    window.props_app.store.load((record, other))
    save, remove = _buttons(window, record)
    assert save.text() == "Save"
    assert remove.text() == "Remove"
    _click(window, qtbot, save)
    folder = tmp_path / "pose-3d"
    assert read_props(folder) == ([record], [])
    assert not window.document.is_dirty and len(window.document) == 0

    _click(window, qtbot, remove)
    assert window.props_app.store.get(record.name) is None
    assert window.props_app.store.get(other.name) is other
    assert read_prop_records(folder) == ([], [], {record.name})
    assert window.document.undo(window._mutations)
    assert window.props_app.store.get(record.name) == record
    assert read_props(folder) == ([record], [])
    assert window.document.redo(window._mutations)
    window.props_app.reset()
    window.props_app.adopt()
    assert window.props_app.store.get(record.name) is None


@pytest.mark.parametrize("kind", ["ladder", "wheel", "belt", "ball"])
def test_save_retries_failed_writes_without_adding_empty_undo_steps(
    window: MainWindow, qtbot, monkeypatch, tmp_path: Path, kind: str
) -> None:
    record = _record(kind)
    window.props_app.store.load((record,))
    save, _remove = _buttons(window, record)
    original = prop_file_worker.write_prop
    attempts = []

    def fail_once(*args, **kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("read-only recording")
        return original(*args, **kwargs)

    monkeypatch.setattr(prop_file_worker, "write_prop", fail_once)
    _click(window, qtbot, save)
    assert read_props(tmp_path / "pose-3d") == ([], [])
    assert window.props_app.store.get(record.name) == record
    _click(window, qtbot, save)
    assert len(attempts) == 2
    assert read_props(tmp_path / "pose-3d") == ([record], [])
    assert not window.document.is_dirty and len(window.document) == 0


@pytest.mark.parametrize("kind", ["ladder", "wheel", "belt", "ball"])
def test_save_requires_a_recording_but_removal_keeps_undo_available(
    window: MainWindow, monkeypatch, kind: str
) -> None:
    record = _record(kind)
    window.props_app.store.load((record,))
    monkeypatch.setattr(rig_paths, "pose3d_dir", lambda _paths: None)
    save, remove = _buttons(window, record)
    assert not save.isEnabled()
    assert "recording" in save.toolTip().lower()
    assert remove.isEnabled()


@pytest.mark.parametrize("kind", ["ladder", "belt", "ball"])
def test_removing_a_prop_cancels_its_own_click_workflow(window: MainWindow, kind: str) -> None:
    record = _record(kind)
    window.props_app.store.load((record,))
    window.props_app.draft = StepDraft(record.name, "unfinished")
    window.props_app.checking = record.name
    window.props_app.visual_tracking = (kind, record.name)
    window.props_app.remove_prop(kind, record.name)
    assert window.props_app.draft is None
    assert window.props_app.checking is None
    assert window.props_app.visual_tracking is None
    assert window.document.undo(window._mutations)
    assert window.props_app.store.get(record.name) is record


def test_removal_preserves_another_props_draft_and_rejects_the_wrong_kind(
    window: MainWindow,
) -> None:
    record = _record("ball")
    window.props_app.store.load((record, Ladder("another")))
    draft = StepDraft("another", "unfinished")
    window.props_app.draft = draft
    window.props_app.remove_prop("belt", record.name)
    assert window.props_app.store.get(record.name) is record
    assert len(window.document) == 0
    window.props_app.remove_prop("ball", record.name)
    assert window.props_app.draft is draft


def test_removing_a_wheel_cancels_its_replacement_without_restoring_the_draft(
    window: MainWindow,
    qtbot,
) -> None:
    record = _record("wheel")
    window.props_app.store.load((record,))
    _save, remove = _buttons(window, record)
    window.wheel_panel._rows[record.name].replace.click()
    placement = window.wheel_state.placement
    assert placement is not None and placement.replacing == record.name
    _click(window, qtbot, remove)
    assert window.wheel_state.placement is None
    wheel_controller.accept(window)
    assert window.props_app.store.get(record.name) is None
    assert window.document.undo(window._mutations)
    assert window.props_app.store.get(record.name) is record
    assert window.wheel_state.placement is None


@pytest.mark.parametrize("accept_via_fill", [True, False])
def test_first_last_fill_accepts_the_pending_last_click_and_preserves_the_entered_total(
    window: MainWindow,
    qtbot,
    monkeypatch,
    tmp_path: Path,
    accept_via_fill: bool,
) -> None:
    window.props_app.show("ladder")
    panel = window.props_app.panel
    assert panel is not None
    panel.name.setText("walkway")
    panel.create_button.click()
    panel.ladder_support.setCurrentIndex(panel.ladder_support.findData("centre_beam"))
    panel.ladder_support.activated.emit(panel.ladder_support.currentIndex())
    panel.rung_count.setValue(30)
    assert panel.rung_mode.currentData() is True
    with monkeypatch.context() as patches:
        _fake_panes(window, patches)
        panel.add_point.click()
        window._on_marker_clicked(VIDEOS["Front"], 50.0, 60.0)
        panel.save_next_step.click()
        assert panel.rung_count.value() == 30
        window._on_marker_clicked(VIDEOS["Front"], 340.0, 60.0)
        if accept_via_fill:
            assert panel.extrapolate.text() == "Save step and fill between"
        else:
            panel.save_next_step.click()
            assert panel.extrapolate.text() == "Fill between first and last"
        _click(window, qtbot, panel.extrapolate)
        assert window.props_app.draft is None
        ladder = window.props_app.store.get("walkway")
        assert isinstance(ladder, Ladder) and len(ladder.steps) == 2
        assert ladder.pattern is not None and ladder.pattern.between_endpoints
        assert ladder.pattern.count == 30
        drawings = window.props_app.camera_drawing(VIDEOS["Front"], 0.0)
        estimates = [points[0] for label, points, _c in drawings if label and not points[0][2]]
        assert len(estimates) == 28
        assert [p[0] for p in estimates] == pytest.approx(list(range(60, 340, 10)))
        assert len(read_props(tmp_path / "pose-3d")[0][0].steps) == 2
        assert window.document.undo(window._mutations)
        assert window.props_app.store.get("walkway").pattern is None
        assert window.document.redo(window._mutations)
        assert window.props_app.store.get("walkway").pattern.count == 30
        panel.rung_mode.setCurrentIndex(panel.rung_mode.findData(False))
        assert not panel.extrapolate.isEnabled()
        assert "both ends" in panel.extrapolate.toolTip()


def test_wheels_use_one_saved_selector_and_one_pair_of_record_buttons(window: MainWindow) -> None:
    first = _record("wheel")
    assert isinstance(first, Wheel)
    second = dataclasses.replace(first, spec=dataclasses.replace(first.spec, name="another wheel"))
    window.props_app.store.load((first, second))
    window.props_app.show("wheel")
    panel = window.props_app.panel
    assert panel is not None
    wheel_display.refresh(window)
    panel.select(second.name)
    assert panel.current_prop() == second.name
    assert window.wheel_panel._rows[first.name].isHidden()
    assert not window.wheel_panel._rows[second.name].isHidden()
    assert len([b for b in panel.findChildren(QPushButton) if b.text() == "Save"]) == 1
    assert len([b for b in panel.findChildren(QPushButton) if b.text() == "Remove"]) == 1
    panel.records.remove_button.click()
    assert window.props_app.store.get(first.name) is first
    assert window.props_app.store.get(second.name) is None
    assert panel.current_prop() == first.name
    assert not window.wheel_panel._rows[first.name].isHidden()


def test_ladder_help_has_one_link_and_no_duplicate_details_button(window: MainWindow) -> None:
    window.props_app.show("ladder")
    panel = window.props_app.panel
    assert panel is not None
    steps = panel.ladder_steps
    assert steps.learn_more.isVisibleTo(panel)
    assert not steps.more_toggle.isVisibleTo(panel)
    assert steps.learn_more.parentWidget() is steps


def test_changing_total_keeps_accepted_endpoints_after_a_middle_step_is_added(
    window: MainWindow,
    qtbot,
) -> None:
    first = LadderStep("first", "First", (LadderPoint((StepClick("Front", 7, 20.0, 30.0),)),))
    last = LadderStep("last", "Last", (LadderPoint((StepClick("Front", 7, 120.0, 30.0),)),))
    middle = LadderStep("middle", "Raised", (LadderPoint((StepClick("Front", 7, 70.0, 32.0),)),))
    ladder = Ladder("walkway", (first, last, middle), pattern=RungPattern("first", "last", 6, True))
    window.props_app.store.load((ladder,))
    window.props_app.show("ladder")
    panel = window.props_app.panel
    assert panel is not None
    panel.rung_count.setValue(11)
    _click(window, qtbot, panel.extrapolate)
    changed = window.props_app.store.get(ladder.name)
    assert isinstance(changed, Ladder)
    assert changed.pattern == RungPattern("first", "last", 11, True)
    assert changed.steps == ladder.steps


def test_first_calibrated_step_captures_context_in_the_same_undo_command(
    window: MainWindow, monkeypatch
) -> None:
    state = window._calibration_state
    window._calibration_state = None
    window.props_app._accept_prop(Ladder("late"), "Add ladder")
    window._calibration_state = state
    _fake_panes(window, monkeypatch)
    window.props_app.draft = StepDraft("late", "step")
    import numpy as np

    from tests.wheel_fixture import CAMERAS

    for camera in ("Front", "Left"):
        x, y = CAMERAS[camera].project(np.array([[0.0, 0.0, 70.0]]))[0]
        window.props_app.on_clicked(VIDEOS[camera], float(x), float(y))
    assert window.props_app.save_step()
    accepted = window.props_app.store.get("late")
    assert accepted.context.cameras and accepted.steps[0].points[0].xyz is not None
    assert len(window.document) == 2
    assert window.document.undo(window._mutations)
    assert window.props_app.store.get("late") == Ladder("late")
    window._calibration_state = None
    assert window.document.redo(window._mutations)
    assert window.props_app.store.get("late") == accepted
