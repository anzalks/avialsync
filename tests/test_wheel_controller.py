"""Add Wheel through the running window: click, review, accept, undo, check (D-113).

The panes are not decoded here -- which frame is on screen is stubbed to the
frame the bars are clicked on -- because what is under test is the flow the
window runs: clicks reaching the placement, the fit appearing in the Wheels
tab, Done Labelling being one undo step, the file written from the mutation funnel,
and the encoder check settling the direction. The geometry itself is judged
against ground truth in ``test_wheel.py``, whose synthetic rig these tests reuse.
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.calibration import Calibration, write_calibration
from avialsync.core.commands import SetWheelCommand
from avialsync.core.wheel import EncoderBinding, Wheel, WheelSpec, project_bars
from avialsync.core.wheel_file import read_wheels, wheel_path, write_wheel
from avialsync.core.wheel_fit import fit_wheel
from avialsync.ui import recovery
from avialsync.ui.controllers import (
    calibration_controller,
    rig_paths,
    wheel_controller,
    wheel_display,
    wheel_edits,
    wheel_files,
    wheel_placement,
)
from avialsync.ui.main_window import MainWindow
from avialsync.ui.wheel_dialogs import WheelSetup
from tests.wheel_fixture import CAMERAS, TRUTH, clicks_for
from tests.wheel_window import (
    FRAME,
    VIDEOS,
    build_window,
    click_point,
    place,
    start_placing,
)


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
    win = build_window(qtbot, monkeypatch, pose3d, frame)
    yield win
    if isValid(win):
        win.close()


_place = place


def test_clicking_two_bars_offers_a_wheel_to_accept(window: MainWindow, monkeypatch) -> None:
    _place(window, [0, 1], WheelSpec("wheel", 36), monkeypatch)
    placement = window._wheel_placement
    assert placement is not None and placement.fit is not None
    assert window._act_add_wheel.isChecked()
    assert not window.wheel_panel.isHidden()
    assert not window.wheel_panel._review.isHidden()
    assert window.wheel_panel._accept.isEnabled()
    assert window._left_tabs.currentWidget() is window.wheel_tab
    assert window.wheel_panel._accept.text() == "Done Labelling"


def test_done_labelling_saves_and_exits_click_mode(window: MainWindow, monkeypatch) -> None:
    _place(window, [0, 1], WheelSpec("wheel", 36), monkeypatch)
    window.wheel_panel._accept.click()
    assert window._wheel_placement is None
    assert not window._act_add_wheel.isChecked()
    assert window.wheels.get("wheel") is not None


def test_a_poor_preview_is_drawn_and_can_be_finished(
    window: MainWindow, monkeypatch, pose3d: Path
) -> None:
    """D-123: however poor the fit, the user sees it, and Done Labelling saves it."""
    _place(window, [0, 1], WheelSpec("wheel", 36), monkeypatch)
    placement = window._wheel_placement
    assert placement is not None and placement.fit is not None
    placement.fit = dataclasses.replace(
        placement.fit,
        residuals=tuple(
            dataclasses.replace(residual, pixels=60.0) for residual in placement.fit.residuals
        ),
    )
    wheel_display.refresh(window)
    assert window.wheel_panel._accept.isEnabled()
    summary = window.wheel_panel._summary.text()
    assert summary.startswith("Poor fit.") and "saves this wheel as drawn" in summary
    drawing = wheel_display.pane_drawing(window, VIDEOS["Front"], 0.0)
    assert drawing is not None and drawing.clicks and drawing.bars
    assert wheel_display.scene(window, 0.0)

    window.wheel_panel._accept.click()

    wheel = window.wheels.get("wheel")
    assert wheel is not None and window._wheel_placement is None
    assert read_wheels(pose3d)[0] == [wheel], "the clicks reach the wheel file"
    assert wheel_display.pane_drawing(window, VIDEOS["Front"], 0.0).bars
    assert wheel_display.scene(window, 0.0)
    assert "fits your clicks poorly" in window.notifications.message
    assert window.notifications.action_label == "Re-place"


def test_a_poor_saved_wheel_is_drawn_and_can_be_replaced(window: MainWindow, monkeypatch) -> None:
    _place(window, [0, 1], WheelSpec("wheel", 36), monkeypatch)
    wheel_controller.accept(window)
    wheel = window.wheels.get("wheel")
    assert wheel is not None
    poor_fit = dataclasses.replace(
        wheel.fit,
        residuals=tuple(dataclasses.replace(r, pixels=60.0) for r in wheel.fit.residuals),
    )
    poor = dataclasses.replace(wheel, fit=poor_fit)
    window.document.execute(SetWheelCommand(wheel.name, wheel, poor), window._mutations)
    assert wheel_display.pane_drawing(window, VIDEOS["Front"], 0.0).bars
    assert wheel_display.scene(window, 0.0)
    row = window.wheel_panel._rows["wheel"]
    assert row.fit.text().startswith("Poor fit.")
    assert row.replace.isEnabled()


def test_a_radius_in_the_wrong_units_gives_way_to_the_clicks(
    window: MainWindow, monkeypatch
) -> None:
    """The reported case: a radius typed in cm against a calibration in mm."""
    _place(window, [0, 1], WheelSpec("wheel", 36, radius=10.0, units="mm"), monkeypatch)
    placement = window._wheel_placement
    assert placement is not None and placement.fit is not None
    assert placement.fit.geometry.radius == pytest.approx(TRUTH.radius, rel=0.02)
    assert placement.quality_issue is None
    summary = window.wheel_panel._summary.text()
    assert "imply" in summary and "10× apart" in summary
    assert wheel_display.pane_drawing(window, VIDEOS["Front"], 0.0).bars


def test_discard_clicks_exits_without_wheel(window: MainWindow, monkeypatch) -> None:
    _place(window, [0, 1], WheelSpec("wheel", 36), monkeypatch)
    window.wheel_panel._cancel.click()
    assert window._wheel_placement is None
    assert window.wheels.get("wheel") is None


def test_wheel_button_uses_the_edit_action(window: MainWindow, monkeypatch) -> None:
    """The new entry point has one label, tooltip, state and command."""
    button = window.view_toolbar.add_wheel_button
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


def test_projected_click_target_follows_display_scale() -> None:
    """A projected diamond remains easy to click in a small or zoomed pane."""
    scale = {"value": 0.25}
    pane = SimpleNamespace(
        paint_canvas=SimpleNamespace(width=lambda: 200, height=lambda: 150),
        surface=SimpleNamespace(frame_geometry=lambda _w, _h: (scale["value"], 0, 0)),
    )
    window = SimpleNamespace(
        video_grid=SimpleNamespace(pane_paths=lambda: ["camera.mp4"], panes=[pane])
    )
    assert wheel_display.projected_hit_radius(window, "camera.mp4") == 32.0
    scale["value"] = 2.0
    assert wheel_display.projected_hit_radius(window, "camera.mp4") == 4.0


def test_two_views_project_into_the_third_without_inventing_a_click(
    window: MainWindow, monkeypatch
) -> None:
    """Projection is feedback from triangulation, never another observation."""
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
    assert window.wheel_panel._accept.isEnabled()
    camera, x, y = last.views[2]
    drawing = wheel_display.pane_drawing(window, VIDEOS[camera], 0.0)
    assert drawing is not None
    assert drawing.projections[-1][0] == "2b"
    assert all(label != "2b" for label, *_ in drawing.clicks)
    assert len(placement.clicks[(1, "right")].views) == 2
    wheel_controller.select_end(window, 0)
    wheel_controller.on_clicked(window, VIDEOS[camera], x, y)
    assert placement.step == 4
    assert window.wheel_panel._accept.isEnabled()
    drawing = wheel_display.pane_drawing(window, VIDEOS[camera], 0.0)
    assert drawing is not None
    assert all(label != "2b" for label, *_ in drawing.projections)
    assert drawing.clicks[-1][0] == "2b"
    wheel_controller.undo_click(window)
    drawing = wheel_display.pane_drawing(window, VIDEOS[camera], 0.0)
    assert drawing is not None and drawing.projections[-1][0] == "2b"
    assert len(placement.clicks[(1, "right")].views) == 2


def test_camera_first_order_can_complete_two_bars(
    window: MainWindow, monkeypatch, pose3d: Path
) -> None:
    monkeypatch.setattr(
        wheel_controller,
        "ask_wheel_setup",
        lambda *_a: WheelSetup(WheelSpec("wheel", 36), channel=None),
    )
    wheel_controller.toggled(window, True)
    clicks = clicks_for([0, 1])
    for camera in ("Front", "Left"):
        for step, click in enumerate(clicks):
            wheel_controller.select_end(window, step)
            x, y = next((x, y) for name, x, y in click.views if name == camera)
            wheel_controller.on_clicked(window, VIDEOS[camera], x, y)
        if camera == "Front":
            assert window._wheel_placement is not None
            assert not window._wheel_placement.estimates
    placement = window._wheel_placement
    assert placement is not None and placement.ready(set(CAMERAS))
    assert window.wheel_panel._accept.isEnabled()
    assert [button.text() for button in window.wheel_panel._point_buttons[:4]] == [
        "1A  2/3",
        "1B  2/3",
        "2A  2/3",
        "2B  2/3",
    ]
    window.wheel_panel._accept.click()
    wheel = window.wheels.get("wheel")
    assert wheel is not None
    assert all(len(click.views) == 2 for click in wheel.clicks)
    saved, _removed = read_wheels(pose3d)
    assert saved == [wheel]
    assert all(len(click.views) == 2 for click in saved[0].clicks)
    assert len(wheel_display.pane_drawing(window, VIDEOS["Right"], 0.0).bars) > 3


def test_next_point_keeps_a_single_camera_click_visible(window: MainWindow, monkeypatch) -> None:
    monkeypatch.setattr(
        wheel_controller,
        "ask_wheel_setup",
        lambda *_a: WheelSetup(WheelSpec("wheel", 36), channel=None),
    )
    wheel_controller.toggled(window, True)
    clicks = clicks_for([0])
    for step, click in enumerate(clicks):
        x, y = next((x, y) for name, x, y in click.views if name == "Front")
        wheel_controller.on_clicked(window, VIDEOS["Front"], x, y)
        drawing = wheel_display.pane_drawing(window, VIDEOS["Front"], 0.0)
        assert drawing is not None and drawing.clicks[-1][0] == f"1{'ab'[step]}"
        assert not drawing.projections
        window.wheel_panel._next.click()
    placement = window._wheel_placement
    assert placement is not None and placement.step == 2
    assert placement.count(0) == placement.count(1) == 1
    assert not window.wheel_panel._accept.isEnabled()


def test_missing_view_projection_matches_synthetic_truth() -> None:
    click = clicks_for([0])[0]
    placement = wheel_placement.Placement(WheelSpec("wheel", 36), None, FRAME)
    placement.clicks[(0, click.side)] = click.without_view("Right")

    wheel_placement.estimate_missing(placement, CAMERAS)

    projected = placement.estimates[(0, click.side, "Right")]
    actual = next((x, y) for name, x, y in click.views if name == "Right")
    assert sum((a - b) ** 2 for a, b in zip(projected, actual, strict=True)) ** 0.5 < 3.0
    assert len(placement.clicks[(0, click.side)].views) == 2


def test_three_bars_is_the_maximum_guided_input(window: MainWindow, monkeypatch) -> None:
    _place(window, [0, 1, 2], WheelSpec("wheel", 36), monkeypatch)
    placement = window._wheel_placement
    assert placement is not None and placement.step == 6
    before = placement.ordered()
    wheel_controller.on_clicked(window, VIDEOS["Front"], 1.0, 2.0)
    assert placement.ordered() == before
    assert "review the fit" in window.wheel_panel._instruction.text().lower()


def test_done_labelling_is_live_from_point_2b_through_all_three_bars(
    window: MainWindow, monkeypatch, pose3d: Path
) -> None:
    """Two views per point: Done turns on with 2B's second view and stays on for bar 3."""
    start_placing(window, monkeypatch)
    panel = window.wheel_panel
    enabled = []
    for step, click in enumerate(clicks_for([0, 1, 2])):
        panel._point_buttons[step].click()
        for camera, x, y in click.views[:2]:
            wheel_controller.on_clicked(window, VIDEOS[camera], x, y)
            enabled.append(panel._accept.isEnabled())
        if step == 3:
            assert "Bar 3 (3A, 3B) is optional" in panel._summary.text()
    assert enabled == [False] * 7 + [True] * 5
    placement = window._wheel_placement
    assert placement is not None and placement.fit is not None
    assert len(placement.fit.indices) == 3, "a complete third bar joins the fit"

    panel._accept.click()

    wheel = window.wheels.get("wheel")
    assert wheel is not None and len(wheel.fit.indices) == 3 and len(wheel.clicks) == 6
    assert read_wheels(pose3d)[0] == [wheel]
    assert window._wheel_placement is None and not window._act_add_wheel.isChecked()
    assert wheel_display.pane_drawing(window, VIDEOS["Right"], 0.0).bars


