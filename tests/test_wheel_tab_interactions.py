"""Every control in the Wheels tab, driven the way a user drives it (D-113, D-116, D-122).

``test_wheel_controller.py`` checks the controller's rules; this module checks
that each button, field and combo in the tab actually reaches them -- a click
on a widget, not a call to the function behind it. A control that is wired to
nothing looks exactly like one that works until someone clicks it.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.pyramid import PyramidBuilder
from avialsync.core.timeline import TimeMap
from avialsync.core.wheel import EncoderBinding, WheelSpec
from avialsync.core.wheel_file import read_wheels
from avialsync.ui.controllers import wheel_controller, wheel_display
from avialsync.ui.main_window import MainWindow
from avialsync.ui.wheel_dialogs import WheelSetup
from tests.wheel_fixture import clicks_for
from tests.wheel_window import FRAME, VIDEOS, build_window, click_point, place, start_placing


@pytest.fixture
def pose3d(tmp_path) -> Path:
    return tmp_path / "pose-3d"


@pytest.fixture
def frame() -> dict[str, float]:
    return {"now": FRAME, "t": 0.0}


@pytest.fixture
def window(
    qapp: QApplication, qtbot, monkeypatch, pose3d: Path, frame: dict[str, float]
) -> MainWindow:
    win = build_window(qtbot, monkeypatch, pose3d, frame)
    yield win
    if isValid(win):
        win.close()


def _two_bars(window: MainWindow, monkeypatch, channel=None) -> None:
    start_placing(window, monkeypatch, channel=channel)
    for step, click in enumerate(clicks_for([0, 1])):
        click_point(window, step, click.views)


# ── starting and leaving a placement ────────────────────────────────


def test_add_wheel_button_in_the_tab_starts_and_stops_placing(
    window: MainWindow, monkeypatch
) -> None:
    button = window.wheel_tab.add_button
    assert button.text() == window._act_add_wheel.text()
    assert not button.isEnabled(), "greyed until two cameras are open (rule 15)"
    assert "two camera videos" in button.toolTip()

    monkeypatch.setattr(window.video_grid, "pane_paths", lambda: list(VIDEOS.values()))
    window._refresh_action_availability()
    monkeypatch.setattr(
        wheel_controller, "ask_wheel_setup", lambda *_a: WheelSetup(WheelSpec("wheel", 36), None)
    )
    assert button.isEnabled()

    button.click()
    assert window._wheel_placement is not None and button.isChecked()

    button.click()
    assert window._wheel_placement is None and not button.isChecked()


def test_cancelling_the_setup_dialog_leaves_add_wheel_unchecked(
    window: MainWindow, monkeypatch
) -> None:
    monkeypatch.setattr(wheel_controller, "ask_wheel_setup", lambda *_a: None)
    window._act_add_wheel.trigger()
    assert window._wheel_placement is None
    assert not window._act_add_wheel.isChecked()


# ── the review while placing ─────────────────────────────────────────


def test_point_buttons_select_the_end_the_next_click_places(
    window: MainWindow, monkeypatch
) -> None:
    start_placing(window, monkeypatch)
    buttons = window.wheel_panel._point_buttons
    buttons[3].click()
    placement = window._wheel_placement
    assert placement is not None and placement.step == 3
    assert [button.isChecked() for button in buttons] == [False, False, False, True, False, False]

    click = clicks_for([0, 1])[3]
    camera, x, y = click.views[0]
    click_point(window, 3, [(camera, x, y)])
    assert placement.count(3) == 1 and placement.count(0) == 0
    assert buttons[3].text() == "2B  1/3"


def test_next_point_walks_to_3b_and_then_stops(window: MainWindow, monkeypatch) -> None:
    start_placing(window, monkeypatch)
    panel = window.wheel_panel
    for expected in range(1, 6):
        panel._next.click()
        assert window._wheel_placement.step == expected
    assert not panel._next.isEnabled()


def test_undo_click_button_takes_back_the_last_click(window: MainWindow, monkeypatch) -> None:
    start_placing(window, monkeypatch)
    panel = window.wheel_panel
    assert not panel._undo.isEnabled()
    camera, x, y = clicks_for([0])[0].views[0]
    click_point(window, 0, [(camera, x, y)])
    assert panel._undo.isEnabled()

    panel._undo.click()

    assert window._wheel_placement.clicks == {}
    assert not panel._undo.isEnabled()


def test_flip_side_button_picks_the_mirrored_wheel(window: MainWindow, monkeypatch) -> None:
    start_placing(window, monkeypatch)
    panel = window.wheel_panel
    assert not panel._flip.isEnabled(), "nothing to flip before a fit"
    for step, click in enumerate(clicks_for([0, 1])):
        click_point(window, step, click.views)
    placement = window._wheel_placement
    before = placement.fit.geometry.centre
    assert panel._flip.isEnabled()

    panel._flip.click()

    assert placement.flipped
    assert placement.fit.geometry.centre != pytest.approx(before)


def test_go_to_frame_button_seeks_back_to_the_labelled_frame(
    window: MainWindow, monkeypatch
) -> None:
    seeks: list[tuple[float, bool]] = []
    monkeypatch.setattr(window.player, "seek", lambda t, exact=True: seeks.append((t, exact)))
    monkeypatch.setattr(wheel_display, "frame_master_time", lambda _w, f: 100.0 + f)
    start_placing(window, monkeypatch)

    window.wheel_panel._frame.click()

    assert seeks == [(100.0 + FRAME, True)]


def test_review_fields_refit_the_placement(window: MainWindow, monkeypatch) -> None:
    _two_bars(window, monkeypatch)
    fields = window.wheel_panel._review_spec
    fields.units.setCurrentIndex(fields.units.findData("mm"))
    fields.radius.setValue(100.0)
    fields.bars.setValue(40)

    placement = window._wheel_placement
    assert placement.spec == WheelSpec("wheel", 40, 100.0, "mm")
    assert placement.fit is not None and placement.fit.geometry.bar_count == 40


def test_generating_the_wheel_is_announced_once(window: MainWindow, monkeypatch) -> None:
    """The fit runs on every click; the user is told when it first produces a wheel."""
    start_placing(window, monkeypatch)
    clicks = clicks_for([0, 1, 2])
    for step, click in enumerate(clicks[:3]):
        click_point(window, step, click.views)
    assert "Wheel generated" not in window.notifications.message

    click_point(window, 3, clicks[3].views)
    assert "Wheel generated from 2 bars" in window.notifications.message

    window.notifications.clear_all()
    click_point(window, 4, clicks[4].views)
    assert window.notifications.message == "", "an unchanged preview is not re-announced"


# ── Done Labelling and Discard Clicks ───────────────────────────────


def test_done_labelling_reads_the_encoder_from_its_real_cache(
    window: MainWindow, monkeypatch, tmp_path: Path, pose3d: Path
) -> None:
    """No stub between the button and the encoder's pyramid: the path a user takes."""
    cache = tmp_path / "encoder.avialcache"
    cache.mkdir()
    times = np.linspace(-1.0, 1.0, 201)
    PyramidBuilder(cache, "angle").build_and_save(times, 30.0 + 10.0 * times)
    monkeypatch.setattr(wheel_display, "_encoder_map", lambda _w, _s: (cache, TimeMap()))
    _two_bars(window, monkeypatch, channel=("encoder.csv", "angle"))

    window.wheel_panel._accept.click()

    wheel = window.wheels.get("wheel")
    assert wheel is not None and window._wheel_placement is None
    assert wheel.binding == EncoderBinding("encoder.csv", "angle", pytest.approx(30.0))
    assert read_wheels(pose3d)[0] == [wheel]


