"""Add 3D Marker through the running window: place, move, delete, undo, files (D-112).

Which frame is on screen is stubbed, as in ``test_wheel_controller.py``; the
clicks are what the synthetic rig's cameras see of a known point, so the
triangulated marker is judged against that point.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core import custom_markers
from avialsync.ui import recovery
from avialsync.ui.controllers import calibration_controller, rig_paths
from avialsync.ui.controllers import custom_marker_controller as markers
from avialsync.ui.main_window import MainWindow
from tests.wheel_fixture import CAMERAS

FRAME = 12
TRUTH = np.array([15.0, -25.0, 100.0])


@pytest.fixture(autouse=True)
def isolated_recovery_dir(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    yield target


@pytest.fixture
def videos(tmp_path: Path) -> dict[str, str]:
    (tmp_path / "rec").mkdir()
    return {name: str(tmp_path / "rec" / f"{name}.mp4") for name in CAMERAS}


@pytest.fixture
def pose3d(tmp_path: Path) -> Path:
    return tmp_path / "rec" / "pose-3d"


@pytest.fixture
def window(
    qapp: QApplication, qtbot, monkeypatch, videos: dict[str, str], pose3d: Path
) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    monkeypatch.setattr(rig_paths, "open_videos", lambda _w: list(videos.values()))
    monkeypatch.setattr(rig_paths, "frame_at", lambda _w, _t: FRAME)
    monkeypatch.setattr(rig_paths, "pose3d_dir", lambda _w: pose3d)
    win._calibration_state = calibration_controller.CalibrationState(
        path=Path("calibration.toml"),
        cameras={videos[name]: model for name, model in CAMERAS.items()},
    )
    yield win
    if isValid(win):
        win.close()


def _place(window: MainWindow, videos: dict[str, str], monkeypatch, point=TRUTH) -> None:
    monkeypatch.setattr(markers, "ask_marker_name", lambda *_a: "rung")
    markers.toggled(window, True)
    for name, camera in CAMERAS.items():
        x, y = camera.project(point)[0]
        markers.on_clicked(window, videos[name], float(x), float(y))


def test_a_marker_clicked_in_every_camera_lands_on_the_point(
    window: MainWindow, videos, monkeypatch
) -> None:
    _place(window, videos, monkeypatch)
    marker = window.custom_markers.get("rung", FRAME)
    assert marker is not None and marker.xyz is not None
    assert np.allclose(marker.xyz, TRUTH, atol=1e-6)
    assert window._marker_placement is None
    assert window.document.undo(window._mutations)
    assert window.custom_markers.get("rung", FRAME) is None
    assert window.document.redo(window._mutations)
    assert window.custom_markers.get("rung", FRAME) == marker


def test_a_drag_retriangulates_as_one_step(window: MainWindow, videos, monkeypatch) -> None:
    _place(window, videos, monkeypatch)
    before = window.custom_markers.get("rung", FRAME)
    assert before is not None
    moved_to = TRUTH + np.array([6.0, 0.0, 0.0])
    x, y = CAMERAS["Front"].project(moved_to)[0]
    markers.on_moved(window, videos["Front"], "rung", FRAME, float(x), float(y))
    after = window.custom_markers.get("rung", FRAME)
    assert after is not None and after.xyz != before.xyz
    assert window.document.undo(window._mutations)
    assert window.custom_markers.get("rung", FRAME) == before


def test_delete_is_undoable(window: MainWindow, videos, monkeypatch) -> None:
    _place(window, videos, monkeypatch)
    marker = window.custom_markers.get("rung", FRAME)
    markers.delete(window, "rung", FRAME)
    assert window.custom_markers.get("rung", FRAME) is None
    assert window.document.undo(window._mutations)
    assert window.custom_markers.get("rung", FRAME) == marker


def test_markers_are_written_in_pose3d_never_beside_the_videos(
    window: MainWindow, videos, monkeypatch, pose3d: Path
) -> None:
    _place(window, videos, monkeypatch)
    rec = Path(next(iter(videos.values()))).parent
    beside_videos = [p for p in rec.iterdir() if p.is_file()]
    assert beside_videos == [], "the recording folder is the acquisition's"
    for name in CAMERAS:
        read = custom_markers.read_2d(pose3d / f"{name}{custom_markers.MARKER_SUFFIX}")
        assert ("rung", FRAME) in read
    assert ("rung", FRAME) in custom_markers.read_3d(pose3d / "pose.custom_markers.csv")


def test_markers_on_disk_are_adopted(window: MainWindow, videos, monkeypatch) -> None:
    _place(window, videos, monkeypatch)
    marker = window.custom_markers.get("rung", FRAME)
    window.custom_markers.clear()
    markers.adopt(window)
    assert window.custom_markers.get("rung", FRAME) == marker


def test_a_marker_file_the_first_build_left_beside_a_video_is_still_read(
    window: MainWindow, videos
) -> None:
    video = videos["Front"]
    legacy = custom_markers.marker_file_for(Path(video))
    custom_markers.write_2d(
        legacy, "Front", [custom_markers.CustomMarker("old", 3).with_view("Front", 1.0, 2.0)]
    )
    markers.adopt(window)
    old = window.custom_markers.get("old", 3)
    assert old is not None and old.view("Front") == (1.0, 2.0)


# ── reprojection never asks from a switch (rule 11) ──────────────────


@pytest.fixture
def no_dialog(monkeypatch):
    def _refuse(*_args, **_kwargs):
        raise AssertionError("a modal was opened for an overlay switch")

    monkeypatch.setattr(calibration_controller, "ask_calibration_source", _refuse)


def test_switching_reprojection_on_without_a_calibration_only_informs(
    window: MainWindow, no_dialog
) -> None:
    window._calibration_state = None
    undo_before = window.document.undo_label()
    window._on_overlay_toggled("tracking.reprojection", True)
    assert window.overlay_state.is_visible("tracking.reprojection")
    assert "calibration" in window.notifications.message
    assert window.document.undo_label() != undo_before
    assert window.document.undo(window._mutations)
    assert not window.overlay_state.is_visible("tracking.reprojection")
    assert window.document.undo_label() == undo_before, "one switch, one undo step"


def test_show_all_does_not_open_the_calibration_question(window: MainWindow, no_dialog) -> None:
    window._calibration_state = None
    window._set_all_overlays(True)
    assert window.overlay_state.is_visible("tracking.reprojection")


def test_the_question_is_asked_when_the_user_asks_for_it(window: MainWindow, monkeypatch) -> None:
    asked: list[str] = []
    monkeypatch.setattr(
        calibration_controller, "ask_calibration_source", lambda *_a: asked.append("x")
    )
    window._calibration_state = None
    calibration_controller.acquire_calibration(window, lambda: None, lambda: None)
    assert asked == ["x"]