def test_a_third_bar_clicked_backwards_is_left_out_and_done_stays_live(
    window: MainWindow, monkeypatch, pose3d: Path
) -> None:
    """A third bar that cannot be fitted must not take Done Labelling away."""
    start_placing(window, monkeypatch)
    clicks = clicks_for([0, 1, 2])
    for step, click in enumerate(clicks[:4]):
        click_point(window, step, click.views)
    # A and B swapped on bar 3: the fit refuses that bar, not the wheel.
    click_point(window, 4, clicks[5].views)
    click_point(window, 5, clicks[4].views)
    placement = window._wheel_placement
    assert placement is not None and placement.fit is not None
    assert len(placement.fit.indices) == 2
    assert "left out of the fit" in window.wheel_panel._summary.text()
    assert window.wheel_panel._accept.isEnabled()

    window.wheel_panel._accept.click()

    wheel = window.wheels.get("wheel")
    assert wheel is not None and len(wheel.clicks) == 6, "bar 3's clicks are kept"
    assert len(wheel.fit.indices) == 2
    assert read_wheels(pose3d)[0] == [wheel]
    assert wheel_display.pane_drawing(window, VIDEOS["Front"], 0.0).bars


def test_a_stepped_over_third_bar_is_used_as_clicked(window: MainWindow, monkeypatch) -> None:
    """Clicked bars are neighbours by declaration; a skipped one shows as click error."""
    _place(window, [0, 1, 3], WheelSpec("wheel", 36), monkeypatch)
    placement = window._wheel_placement
    assert placement is not None and placement.fit is not None
    assert sorted(abs(i) for i in placement.fit.indices) == [0, 1, 2]
    assert placement.fit.max_px > 20.0, "the skipped bar cannot hide"
    assert window.wheel_panel._accept.isEnabled()
    assert wheel_display.pane_drawing(window, VIDEOS["Front"], 0.0).bars


