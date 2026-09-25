"""Add Wheel through the running window: click, review, accept, undo, check (D-113).

The panes are not decoded here -- which frame is on screen is stubbed to the
frame the bars are clicked on -- because what is under test is the flow the
window runs: clicks reaching the placement, the fit appearing in the Wheels
section, Accept being one undo step, the file written from the mutation funnel,
and the encoder check settling the direction. The geometry itself is judged
against ground truth in ``test_wheel.py``, whose synthetic rig these tests reuse.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.wheel import EncoderBinding, WheelSpec, project_bars
from avialsync.core.wheel_file import read_wheels, wheel_path
from avialsync.ui import recovery
from avialsync.ui.controllers import (
    calibration_controller,
    rig_paths,
    wheel_controller,
    wheel_display,
    wheel_files,
)
from avialsync.ui.main_window import MainWindow
from avialsync.ui.wheel_dialogs import WheelSetup
from tests.wheel_fixture import CAMERAS, TRUTH, clicks_for

FRAME = 7
VIDEOS = {name: f"/rec/{name}.mp4" for name in CAMERAS}


@pytest.fixture(autouse=True)
def isolated_recovery_dir(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    yield target


@pytest.fixture
def pose3d(tmp_path) -> Path:
    return tmp_path / "pose-3d"


@pytest.fixture
def frame() -> dict[str, float]:
    """The frame the stubbed panes show, and its master time; tests move it."""
    return {"now": FRAME, "t": 0.0}


@pytest.fixture
def window(
    qapp: QApplication, qtbot, monkeypatch, pose3d: Path, frame: dict[str, float]
) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    monkeypatch.setattr(rig_paths, "open_videos", lambda _w: list(VIDEOS.values()))
    monkeypatch.setattr(rig_paths, "frame_at", lambda _w, _t: frame["now"])
    monkeypatch.setattr(rig_paths, "pose3d_dir", lambda _w: pose3d)
    monkeypatch.setattr(wheel_display, "frame_and_time", lambda _w, _t: (frame["now"], frame["t"]))
    monkeypatch.setattr(wheel_display, "frame_master_time", lambda _w, f: float(f - FRAME))
    win._calibration_state = calibration_controller.CalibrationState(
        path=Path("calibration.toml"),
        cameras={VIDEOS[name]: model for name, model in CAMERAS.items()},
    )
    yield win
    if isValid(win):
        win.close()


def _place(window: MainWindow, slots: list[int], spec: WheelSpec, monkeypatch) -> None:
    """Run Add Wheel with *spec*, clicking the bars in *slots* in every camera."""
    monkeypatch.setattr(
        wheel_controller, "ask_wheel_setup", lambda *_a: WheelSetup(spec, channel=None)
    )
    wheel_controller.toggled(window, True)
    for click in clicks_for(slots):
        for camera, x, y in click.views:
            assert wheel_controller.on_clicked(window, VIDEOS[camera], x, y)


def test_clicking_two_bars_offers_a_wheel_to_accept(window: MainWindow, monkeypatch) -> None:
    _place(window, [0, 1], WheelSpec("wheel", 36), monkeypatch)
    placement = window._wheel_placement
    assert placement is not None and placement.fit is not None
    assert window._act_add_wheel.isChecked()
    assert not window.wheel_panel.isHidden()
    assert not window.wheel_panel._review.isHidden()
    assert window.wheel_panel._accept.isEnabled()


def test_wheel_button_uses_the_edit_action(window: MainWindow, monkeypatch) -> None:
    """The new entry point has one label, tooltip, state and command."""
    button = window.transport.evidence.add_wheel_button
    assert button.action is window._act_add_wheel
    assert button.text() == window._act_add_wheel.text()
    assert button.toolTip() == window._act_add_wheel.toolTip()
    assert button.isCheckable()
    assert button.accessibleDescription()
    monkeypatch.setattr(
        wheel_controller,
        "ask_wheel_setup",
        lambda *_a: WheelSetup(WheelSpec("wheel", 36), channel=None),
    )
    window._act_add_wheel.setEnabled(True)
    button.click()
    assert window._wheel_placement is not None
    assert button.isChecked() and window._act_add_wheel.isChecked()


def test_each_end_waits_for_all_three_views(window: MainWindow, monkeypatch) -> None:
    """An early fit cannot commit a wheel with an incomplete third camera."""
    monkeypatch.setattr(
        wheel_controller,
        "ask_wheel_setup",
        lambda *_a: WheelSetup(WheelSpec("wheel", 36), channel=None),
    )
    wheel_controller.toggled(window, True)
    clicks = clicks_for([0, 1])
    for click in clicks[:3]:
        for camera, x, y in click.views:
            wheel_controller.on_clicked(window, VIDEOS[camera], x, y)
    last = clicks[3]
    for camera, x, y in last.views[:2]:
        wheel_controller.on_clicked(window, VIDEOS[camera], x, y)
        drawing = wheel_display.pane_drawing(window, VIDEOS[camera], 0.0)
        assert drawing is not None and drawing.clicks[-1][0] == "2b"
    placement = window._wheel_placement
    assert placement is not None and placement.step == 3
    assert not window.wheel_panel._accept.isEnabled()
    wheel_controller.accept(window)
    assert window.wheels.get("wheel") is None
    for camera, x, y in last.views[2:]:
        wheel_controller.on_clicked(window, VIDEOS[camera], x, y)
    assert placement.step == 4
    assert window.wheel_panel._accept.isEnabled()
    for video in VIDEOS.values():
        drawing = wheel_display.pane_drawing(window, video, 0.0)
        assert drawing is not None and len(drawing.clicks) == 4


def test_three_bars_is_the_maximum_guided_input(window: MainWindow, monkeypatch) -> None:
    _place(window, [0, 1, 2], WheelSpec("wheel", 36), monkeypatch)
    placement = window._wheel_placement
    assert placement is not None and placement.step == 6
    before = placement.ordered()
    wheel_controller.on_clicked(window, VIDEOS["Front"], 1.0, 2.0)
    assert placement.ordered() == before
    assert "three bars" in window.wheel_panel._instruction.text().lower()


def test_started_third_bar_blocks_accept(window: MainWindow, monkeypatch) -> None:
    _place(window, [0, 1], WheelSpec("wheel", 36), monkeypatch)
    click = clicks_for([0, 1, 2])[4]
    camera, x, y = click.views[0]
    wheel_controller.on_clicked(window, VIDEOS[camera], x, y)
    placement = window._wheel_placement
    assert placement is not None and placement.fit is not None
    assert not window.wheel_panel._accept.isEnabled()
    wheel_controller.accept(window)
    assert window.wheels.get("wheel") is None


def test_accept_is_one_undo_step_and_writes_the_file(
    window: MainWindow, monkeypatch, pose3d: Path
) -> None:
    _place(window, [0, 1, 2], WheelSpec("wheel", 36), monkeypatch)
    wheel_controller.accept(window)
    wheel = window.wheels.get("wheel")
    assert wheel is not None
    assert wheel.frame == FRAME
    assert window._wheel_placement is None
    assert not window._act_add_wheel.isChecked()
    assert read_wheels(pose3d)[0] == [wheel]

    assert window.document.undo(window._mutations)
    assert window.wheels.get("wheel") is None
    assert wheel_path(pose3d, "wheel").exists(), "removing a wheel never deletes its file"
    assert read_wheels(pose3d)[0] == []

    assert window.document.redo(window._mutations)
    assert window.wheels.get("wheel") == wheel


def test_a_click_is_taken_back(window: MainWindow, monkeypatch) -> None:
    monkeypatch.setattr(
        wheel_controller,
        "ask_wheel_setup",
        lambda *_a: WheelSetup(WheelSpec("wheel", 36), channel=None),
    )
    wheel_controller.toggled(window, True)
    wheel_controller.on_clicked(window, VIDEOS["Front"], 100.0, 200.0)
    wheel_controller.undo_click(window)
    placement = window._wheel_placement
    assert placement is not None and placement.clicks == {}


def test_a_click_on_another_frame_is_refused(window: MainWindow, monkeypatch, frame) -> None:
    _place(window, [0], WheelSpec("wheel", 36), monkeypatch)
    frame["now"] = FRAME + 3
    placement = window._wheel_placement
    assert placement is not None
    before = dict(placement.clicks)
    wheel_controller.on_clicked(window, VIDEOS["Front"], 1.0, 2.0)
    assert placement.clicks == before


def test_without_a_placement_the_click_is_a_markers(window: MainWindow) -> None:
    assert not wheel_controller.on_clicked(window, VIDEOS["Front"], 1.0, 2.0)


def test_cancel_discards_the_clicks(window: MainWindow, monkeypatch) -> None:
    _place(window, [0, 1], WheelSpec("wheel", 36), monkeypatch)
    window._act_add_wheel.setChecked(False)
    wheel_controller.toggled(window, False)
    assert window._wheel_placement is None
    assert len(window.wheels) == 0


def test_a_typed_radius_refits_as_one_step(window: MainWindow, monkeypatch) -> None:
    _place(window, [0, 1, 2], WheelSpec("wheel", 36), monkeypatch)
    wheel_controller.accept(window)
    wheel_controller.edit_spec(window, "wheel", 36, "mm", 100.0)
    wheel = window.wheels.get("wheel")
    assert wheel is not None and wheel.spec.radius == 100.0
    assert wheel.fit.implied_radius == pytest.approx(100.0, rel=0.05)
    assert window.document.undo(window._mutations)
    restored = window.wheels.get("wheel")
    assert restored is not None and restored.spec.radius is None


def test_every_camera_draws_the_generated_bars(window: MainWindow, monkeypatch) -> None:
    _place(window, [0, 1, 2], WheelSpec("wheel", 36), monkeypatch)
    preview = wheel_display.pane_drawing(window, VIDEOS["Front"], 0.0)
    assert preview is not None
    assert all(bar.preview for bar in preview.bars)
    assert len(preview.clicks) == 6, "both ends of three bars, in this camera"
    wheel_controller.accept(window)
    for video in VIDEOS.values():
        drawing = wheel_display.pane_drawing(window, video, 0.0)
        assert drawing is not None
        assert len(drawing.bars) > 3, "more bars than were clicked"
        assert not any(bar.preview for bar in drawing.bars)
    assert wheel_display.scene(window, 0.0)


def test_without_an_encoder_the_wheel_stays_on_its_frame(
    window: MainWindow, monkeypatch, frame
) -> None:
    _place(window, [0, 1, 2], WheelSpec("wheel", 36), monkeypatch)
    wheel_controller.accept(window)
    frame["now"] = FRAME + 30
    window._wheel_cache.clear()
    assert wheel_display.pane_drawing(window, VIDEOS["Front"], 1.0) is None


def test_the_encoder_turns_the_wheel_on_other_frames(
    window: MainWindow, monkeypatch, frame
) -> None:
    _place(window, [0, 1, 2], WheelSpec("wheel", 36), monkeypatch)
    wheel_controller.accept(window)
    wheel = window.wheels.get("wheel")
    assert wheel is not None
    readings = {0.0: 10.0, 2.0: 55.0}
    monkeypatch.setattr(wheel_display, "sample", lambda _w, _c, t: readings.get(t))
    monkeypatch.setattr(wheel_display, "_encoder_map", lambda _w, _s: None)
    window.wheels.set("wheel", dataclasses.replace(wheel, binding=EncoderBinding("e", "a", 10.0)))
    frame.update(now=FRAME + 2, t=2.0)
    bound = window.wheels.get("wheel")
    assert bound is not None
    ends = wheel_display._ends(window, bound, 2.0)
    assert ends is not None
    assert ends == pytest.approx(wheel.geometry.bar_ends(45.0))


def test_two_checks_measure_the_direction(window: MainWindow, monkeypatch, frame) -> None:
    """Clicks on a reversed encoder's footage settle its sign through the window."""
    _place(window, [0, 1, 2], WheelSpec("wheel", 36), monkeypatch)
    wheel_controller.accept(window)
    wheel = window.wheels.get("wheel")
    assert wheel is not None
    window.wheels.set("wheel", dataclasses.replace(wheel, binding=EncoderBinding("e", "a", 0.0)))
    camera = CAMERAS["Front"]
    for shown, turn in ((100, -47.0), (200, -133.0)):
        # The real wheel turned by -turn's encoder reading: a reversed encoder.
        pixels, in_front, facing = project_bars(TRUTH, TRUTH.bar_ends(turn), camera)
        seen = [i for i in range(len(pixels)) if in_front[i] and facing[i]]
        x, y = pixels[seen[len(seen) // 2], 0]
        monkeypatch.setattr(wheel_display, "sample", lambda _w, _c, _t, a=-turn: a)
        frame.update(now=shown, t=float(shown))
        wheel_controller.start_checking(window, "wheel")
        assert window._wheel_checking == "wheel"
        wheel_controller.on_clicked(window, VIDEOS["Front"], float(x), float(y))
        assert window._wheel_checking is None
    checked = window.wheels.get("wheel")
    assert checked is not None and checked.binding is not None
    binding = checked.binding
    assert binding.sign == -1.0
    assert binding.measured
    assert len(binding.checks) == 2


def test_a_new_session_forgets_its_wheels(window: MainWindow, monkeypatch) -> None:
    _place(window, [0, 1, 2], WheelSpec("wheel", 36), monkeypatch)
    wheel_controller.accept(window)
    wheel_controller.reset(window)
    assert len(window.wheels) == 0
    assert window.wheel_panel.isHidden()


def test_wheels_on_disk_are_adopted_once(window: MainWindow, monkeypatch, pose3d: Path) -> None:
    _place(window, [0, 1, 2], WheelSpec("wheel", 36), monkeypatch)
    wheel_controller.accept(window)
    wheel = window.wheels.get("wheel")
    window.wheels.clear()
    wheel_files.adopt(window)
    assert window.wheels.get("wheel") == wheel
