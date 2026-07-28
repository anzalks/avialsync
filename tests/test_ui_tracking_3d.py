"""Tests for the timeline-synchronized 3D tracking pane."""

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter

from avialview.core.pyramid import PyramidBuilder, PyramidReader
from avialview.ui.tracking_3d_pane import Tracking3DPane


def _tracking_readers(
    cache_dir: Path,
    *,
    include_z: bool = True,
) -> list[PyramidReader]:
    cache_dir.mkdir()
    times = np.array([0.0, 0.5, 1.0], dtype=np.float64)
    channels = {
        "nose_x": np.array([0.0, 10.0, 20.0]),
        "nose_y": np.array([1.0, 11.0, 21.0]),
        "tail_x": np.array([3.0, 13.0, 23.0]),
        "tail_y": np.array([4.0, 14.0, 24.0]),
        "confidence": np.array([0.9, 0.8, 0.7]),
    }
    if include_z:
        channels["nose_z"] = np.array([2.0, 12.0, 22.0])
        channels["tail_z"] = np.array([5.0, 15.0, 25.0])
    for name, values in channels.items():
        PyramidBuilder(cache_dir, name).build_and_save(times, values)
    return [PyramidReader(cache_dir, name) for name in channels]


def test_complete_xyz_triplets_follow_master_cursor(qtbot, tmp_path: Path) -> None:
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.show()
    pane.set_readers(_tracking_readers(tmp_path / "tracking.avialcache"))

    assert pane.canvas.point_count == 2
    assert pane.canvas.point_names == ("nose", "tail")
    assert pane.status_label.text() == "2 tracked points"

    pane.set_cursor(0.5)
    np.testing.assert_allclose(
        pane.canvas.positions,
        np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]]),
    )


def test_incomplete_xy_points_are_not_presented_as_3d(qtbot, tmp_path: Path) -> None:
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.set_readers(_tracking_readers(tmp_path / "tracking_2d.avialcache", include_z=False))

    assert pane.canvas.point_count == 0
    assert pane.status_label.text() == "No XYZ tracking channels"
    assert not pane.fit_button.isEnabled()


def test_out_of_range_pose_has_no_stale_coordinates(qtbot, tmp_path: Path) -> None:
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.set_readers(_tracking_readers(tmp_path / "tracking_bounds.avialcache"))

    pane.set_cursor(0.5)
    assert np.all(np.isfinite(pane.canvas.positions))
    pane.set_cursor(4.0)
    assert np.all(np.isnan(pane.canvas.positions))


def test_mouse_drag_orbits_and_fit_restores_default(qtbot, tmp_path: Path) -> None:
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.resize(500, 300)
    pane.show()
    pane.set_readers(_tracking_readers(tmp_path / "tracking_orbit.avialcache"))

    initial_azimuth = pane.canvas._azimuth
    qtbot.mousePress(
        pane.canvas,
        Qt.MouseButton.LeftButton,
        pos=pane.canvas.rect().center(),
    )
    qtbot.mouseMove(pane.canvas, pane.canvas.rect().center() + pane.canvas.rect().topRight() / 4)
    qtbot.mouseRelease(
        pane.canvas,
        Qt.MouseButton.LeftButton,
        pos=pane.canvas.rect().center() + pane.canvas.rect().topRight() / 4,
    )
    assert pane.canvas._azimuth != initial_azimuth

    pane.fit_button.click()
    assert pane.canvas._azimuth == initial_azimuth


def test_main_window_places_3d_view_beside_video_grid(qtbot, monkeypatch) -> None:
    from avialview.ui.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "_run_diagnostics", lambda _self: None)
    window = MainWindow()
    qtbot.addWidget(window)

    splitter = window._media_splitter
    assert isinstance(splitter, QSplitter)
    assert splitter.orientation() == Qt.Orientation.Horizontal
    assert splitter.widget(0) is window.video_grid
    assert splitter.widget(1) is window.tracking_3d_pane
    assert window.player.tracking_3d_pane is window.tracking_3d_pane

    window.close()
