"""Tests for the timeline-synchronized 3D tracking pane."""

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter

from avialsync.core.pyramid import PyramidBuilder, PyramidReader
from avialsync.ui.tracking_3d_pane import Tracking3DPane
from avialsync.ui.tracking_skeleton import BoneMode


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


def _anatomical_readers(cache_dir: Path) -> list[PyramidReader]:
    """Build a pose whose vertical axis is Y and grows downward.

    Mirrors the real AOL EKS session: head_bar y=5.9, shoulders 33.9,
    paws 48.2, toes 54.7 -- anatomically descending as y increases.
    """
    cache_dir.mkdir()
    times = np.array([0.0, 1.0], dtype=np.float64)
    layout = {
        "head_bar": (-56.7, 5.9, 461.3),
        "left_shoulder": (-28.4, 33.9, 471.9),
        "left_paw": (-28.8, 48.2, 464.4),
        "left_toe": (-29.8, 54.7, 461.4),
    }
    names = []
    for point, (x, y, z) in layout.items():
        for axis, value in zip("xyz", (x, y, z), strict=True):
            name = f"{point}_{axis}"
            PyramidBuilder(cache_dir, name).build_and_save(
                times, np.array([value, value], dtype=np.float64)
            )
            names.append(name)
    return [PyramidReader(cache_dir, name) for name in names]


def test_head_renders_above_toes(qtbot, tmp_path: Path) -> None:
    """The 3D view must orient anatomy head-up, not use a fixed Z-up axis.

    The reference AOL session's vertical axis is Y and it increases downward,
    so a hardcoded Z-up projection renders the animal edge-on.
    """
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.resize(400, 400)
    pane.show()
    pane.set_readers(_anatomical_readers(tmp_path / "anat.avialcache"))
    pane.set_cursor(0.0)

    assert pane.canvas.up_axis == 1, "vertical axis should be detected as Y"
    assert pane.canvas.up_inverted is True, "Y grows downward in this data"

    screen, _depth = pane.canvas._project(pane.canvas.positions)
    y_by_name = {name: float(screen[i, 1]) for i, name in enumerate(pane.canvas.point_names)}
    # Screen Y grows downward, so "higher on screen" is a smaller value.
    assert y_by_name["head_bar"] < y_by_name["left_shoulder"] < y_by_name["left_toe"], (
        f"anatomy is not head-up on screen: {y_by_name}"
    )


def test_up_axis_override_is_respected(qtbot, tmp_path: Path) -> None:
    """An explicit choice pins the orientation against later auto-detection."""
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.resize(400, 400)
    pane.set_readers(_anatomical_readers(tmp_path / "anat_override.avialcache"))

    pane.set_up_axis(2, False)
    assert pane.canvas.up_axis == 2
    assert pane.canvas.up_inverted is False

    # Re-loading data must not silently undo a user's explicit choice.
    pane.set_readers(_anatomical_readers(tmp_path / "anat_override2.avialcache"))
    assert pane.canvas.up_axis == 2


def test_unrecognised_landmarks_keep_neutral_default(qtbot, tmp_path: Path) -> None:
    """Without head/foot landmarks the view must not guess an orientation."""
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.set_readers(_tracking_readers(tmp_path / "neutral.avialcache"))

    assert pane.canvas.up_axis == 2
    assert pane.canvas.up_inverted is False


def test_main_window_places_3d_view_beside_video_grid(qtbot, monkeypatch) -> None:
    from avialsync.ui.main_window import MainWindow

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