def test_done_labelling_without_an_encoder_reading_still_saves(
    window: MainWindow, monkeypatch, pose3d: Path
) -> None:
    monkeypatch.setattr(wheel_display, "_encoder_map", lambda _w, _s: None)
    _two_bars(window, monkeypatch, channel=("encoder.csv", "angle"))

    window.wheel_panel._accept.click()

    wheel = window.wheels.get("wheel")
    assert wheel is not None and wheel.binding is None
    assert read_wheels(pose3d)[0] == [wheel]


def test_done_labelling_is_greyed_with_its_reason_until_2b(window: MainWindow, monkeypatch) -> None:
    start_placing(window, monkeypatch)
    accept = window.wheel_panel._accept
    for step, click in enumerate(clicks_for([0, 1])[:3]):
        click_point(window, step, click.views)
    assert not accept.isEnabled()
    assert accept.toolTip(), "a greyed Done Labelling says what it is waiting for"


# ── a placed wheel's row ─────────────────────────────────────────────


@pytest.fixture
def placed(window: MainWindow, monkeypatch):
    place(window, [0, 1], WheelSpec("wheel", 36), monkeypatch)
    window.wheel_panel._accept.click()
    wheel = window.wheels.get("wheel")
    assert wheel is not None
    return window.wheel_panel._rows["wheel"]


def _bind(window: MainWindow, wheel) -> None:
    """Give the placed wheel an encoder, as if one had been chosen in Add Wheel."""
    window.wheels.set("wheel", dataclasses.replace(wheel, binding=EncoderBinding("e", "a", 0.0)))


def test_row_bar_count_refits_as_one_undo_step(window: MainWindow, placed) -> None:
    placed.spec.bars.setValue(40)
    assert window.wheels.get("wheel").spec.bar_count == 40
    assert window.document.undo(window._mutations)
    assert window.wheels.get("wheel").spec.bar_count == 36


