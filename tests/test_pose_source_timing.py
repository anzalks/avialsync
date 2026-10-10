"""A pose source's Offset and Drift move it live, or say why they cannot.

Its source card offered the same timing fields as any data source, and editing
them did nothing until the session was reopened: the handler looked for plot
rows, and pose sources have none unless Show plot is ticked.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.pyramid import PyramidBuilder, PyramidReader
from avialsync.core.timeline import TimeMap
from avialsync.ui.main_window import MainWindow
from avialsync.ui.tracking_timing import calibrate_overlay_timing
from tests.test_aol_pose_routing import _finish_import


@pytest.fixture
def window(qtbot, monkeypatch) -> MainWindow:
    monkeypatch.setattr(MainWindow, "_run_diagnostics", lambda _self: None)
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    win.close()


def _pose_3d(window: MainWindow, tmp_path: Path) -> str:
    source = str(tmp_path / "_eks.csv")
    _finish_import(
        window,
        source,
        tmp_path / "eks_cache",
        ["head_bar_x", "head_bar_y", "head_bar_z"],
        {"role": "pose3d"},
    )
    return source


def test_a_3d_pose_offset_moves_its_readers_and_the_timeline(
    window: MainWindow, tmp_path: Path
) -> None:
    source = _pose_3d(window, tmp_path)
    card = window.sidebar.sensor_widget(source)
    assert card is not None
    assert card.offset_spin.isEnabled(), "a 3D source keeps its own clock"

    card.offset_spin.setValue(5.0)

    maps = {id(reader.time_map): reader.time_map for reader in window._pose_3d_sources[source]}
    assert [time_map.offset for time_map in maps.values()] == [pytest.approx(5.0)]
    assert window.clock.state.bounds == pytest.approx((-5.0, -4.0))


def test_a_pose_offset_is_one_undoable_change(window: MainWindow, tmp_path: Path) -> None:
    source = _pose_3d(window, tmp_path)
    card = window.sidebar.sensor_widget(source)
    assert card is not None
    window.document.clear()

    card.offset_spin.setValue(2.5)
    assert window.isWindowModified()
    assert window.document.undo(window._mutations)

    reader = window._pose_3d_sources[source][0]
    assert reader.time_map.offset == pytest.approx(0.0)
    assert card.offset_spin.value() == pytest.approx(0.0)
    assert window.clock.state.bounds == pytest.approx((0.0, 1.0))


def test_the_lock_greys_both_fields_with_its_reason_and_lifts(
    window: MainWindow, tmp_path: Path
) -> None:
    source = _pose_3d(window, tmp_path)
    card = window.sidebar.sensor_widget(source)
    assert card is not None
    default_tip = card.offset_spin.toolTip()

    window.sidebar.set_sensor_timing_locked(source, "Timed by FaceCam.mp4's own frames.")
    assert not card.offset_spin.isEnabled() and not card.drift_spin.isEnabled()
    assert "FaceCam.mp4" in card.offset_spin.toolTip()
    assert "FaceCam.mp4" in card.drift_spin.toolTip()

    window.sidebar.set_sensor_timing_locked(source, "")
    assert card.offset_spin.isEnabled() and card.drift_spin.isEnabled()
    assert card.offset_spin.toolTip() == default_tip


def _overlay_window(tmp_path: Path, frame_times: np.ndarray) -> tuple[SimpleNamespace, list]:
    """A window holding one 2D overlay on FaceCam.mp4, recording what the card is told."""
    source_times = np.array([0.0, 1.0, 2.0])
    for channel in ("nose_x", "nose_y"):
        PyramidBuilder(tmp_path, channel).build_and_save(source_times, source_times)
    tracking_map = TimeMap()
    points = {
        "nose": tuple(
            MappedChannelReader(PyramidReader(tmp_path, axis), tracking_map, "FaceCam_eks.csv")
            for axis in ("nose_x", "nose_y")
        )
    }
    video = "FaceCam.mp4"
    told: list[tuple[str, str]] = []
    window = SimpleNamespace(
        video_grid=SimpleNamespace(
            pane_paths=lambda: [video], panes=[SimpleNamespace(time_map=TimeMap())]
        ),
        _video_frame_times={video: frame_times},
        _overlay_sources={video: {"FaceCam_eks.csv": {"frame_rate": 1.0, "points": points}}},
        _pose_3d_sources={},
        sidebar=SimpleNamespace(
            set_sensor_timing_locked=lambda path, reason: told.append((path, reason))
        ),
        notifications=SimpleNamespace(show_warning=lambda _text: None),
        _announced_uncalibrated_overlays=set(),
    )
    return window, told


def test_an_overlay_timed_by_its_camera_locks_its_fields(tmp_path: Path) -> None:
    window, told = _overlay_window(tmp_path, np.array([0.0, 0.5, 2.0]))

    calibrate_overlay_timing(window, "FaceCam.mp4")

    assert len(told) == 1
    path, reason = told[0]
    assert path == "FaceCam_eks.csv"
    assert "FaceCam.mp4" in reason


def test_an_overlay_its_camera_cannot_time_keeps_its_fields(tmp_path: Path) -> None:
    """Frame indices past the video's end: drawn on its own mapping, so editable."""
    window, told = _overlay_window(tmp_path, np.array([0.0, 0.5]))

    calibrate_overlay_timing(window, "FaceCam.mp4")

    assert told == []
