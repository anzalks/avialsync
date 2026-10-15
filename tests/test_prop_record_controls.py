"""Every prop can be explicitly saved, removed, reopened, and restored by Undo."""

from __future__ import annotations

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
    StepClick,
)
from avialsync.core.prop_file import PropRecord, prop_kind, read_prop_records, read_props
from avialsync.core.wheel import Wheel, WheelFit, WheelSpec
from avialsync.engine import prop_file_worker
from avialsync.ui.controllers import rig_paths, wheel_controller, wheel_display
from avialsync.ui.main_window import MainWindow
from avialsync.ui.props_app import StepDraft
from tests.wheel_fixture import TRUTH, clicks_for
from tests.wheel_window import build_window


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
    if kind == "wheel":
        wheel_display.refresh(window)
        row = window.wheel_panel._rows[record.name]
        return row.save, row.remove
    return getattr(panel, f"save_{kind}"), getattr(panel, f"remove_{kind}")


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
    assert save.text() == "Save prop"
    assert remove.text() == "Remove saved prop"
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