def test_row_direction_and_ratio_edit_the_encoder(window: MainWindow, placed) -> None:
    wheel = window.wheels.get("wheel")
    _bind(window, wheel)
    row = window.wheel_panel._rows["wheel"]
    row.direction.setCurrentIndex(1)
    row.ratio.setValue(2.5)
    binding = window.wheels.get("wheel").binding
    assert binding.sign < 0 and binding.ratio == pytest.approx(2.5)
    assert not binding.measured, "a typed direction is not a measured one"


def test_row_verify_here_enters_and_leaves_checking(window: MainWindow, placed) -> None:
    wheel = window.wheels.get("wheel")
    _bind(window, wheel)
    row = window.wheel_panel._rows["wheel"]
    row.verify.click()
    assert window._wheel_checking == "wheel"
    assert window.wheel_panel._rows["wheel"].verify.text() == "Click a Bar End…"
    window.wheel_panel._rows["wheel"].verify.click()
    assert window._wheel_checking is None


def test_row_replace_starts_a_placement_that_swaps_the_wheel_in(
    window: MainWindow, monkeypatch, placed
) -> None:
    placed.replace.click()
    placement = window._wheel_placement
    assert placement is not None and placement.replacing == "wheel"
    for step, click in enumerate(clicks_for([0, 1])):
        click_point(window, step, click.views)
    window.wheel_panel._accept.click()
    assert [wheel.name for wheel in window.wheels] == ["wheel"]


def test_row_remove_takes_the_wheel_out_and_undo_brings_it_back(window: MainWindow, placed) -> None:
    placed.remove.click()
    assert window.wheels.get("wheel") is None
    assert window.document.undo(window._mutations)
    assert window.wheels.get("wheel") is not None


# ── generation off the UI thread (D-123) ────────────────────────────


@pytest.fixture
def threaded(
    qapp: QApplication, qtbot, monkeypatch, pose3d: Path, frame: dict[str, float]
) -> MainWindow:
    """A window whose wheel fits run on real job threads, as in the app."""
    win = build_window(qtbot, monkeypatch, pose3d, frame, inline_jobs=False)
    yield win
    if isValid(win):
        win.close()


def _idle(window: MainWindow) -> bool:
    placement = window._wheel_placement
    return (placement is None or not placement.fitting) and not window._job_manager.is_busy()


def test_the_wheel_is_generated_as_a_registered_background_job(
    threaded: MainWindow, monkeypatch, qtbot
) -> None:
    window = threaded
    labels: list[str] = []
    window._job_manager.jobs_changed.connect(
        lambda: labels.extend(job.label for job in window._job_manager.jobs())
    )
    start_placing(window, monkeypatch)
    for step, click in enumerate(clicks_for([0, 1])):
        click_point(window, step, click.views)

    placement = window._wheel_placement
    assert placement.fitting, "the click returns before the fit does"
    assert window.wheel_panel._summary.text() == "Generating wheel…"
    assert not window.wheel_panel._accept.isEnabled(), "Done waits for the latest clicks' fit"
    assert "Generating wheel wheel" in labels

    qtbot.waitUntil(lambda: _idle(window), timeout=10_000)

    assert placement.fit is not None
    assert window.wheel_panel._accept.isEnabled()
    assert wheel_display.pane_drawing(window, VIDEOS["Front"], 0.0).bars


def test_clicks_during_a_fit_are_fitted_when_it_returns(
    threaded: MainWindow, monkeypatch, qtbot
) -> None:
    window = threaded
    start_placing(window, monkeypatch)
    for step, click in enumerate(clicks_for([0, 1, 2])):
        click_point(window, step, click.views)

    qtbot.waitUntil(lambda: _idle(window), timeout=10_000)

    placement = window._wheel_placement
    assert placement.fit is not None and len(placement.fit.indices) == 3
    window.wheel_panel._accept.click()
    assert len(window.wheels.get("wheel").fit.indices) == 3


def test_a_placed_wheels_refit_runs_in_the_background(
    threaded: MainWindow, monkeypatch, qtbot
) -> None:
    window = threaded
    start_placing(window, monkeypatch)
    for step, click in enumerate(clicks_for([0, 1])):
        click_point(window, step, click.views)
    qtbot.waitUntil(lambda: _idle(window), timeout=10_000)
    window.wheel_panel._accept.click()

    window.wheel_panel._rows["wheel"].spec.bars.setValue(40)
    assert window.wheels.get("wheel").spec.bar_count == 36, "not applied before the fit"
    qtbot.waitUntil(lambda: window.wheels.get("wheel").spec.bar_count == 40, timeout=10_000)
    qtbot.waitUntil(lambda: _idle(window), timeout=10_000)


