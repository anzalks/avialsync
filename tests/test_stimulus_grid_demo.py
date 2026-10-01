"""The published synthetic camera scene visibly follows its TTL events."""

import av
import numpy as np

from tools import generate_stimulus_grid_demo as demo

EVENTS = demo.EVENTS


def test_three_camera_scene_moves_only_near_triggers() -> None:
    for yaw in (-0.7, 0.0, 0.7):
        idle = demo._scene_frame(3.0, yaw)
        assert np.array_equal(idle, demo._scene_frame(0.2, yaw))
        for event in EVENTS:
            active = demo._scene_frame(event + 0.1, yaw)
            assert not np.array_equal(active, idle)
            assert np.count_nonzero(np.all(active > 220, axis=2)) > 0
            assert np.count_nonzero(np.all(idle > 220, axis=2)) == 0


def test_camera_angles_show_distinct_views_of_the_same_trigger() -> None:
    views = [demo._scene_frame(EVENTS[0] + 0.1, yaw) for yaw in (-0.7, 0.0, 0.7)]
    assert not np.array_equal(views[0], views[1])
    assert not np.array_equal(views[1], views[2])


def test_demo_export_runs_through_the_app_action(qapp, tmp_path, monkeypatch) -> None:
    """The published demo path must use the live dialog and export worker."""
    monkeypatch.setattr(demo, "EVENTS", (1.5,))
    monkeypatch.setattr(demo, "SOURCE_SECONDS", 3.0)
    monkeypatch.setattr(demo, "OUTPUT", tmp_path)
    camera = demo.CameraFixture(tmp_path / "camera.mp4", "Camera", 0.0, 0.0)
    demo._write_camera(camera)
    signal_csv = demo._write_signal_csv(tmp_path)
    movie = tmp_path / "app_export.mp4"

    demo._export_via_app(qapp, tmp_path, (camera,), signal_csv, movie)

    with av.open(str(movie)) as container:
        frames = list(container.decode(video=0))
    assert len(frames) == 24
    assert (tmp_path / "stimulus_grid_select_events.png").is_file()
