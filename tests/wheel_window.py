"""A running window wired to the synthetic wheel rig, for the wheel UI tests (D-113).

Plain functions, not fixtures: each test module keeps its own thin fixtures
over them, so pytest's fixture lookup and the linters both stay simple.

The panes are not decoded -- which frame is on screen is stubbed to the frame
the bars are clicked on -- because what is under test is the flow the window
runs, not decoding. The rig is ``tests/wheel_fixture.py``'s synthetic ground
truth, never recorded data.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread

from avialsync.core.wheel import WheelSpec
from avialsync.ui.controllers import (
    calibration_controller,
    rig_paths,
    wheel_controller,
    wheel_display,
)
from avialsync.ui.main_window import MainWindow
from avialsync.ui.wheel_dialogs import WheelSetup
from tests.wheel_fixture import CAMERAS, clicks_for

FRAME = 7
VIDEOS = {name: f"/rec/{name}.mp4" for name in CAMERAS}


def build_window(
    qtbot, monkeypatch, pose3d: Path, frame: dict[str, float], *, inline_jobs: bool = True
) -> MainWindow:
    """A window whose three cameras show *frame* and are calibrated to the rig.

    With *inline_jobs*, a background job (the wheel fit, D-123) runs to the end
    inside ``_run_job``, so a click's fit is there when the click returns. The
    real threaded path is exercised by the tests that pass ``False``.
    """
    win = MainWindow()
    qtbot.addWidget(win)
    if inline_jobs:
        monkeypatch.setattr(win, "_run_job", _run_inline)
    monkeypatch.setattr(rig_paths, "open_videos", lambda _w: list(VIDEOS.values()))
    monkeypatch.setattr(rig_paths, "frame_at", lambda _w, _t: frame["now"])
    monkeypatch.setattr(rig_paths, "pose3d_dir", lambda _w: pose3d)
    monkeypatch.setattr(wheel_display, "frame_and_time", lambda _w, _t: (frame["now"], frame["t"]))
    monkeypatch.setattr(wheel_display, "frame_master_time", lambda _w, f: float(f - FRAME))
    win._calibration_state = calibration_controller.CalibrationState(
        path=Path("calibration.toml"),
        cameras={VIDEOS[name]: model for name, model in CAMERAS.items()},
    )
    return win


def _run_inline(worker, label: str = "Working", configure=None) -> QThread:
    """``MainWindow._run_job`` without the thread: wire the worker, then run it here."""
    del label
    thread = QThread()
    if configure is not None:
        configure(thread)
    worker.run()
    return thread


def start_placing(
    window: MainWindow,
    monkeypatch,
    spec: WheelSpec | None = None,
    channel: tuple[str, str] | None = None,
) -> None:
    """Add Wheel, answering its dialog with *spec* and *channel*."""
    setup = WheelSetup(spec or WheelSpec("wheel", 36), channel=channel)
    monkeypatch.setattr(wheel_controller, "ask_wheel_setup", lambda *_a: setup)
    wheel_controller.toggled(window, True)


def click_point(window: MainWindow, step: int, views) -> None:
    """Select point *step* in the Wheels tab, then click it in each of *views*."""
    window.wheel_panel._point_buttons[step].click()
    for camera, x, y in views:
        assert wheel_controller.on_clicked(window, VIDEOS[camera], x, y)


def place(window: MainWindow, slots: list[int], spec: WheelSpec, monkeypatch) -> None:
    """Run Add Wheel with *spec*, clicking the bars in *slots* in every camera."""
    start_placing(window, monkeypatch, spec)
    for click in clicks_for(slots):
        for camera, x, y in click.views:
            assert wheel_controller.on_clicked(window, VIDEOS[camera], x, y)