def test_started_third_bar_does_not_block_two_complete_bars(
    window: MainWindow, monkeypatch, pose3d: Path
) -> None:
    _place(window, [0, 1], WheelSpec("wheel", 36), monkeypatch)
    click = clicks_for([0, 1, 2])[4]
    camera, x, y = click.views[0]
    wheel_controller.on_clicked(window, VIDEOS[camera], x, y)
    placement = window._wheel_placement
    assert placement is not None and placement.fit is not None
    assert window.wheel_panel._accept.isEnabled()
    assert "incomplete third bar" in window.wheel_panel._summary.text().lower()
    window.wheel_panel._accept.click()
    wheel = window.wheels.get("wheel")
    assert wheel is not None
    assert len(wheel.fit.indices) == 2
    assert len(wheel.clicks) == 5
    assert read_wheels(pose3d)[0] == [wheel]


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
    wheel_edits.edit_spec(window, "wheel", 36, "mm", 100.0)
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


def test_video_only_recording_rediscovers_its_saved_wheel(qapp, qtbot, tmp_path: Path) -> None:
    """A generic recording needs no pose-source callback to find its sidecar."""
    video = tmp_path / "camera_1.mp4"
    shutil.copyfile(Path("tests/fixtures/videos/camera_1.mp4"), video)
    spec = WheelSpec("wheel", 36)
    clicks = clicks_for([0, 1])
    wheel = Wheel(spec, FRAME, clicks, fit_wheel(spec, clicks, CAMERAS))
    write_wheel(tmp_path / "pose-3d", wheel)
    win = MainWindow()
    qtbot.addWidget(win)

    win._load_video(video)
    qtbot.waitUntil(lambda: win.wheels.get("wheel") is not None, timeout=10_000)

    assert not win._pose_3d_sources
    assert win.wheels.get("wheel") == wheel
    win.close()