def _rigid_chain_readers(
    cache_dir: Path,
    names: tuple[str, ...] = ("head", "spine", "tail"),
    frames: int = 90,
) -> list[PyramidReader]:
    """An animal whose segments hold their length while the whole body moves.

    Distance is the only evidence the detector reads, so the body has to move:
    points that merely sit at fixed coordinates are rigid against everything,
    including a wall.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    times = np.linspace(0.0, frames / 30.0, frames)
    phase = np.linspace(0.0, 6.0, frames)
    # A chain descending in Z, each joint bending on its own, carried around by
    # a moving root: consecutive points hold their spacing, skipped ones do not.
    position = np.column_stack((np.sin(phase) * 30.0, np.cos(phase) * 30.0, np.zeros(frames)))
    readers = []
    for index, point in enumerate(names):
        if index:
            bend = np.sin(phase * (index + 1.7)) * 0.8
            position = position + np.column_stack(
                (np.sin(bend) * 40.0, np.zeros(frames), -np.cos(bend) * 40.0)
            )
        for axis_index, axis in enumerate("xyz"):
            name = f"{point}_{axis}"
            PyramidBuilder(cache_dir, name).build_and_save(times, position[:, axis_index])
            readers.append(name)
    return [PyramidReader(cache_dir, name) for name in readers]


def test_skeleton_is_detected_when_the_data_declares_none(qtbot, tmp_path: Path) -> None:
    """Pose with no declared topology still shows bones, marked as detected (D-082)."""
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.set_readers(_rigid_chain_readers(tmp_path / "chain.avialcache"))

    assert pane.canvas.skeleton_edges, "no skeleton was detected from the geometry"
    assert pane.canvas.skeleton_is_derived
    assert "detected" in pane.status_label.text()

    # Painting is where a derived skeleton differs from a declared one -- dashed
    # pens and a per-bone width -- so exercise it rather than only the edge list.
    pane.resize(400, 400)
    pane.set_cursor(1.0)
    assert not pane.canvas.grab().isNull()


def test_detected_bones_flow_outward_from_the_top(qtbot, tmp_path: Path) -> None:
    """Detection reports a direction, rooted on the view's anatomical vertical."""
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.set_readers(_rigid_chain_readers(tmp_path / "flow.avialcache"))

    estimate = pane.canvas.inferred_skeleton
    assert estimate.roots == ("head",)
    assert estimate.parents == {"spine": "head", "tail": "spine"}
    assert pane.canvas.skeleton_edges[0] == ("head", "spine")


def test_declared_topology_wins_over_detection(qtbot, tmp_path: Path) -> None:
    """A session that names its own bones is never second-guessed."""
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.set_skeleton([("head", "tail")])
    pane.set_readers(_rigid_chain_readers(tmp_path / "declared.avialcache"))

    assert pane.canvas.skeleton_edges == [("head", "tail")]
    assert not pane.canvas.skeleton_is_derived
    assert "from session" in pane.status_label.text()


def test_declared_names_resolve_through_a_loader_prefix(qtbot, tmp_path: Path) -> None:
    """A body part the cache kept prefixed still gets its declared bone drawn."""
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.set_skeleton([("head", "spine")])
    pane.set_readers(
        _rigid_chain_readers(
            tmp_path / "prefixed.avialcache",
            names=("ensemble_head", "ensemble_spine", "ensemble_tail"),
        )
    )

    assert pane.canvas.skeleton_edges == [("ensemble_head", "ensemble_spine")]
    assert not pane.canvas.skeleton_is_derived


def test_an_ambiguous_declared_name_is_skipped_not_guessed(qtbot, tmp_path: Path) -> None:
    """Two points could answer to 'head', so that edge is dropped rather than picked."""
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.set_skeleton([("head", "tail")])
    pane.set_readers(
        _rigid_chain_readers(
            tmp_path / "ambiguous.avialcache",
            names=("left_head", "right_head", "tail"),
        )
    )

    # Nothing declared survived resolution, so the view falls back to detection
    # rather than drawing a bone to whichever 'head' happened to sort first.
    assert pane.canvas.skeleton_is_derived


def test_bones_can_be_turned_off_and_forced_to_detected(qtbot, tmp_path: Path) -> None:
    """The header pins the choice; a scientist can refuse a derived skeleton."""
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.set_skeleton([("head", "tail")])
    pane.set_readers(_rigid_chain_readers(tmp_path / "modes.avialcache"))

    pane.set_bone_mode(BoneMode.OFF)
    assert pane.canvas.skeleton_edges == []

    pane.set_bone_mode(BoneMode.DETECTED)
    assert pane.canvas.skeleton_is_derived
    assert ("head", "tail") not in pane.canvas.skeleton_edges

    pane.set_bone_mode(BoneMode.AUTO)
    assert pane.canvas.skeleton_edges == [("head", "tail")]


def test_a_session_without_a_skeleton_clears_the_previous_one(qtbot, tmp_path: Path) -> None:
    """Loading a second session must not leave the first one's bones on screen."""
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.set_skeleton([("head", "tail")])
    pane.set_readers(_rigid_chain_readers(tmp_path / "first.avialcache"))
    assert not pane.canvas.skeleton_is_derived

    pane.set_skeleton([])
    assert ("head", "tail") not in pane.canvas.skeleton_edges
    assert pane.canvas.skeleton_is_derived


def test_detected_skeleton_survives_an_up_axis_change(qtbot, tmp_path: Path) -> None:
    """Re-orienting the view re-roots the flow instead of losing the bones."""
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.set_readers(_rigid_chain_readers(tmp_path / "reroot.avialcache"))
    assert pane.canvas.inferred_skeleton.roots == ("head",)

    pane.set_up_axis(2, True)

    assert pane.canvas.inferred_skeleton.roots == ("tail",)
    assert len(pane.canvas.skeleton_edges) == 2
