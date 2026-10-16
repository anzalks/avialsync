"""Fresh-window and real-worker regressions for current-format physical props."""

from __future__ import annotations

import dataclasses
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QThread
from pytestqt.qtbot import QtBot

from avialsync.core.physical_props import Ladder
from avialsync.core.prop_file import read_props, write_prop
from avialsync.core.prop_write_queue import PropWriteQueue
from avialsync.core.timeline import TimeMap
from avialsync.engine import prop_file_worker
from avialsync.engine.prop_file_worker import PropFileWriteWorker
from avialsync.ui import prop_context
from avialsync.ui.controllers import rig_paths, wheel_display
from avialsync.ui.main_window import MainWindow
from tests.test_prop_context import saved_wheel
from tests.wheel_window import _run_inline


@pytest.mark.parametrize("has_encoder", [False, True])
def test_moved_current_wheel_reopens_in_one_camera_without_calibration(
    qtbot: QtBot, tmp_path: Path, has_encoder: bool
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    shutil.copyfile("tests/fixtures/videos/camera_1.mp4", original / "Front.mp4")
    wheel = saved_wheel(original, binding=has_encoder, frame=7)
    write_prop(original / "pose-3d", wheel)
    moved = tmp_path / "moved"
    shutil.move(str(original), moved)
    window = MainWindow()
    qtbot.addWidget(window)
    video = str(moved / "Front.mp4")
    window._load_video(Path(video))
    qtbot.waitUntil(
        lambda: window.wheels.get("wheel") is not None and video in window._video_frame_times,
        timeout=15000,
    )
    assert window._calibration_state is None
    placed_time = float(window._video_frame_times[video][7])
    window.clock.seek(placed_time)
    assert wheel_display.pane_drawing(window, video, placed_time) is not None
    assert wheel_display.scene(window, placed_time)
    loaded = window.wheels.get("wheel")
    assert loaded is not None
    assert loaded.context.cameras[0].source == video
    if has_encoder:
        assert loaded.binding is not None
        assert loaded.binding.source_id == str(moved / "encoder.csv")
    window.close()


def test_reference_camera_survives_changed_pane_order(tmp_path: Path) -> None:
    wheel = saved_wheel(tmp_path, frame=15)
    front, left = str(tmp_path / "Front.mp4"), str(tmp_path / "Left.mp4")
    paths = [left, front]
    panes = [
        SimpleNamespace(time_map=TimeMap(), frame_record_at=lambda t: (30, t)),
        SimpleNamespace(time_map=TimeMap(), frame_record_at=lambda t: (15, t)),
    ]
    window = SimpleNamespace(
        video_grid=SimpleNamespace(panes=panes),
        rig_paths=rig_paths.RigPathsContext(lambda: paths, {}, {}, lambda: (), lambda _i, _t: 0),
    )
    assert prop_context.frame_and_time(window, wheel, 0.5) == (15, 0.5)
    assert prop_context.reference_time(window, wheel) == 0.5


def test_nested_camera_finds_its_shared_recording_sidecar(qtbot: QtBot, tmp_path: Path) -> None:
    root = tmp_path / "recording"
    nested = root / "front"
    nested.mkdir(parents=True)
    video = nested / "Front.mp4"
    shutil.copyfile("tests/fixtures/videos/camera_1.mp4", video)
    wheel = saved_wheel(root)
    camera = dataclasses.replace(wheel.context.cameras[0], source=str(video))
    wheel = dataclasses.replace(
        wheel,
        context=dataclasses.replace(wheel.context, cameras=(camera, *wheel.context.cameras[1:])),
    )
    write_prop(root / "pose-3d", wheel)
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_video(video)
    qtbot.waitUntil(lambda: window.wheels.get("wheel") is not None, timeout=15000)
    assert window.props_app._folders["wheel"] == root / "pose-3d"
    window.close()


def test_worker_drains_later_edits_without_any_ui_callback(tmp_path: Path, monkeypatch) -> None:
    queue = PropWriteQueue()
    first, latest = Ladder("ladder"), Ladder("ladder", units="mm")
    assert queue.enqueue(tmp_path, first.name, first, "ladder", False, 0)
    original = prop_file_worker.write_prop
    calls = []

    def write_with_an_edit(folder, prop, **kwargs):
        calls.append(prop)
        if len(calls) == 1:
            assert not queue.enqueue(tmp_path, latest.name, latest, "ladder", False, 0)
        return original(folder, prop, **kwargs)

    monkeypatch.setattr(prop_file_worker, "write_prop", write_with_an_edit)
    worker = PropFileWriteWorker(tmp_path, first.name, first, queue=queue)
    # No signal handler advances the queue. The worker must publish both revisions itself.
    worker.run()
    assert calls == [first, latest]
    assert read_props(tmp_path) == ([latest], [])


def test_immediate_close_keeps_the_pending_latest_revision(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    folder = tmp_path / "pose-3d"
    monkeypatch.setattr(rig_paths, "pose3d_dir", lambda _context: folder)
    entered, release = threading.Event(), threading.Event()
    original = prop_file_worker.write_prop

    def held_write(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(prop_file_worker, "write_prop", held_write)
    window.props_app.store.load((Ladder("ladder"),))
    window.props_app.persist("ladder")
    assert entered.wait(5)
    latest = Ladder("ladder", units="mm")
    window.props_app.store.set("ladder", latest)
    window.props_app.persist("ladder")
    release.set()
    window.close()
    assert read_props(folder) == ([latest], [])


def test_old_session_save_completion_does_not_announce_a_new_sessions_save(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    folder = tmp_path / "pose-3d"
    monkeypatch.setattr(rig_paths, "pose3d_dir", lambda _context: folder)
    workers = []

    def hold(worker, label="", configure=None):
        thread = QThread()
        if configure:
            configure(thread)
        workers.append(worker)
        return thread

    monkeypatch.setattr(window, "_run_job", hold)
    successes = []
    monkeypatch.setattr(window.notifications, "show_success", lambda *a, **kw: successes.append(a))
    window.props_app.store.load((Ladder("ladder"),))
    window.props_app.persist("ladder")
    window.session_runtime.generation += 1
    window.props_app.reset()
    workers[0].run()
    assert not successes
    assert not window.props_app.store.names()
    assert read_props(folder) == ([Ladder("ladder")], [])
    window.close()


def test_a_loaded_prop_keeps_its_destination_when_other_sources_arrive(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    folder = {"current": tmp_path / "recording" / "pose-3d"}
    original_folder = folder["current"]
    write_prop(original_folder, Ladder("ladder"))
    monkeypatch.setattr(rig_paths, "pose3d_dir", lambda _context: folder["current"])
    monkeypatch.setattr(window, "_run_job", _run_inline)
    window.props_app.adopt()
    folder["current"] = tmp_path / "different" / "pose-3d"
    latest = Ladder("ladder", units="mm")
    window.props_app.store.set("ladder", latest)
    window.props_app.persist("ladder")
    assert read_props(original_folder) == ([latest], [])
    assert not folder["current"].exists()
    window.close()


@pytest.mark.parametrize("kind", ["ladder", "wheel", "belt", "ball"])
def test_accepted_prop_survives_background_save_and_fresh_window(
    qtbot: QtBot, tmp_path: Path, kind: str
) -> None:
    from avialsync.core.physical_props import (
        BallProp,
        BallSurface,
        BeltProp,
        BeltTrack,
        LadderPoint,
        LadderStep,
        StepClick,
    )
    from avialsync.core.prop_context import PropContext
    from avialsync.ui.controllers.calibration_controller import CalibrationState
    from tests.wheel_fixture import CAMERAS

    paths = {}
    for name in CAMERAS:
        video = tmp_path / f"{name}.mp4"
        shutil.copyfile("tests/fixtures/videos/camera_1.mp4", video)
        paths[name] = str(video)
    window = MainWindow()
    qtbot.addWidget(window)
    for video in paths.values():
        window._load_video(Path(video))
    qtbot.waitUntil(
        lambda: all(path in window._video_frame_times for path in paths.values()), timeout=15000
    )
    window._calibration_state = CalibrationState(
        tmp_path / "missing-calibration.toml",
        {paths[name]: model for name, model in CAMERAS.items()},
    )
    if kind == "wheel":
        prop = dataclasses.replace(saved_wheel(tmp_path), context=PropContext())
    elif kind == "ball":
        prop = BallProp("ball", BallSurface((0.0, 0.0, 70.0), 5.0))
    elif kind == "belt":
        prop = BeltProp("belt", BeltTrack(((0.0, 0.0, 70.0), (10.0, 0.0, 70.0))))
    else:
        clicks = []
        for name in ("Front", "Left"):
            x, y = CAMERAS[name].project(np.array([[0.0, 0.0, 70.0]]))[0]
            clicks.append(StepClick(name, 0, float(x), float(y)))
        prop = Ladder("ladder", (LadderStep("one", "Rung", (LadderPoint(tuple(clicks)),)),))
    window.props_app._accept_prop(prop, "Accept prop")
    accepted = window.props_app.store.get(kind)
    assert accepted is not None and len(accepted.context.cameras) == len(CAMERAS)
    qtbot.waitUntil(lambda: read_props(tmp_path / "pose-3d")[0] == [accepted], timeout=15000)
    window.close()

    reopened = MainWindow()
    qtbot.addWidget(reopened)
    reopened._load_video(Path(paths["Front"]))
    qtbot.waitUntil(
        lambda: (
            reopened.props_app.store.get(kind) is not None
            and paths["Front"] in reopened._video_frame_times
        ),
        timeout=15000,
    )
    assert reopened._calibration_state is None
    assert reopened.props_app.store.get(kind) == accepted
    if kind == "wheel":
        assert wheel_display.pane_drawing(reopened, paths["Front"], 0.0) is not None
    else:
        assert reopened.props_app.camera_drawing(paths["Front"], 0.0)
    reopened.close()


def test_reopen_waits_for_pending_accepted_save(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(rig_paths, "pose3d_dir", lambda _context: tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = prop_file_worker.write_prop

    def held_write(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(prop_file_worker, "write_prop", held_write)
    latest = Ladder("pending", units="mm")
    window.props_app.store.load((latest,))
    window.props_app.persist(latest.name)
    assert entered.wait(5)
    window.session_runtime.generation += 1
    window.props_app.reset()
    window.props_app.adopt()
    release.set()
    qtbot.waitUntil(lambda: window.props_app.store.get(latest.name) == latest, timeout=15000)
    assert read_props(tmp_path) == ([latest], [])
    window.close()


def test_loaded_wheel_explains_missing_motion(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    from tests.wheel_window import build_window

    with monkeypatch.context() as patches:
        window = build_window(qtbot, patches, tmp_path, {"now": 7, "t": 0.0})
        wheel = saved_wheel(tmp_path, binding=True, frame=7)
        window.props_app.store.load((wheel,))
        wheel_display.refresh(window)
        label = window.wheel_panel._rows[wheel.name].dependencies
        assert "encoder.csv" in label.text() and "placement frame 7" in label.text()
        assert label.accessibleName() and label.accessibleDescription()
        window.close()


def test_same_camera_basename_in_another_recording_is_not_a_source_match(tmp_path: Path) -> None:
    wheel = saved_wheel(tmp_path / "first")
    other = str(tmp_path / "unrelated" / "Front.mp4")
    paths = [other]
    window = SimpleNamespace(
        video_grid=SimpleNamespace(
            panes=[SimpleNamespace(time_map=TimeMap(), frame_record_at=lambda t: (0, t))]
        ),
        rig_paths=rig_paths.RigPathsContext(lambda: paths, {}, {}, lambda: (), lambda _i, _t: 0),
    )
    assert prop_context.camera_for(wheel, other) is None
    assert prop_context.frame_and_time(window, wheel, 0.0) is None