def test_generic_cameras_and_tracking_share_one_wheel_folder(tmp_path: Path) -> None:
    recording = tmp_path / "recording"
    videos = [
        str(recording / "front" / "camera.mp4"),
        str(recording / "side" / "camera.mp4"),
    ]
    window = SimpleNamespace(
        video_grid=SimpleNamespace(pane_paths=lambda: videos),
        _pose_3d_sources={},
    )

    assert rig_paths.pose3d_dir(window) == recording / "pose-3d"
    window._pose_3d_sources = {str(recording / "tracking" / "points.csv"): []}
    assert rig_paths.pose3d_dir(window) == recording / "pose-3d"


def test_a_camera_opened_later_joins_the_quiet_calibration(
    qapp: QApplication, qtbot, monkeypatch, tmp_path: Path
) -> None:
    """Reopening a session: panes arrive one by one, and the last must draw too."""
    folder = tmp_path / "pose-3d"
    folder.mkdir()
    write_calibration(folder / "calibration.toml", Calibration(cameras=tuple(CAMERAS.values())))
    win = MainWindow()
    qtbot.addWidget(win)
    open_now = [VIDEOS["Front"], VIDEOS["Left"]]
    monkeypatch.setattr(rig_paths, "open_videos", lambda _w: list(open_now))
    monkeypatch.setattr(rig_paths, "pose3d_dir", lambda _w: folder)

    calibration_controller.calibration_quietly(win)
    assert set(win._calibration_state.cameras) == set(open_now)

    open_now.append(VIDEOS["Right"])
    calibration_controller.calibration_quietly(win)
    assert set(win._calibration_state.cameras) == set(VIDEOS.values())
    win.close()