# ── showing the wheel, and the encoder's latency ─────────────────────


def test_show_wheel_check_box_is_view_overlays_wheel_entry(window: MainWindow) -> None:
    """One switch, reachable from two places: they cannot disagree (rules 13, 15)."""
    box = window.wheel_tab.show_wheel
    action = window._overlay_actions["tracking.wheel"]
    assert box.text() == action.text() and box.isChecked()

    box.click()
    assert not action.isChecked()
    assert not window.overlay_state.is_visible("tracking.wheel")

    assert window.document.undo(window._mutations)
    assert box.isChecked(), "undo reaches the check box as well as the menu"

    action.trigger()
    assert not box.isChecked(), "the menu reaches the check box"


def test_out_of_sight_bars_check_box_follows_its_overlay(window: MainWindow) -> None:
    box = window.wheel_tab.show_hidden_bars
    assert not box.isChecked()
    box.click()
    assert window.overlay_state.is_visible("tracking.wheel_hidden")


@pytest.fixture
def encoder(window: MainWindow, tmp_path: Path) -> str:
    path = "/rec/encoder_log.txt"
    window.sidebar.add_sensor(path, ["encoder_angle"])
    window._sensor_cache_dirs[path] = tmp_path / "encoder.avialcache"
    return path


def test_encoder_offset_field_is_the_encoders_own_offset(
    window: MainWindow, monkeypatch, encoder: str
) -> None:
    place(window, [0, 1], WheelSpec("wheel", 36), monkeypatch)
    window.wheel_panel._accept.click()
    wheel = window.wheels.get("wheel")
    window.wheels.set(
        "wheel",
        dataclasses.replace(wheel, binding=EncoderBinding(encoder, "encoder_angle", 0.0)),
    )
    field = window.wheel_panel._rows["wheel"].offset
    assert field.isEnabled() and field.value() == 0.0

    field.setValue(0.12)

    assert window.sidebar.sensor_mapping(encoder)[0] == pytest.approx(0.12)
    assert window.document.undo(window._mutations)
    assert window.sidebar.sensor_mapping(encoder)[0] == 0.0
    assert window.wheel_panel._rows["wheel"].offset.value() == 0.0, "undo shows here too"

    window.sidebar.set_sensor_mapping(encoder, -0.05, 0.0)
    window._on_sensor_mapping_changed(encoder, -0.05, 0.0)
    assert window.wheel_panel._rows["wheel"].offset.value() == pytest.approx(-0.05)


def test_encoder_offset_is_greyed_without_a_loaded_encoder(window: MainWindow, monkeypatch) -> None:
    place(window, [0, 1], WheelSpec("wheel", 36), monkeypatch)
    window.wheel_panel._accept.click()
    assert not window.wheel_panel._rows["wheel"].offset.isEnabled()


# ── bar diameter (D-128) ─────────────────────────────────────────────


def test_dragging_the_diameter_previews_and_releasing_commits_once(
    window: MainWindow, monkeypatch, pose3d: Path
) -> None:
    place(window, [0, 1], WheelSpec("wheel", 36), monkeypatch)
    window.wheel_panel._accept.click()
    slider = window.wheel_panel._rows["wheel"].diameter.slider
    depth = len(window.document)

    slider.setSliderDown(True)
    slider.setSliderPosition(100)

    assert window.wheels.get("wheel").bar_diameter is None, "a drag records nothing"
    assert len(window.document) == depth
    preview = window._wheel_diameter_preview["wheel"]
    assert preview > 0
    assert wheel_display.scene(window, 0.0)[0][2] == pytest.approx(preview), "drawn in 3D"

    slider.setSliderDown(False)

    wheel = window.wheels.get("wheel")
    assert wheel.bar_diameter == pytest.approx(preview)
    assert len(window.document) == depth + 1
    assert read_wheels(pose3d)[0] == [wheel]
    assert window._wheel_diameter_preview == {}
    assert wheel_display.scene(window, 0.0)[0][2] == pytest.approx(preview)

    assert window.document.undo(window._mutations)
    assert window.wheels.get("wheel").bar_diameter is None


def test_a_typed_diameter_is_kept_and_zero_clears_it(window: MainWindow, monkeypatch) -> None:
    place(window, [0, 1], WheelSpec("wheel", 36), monkeypatch)
    window.wheel_panel._accept.click()
    field = window.wheel_panel._rows["wheel"].diameter
    assert field.spin.text() == "Not set"

    field.spin.setValue(5.0)
    assert window.wheels.get("wheel").bar_diameter == pytest.approx(5.0)
    assert window.wheel_panel._rows["wheel"].diameter.spin.value() == pytest.approx(5.0)

    field.spin.setValue(0.0)
    assert window.wheels.get("wheel").bar_diameter is None
