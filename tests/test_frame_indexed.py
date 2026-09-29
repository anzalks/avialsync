"""Frame-indexed source contract and tracking frame-rate resolution (D-019, D-137).

The rate a tracking file's frames came at belongs to the camera that exposed
them, so nothing here asks the user for it: the tests assert what is derived
from the loaded videos, and that a source nothing can date yet is imported
provisionally rather than blocked.
"""

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Unit: source contract
# ---------------------------------------------------------------------------


def test_base_class_is_frame_indexed_defaults_false():
    """TimeSeriesSource.is_frame_indexed() should default to False."""
    from avialsync.core.source import TimeSeriesSource

    class _Minimal(TimeSeriesSource):
        @classmethod
        def can_open(cls, path):
            return 0.0

        def open(self, path, config):
            pass

        def channels(self):
            return []

        def read_chunks(self, ch):
            return iter([])

    assert _Minimal().is_frame_indexed() is False


def test_tracking_loader_is_frame_indexed():
    """TrackingLoader.is_frame_indexed() must return True."""
    from avialsync.loaders.tracking_loader import TrackingLoader

    assert TrackingLoader().is_frame_indexed() is True


# ---------------------------------------------------------------------------
# Helper: build a minimal DLC CSV in a tmp directory
# ---------------------------------------------------------------------------


def _write_dlc_csv(path: Path, n_frames: int = 10) -> Path:
    """Write a minimal two-bodypart DLC CSV to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "scorer,DLC_resnet50,DLC_resnet50,DLC_resnet50,DLC_resnet50",
        "bodyparts,nose,nose,tail,tail",
        "coords,x,y,x,y",
    ]
    for i in range(n_frames):
        lines.append(f"{i},{i * 1.0},{i * 0.5},{i * 2.0},{i * 1.5}")
    path.write_text("\n".join(lines))
    return path


# ---------------------------------------------------------------------------
# Unit: TrackingLoader time bounds with different fps values
# ---------------------------------------------------------------------------


def test_tracking_loader_chunk_times_scale_with_fps(tmp_path):
    """Frame-indexed chunk timestamps must scale with configured fps."""
    from avialsync.loaders.tracking_loader import TrackingLoader

    csv = _write_dlc_csv(tmp_path / "pose.csv", n_frames=31)

    loader = TrackingLoader()
    loader.open(csv, {"fps": 10.0})
    chunks = list(loader.read_chunks("nose_x"))
    t0, t1 = chunks[0][0][0], chunks[-1][0][-1]
    # frame indices 0..30 → 0/10 = 0.0, 30/10 = 3.0
    assert abs(t0 - 0.0) < 1e-6
    assert abs(t1 - 3.0) < 1e-6


def test_tracking_loader_chunk_times_rebind(tmp_path):
    """Opening with a different fps must change chunk timestamps."""
    from avialsync.loaders.tracking_loader import TrackingLoader

    csv = _write_dlc_csv(tmp_path / "pose.csv", n_frames=31)

    loader1 = TrackingLoader()
    loader1.open(csv, {"fps": 10.0})
    t1_slow = list(loader1.read_chunks("nose_x"))[-1][0][-1]

    loader2 = TrackingLoader()
    loader2.open(csv, {"fps": 30.0})
    t1_fast = list(loader2.read_chunks("nose_x"))[-1][0][-1]

    assert t1_slow > t1_fast, "Slower fps should give a longer timeline"
    assert abs(t1_slow - 3.0) < 1e-6  # 30 frames @ 10 fps = 3 s
    assert abs(t1_fast - 1.0) < 1e-6  # 30 frames @ 30 fps = 1 s


# ---------------------------------------------------------------------------
# Integration: MainWindow provisional DLC → video → rebind (no mpv)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("qapp")
def test_provisional_dlc_stored_when_no_video(tmp_path):
    """_frame_indexed_sources accumulates provisional entries when no video is loaded."""
    from avialsync.core.registry import LoaderRegistry
    from avialsync.loaders.tracking_loader import TrackingLoader
    from avialsync.ui.main_window import MainWindow

    csv = _write_dlc_csv(tmp_path / "pose.csv", n_frames=10)
    win = MainWindow()

    # No videos loaded yet
    assert len(win._video_fps) == 0

    # Registry must pick TrackingLoader for a DLC CSV
    registry = LoaderRegistry()
    assert registry.find_best_loader(csv) is TrackingLoader

    # With no camera loaded there is nothing to read a rate off, so the import
    # is provisional rather than refused or blocked on a dialog.
    from avialsync.ui.controllers import import_controller

    fps, provisional = import_controller.frame_rate_for_tracking(win, {})
    assert provisional is True
    assert fps == import_controller._ASSUMED_FPS

    win.close()


@pytest.mark.usefixtures("qapp")
def test_rebind_clears_provisional_list(tmp_path, monkeypatch):
    """_rebind_frame_indexed_sources should clear the provisional list."""
    from avialsync.ui.main_window import MainWindow

    win = MainWindow()

    csv = _write_dlc_csv(tmp_path / "pose.csv", n_frames=10)
    from avialsync.loaders.tracking_loader import TrackingLoader

    win._frame_indexed_sources.append((csv, TrackingLoader, {"fps": 10.0}))
    win._video_fps["cam.mp4"] = 25.0

    # Patch _enqueue_import and plot/sidebar so no actual work runs
    enqueued = []
    monkeypatch.setattr(win, "_enqueue_import", lambda p, lc, cfg: enqueued.append((p, lc, cfg)))
    monkeypatch.setattr(win.plot_pane, "remove_channels", lambda *a: None)
    monkeypatch.setattr(win.sidebar, "remove_sensor", lambda *a: None)

    win._rebind_frame_indexed_sources()

    assert win._frame_indexed_sources == [], "Provisional list must be cleared after rebind"
    assert len(enqueued) == 1
    p, lc, cfg = enqueued[0]
    assert p == csv
    assert cfg["fps"] == 25.0
    assert cfg["fps_provisional"] is False

    win.close()


@pytest.mark.usefixtures("qapp")
def test_rebind_uses_new_fps(tmp_path, monkeypatch):
    """After rebind, re-enqueued import uses the video fps, not the provisional fps."""
    from avialsync.ui.main_window import MainWindow

    win = MainWindow()

    csv = _write_dlc_csv(tmp_path / "pose.csv", n_frames=30)
    provisional_fps = 5.0
    video_fps = 30.0
    from avialsync.loaders.tracking_loader import TrackingLoader

    win._frame_indexed_sources.append((csv, TrackingLoader, {"fps": provisional_fps}))
    win._video_fps["cam.mp4"] = video_fps

    enqueued = []
    monkeypatch.setattr(win, "_enqueue_import", lambda p, lc, cfg: enqueued.append((p, lc, cfg)))
    monkeypatch.setattr(win.plot_pane, "remove_channels", lambda *a: None)
    monkeypatch.setattr(win.sidebar, "remove_sensor", lambda *a: None)

    win._rebind_frame_indexed_sources()

    assert enqueued[0][2]["fps"] == video_fps
    assert enqueued[0][2]["fps"] != provisional_fps

    win.close()


# ---------------------------------------------------------------------------
# The frame rate comes from the camera, never from a dialog (D-137)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("qapp")
def test_one_loaded_camera_answers_without_asking(tmp_path):
    from avialsync.ui.controllers import import_controller
    from avialsync.ui.main_window import MainWindow

    win = MainWindow()
    win._video_fps["cam.mp4"] = 29.97

    assert import_controller.frame_rate_for_tracking(win, {}) == (29.97, False)

    win.close()


@pytest.mark.usefixtures("qapp")
def test_the_declared_camera_wins_over_every_other(tmp_path):
    """The import review already asked which camera; that answer is the rate."""
    from avialsync.ui.controllers import import_controller
    from avialsync.ui.main_window import MainWindow

    win = MainWindow()
    win._video_fps["left.mp4"] = 60.0
    win._video_fps["right.mp4"] = 29.97

    fps, provisional = import_controller.frame_rate_for_tracking(
        win, {"overlay_video": "right.mp4"}
    )

    assert (fps, provisional) == (29.97, False)

    win.close()


@pytest.mark.usefixtures("qapp")
def test_a_declared_camera_that_is_not_loaded_stays_provisional(tmp_path):
    """Another camera's rate is not an answer about this one."""
    from avialsync.ui.controllers import import_controller
    from avialsync.ui.main_window import MainWindow

    win = MainWindow()
    win._video_fps["left.mp4"] = 60.0

    fps, provisional = import_controller.frame_rate_for_tracking(
        win, {"overlay_video": "right.mp4"}
    )

    assert provisional is True
    assert fps == import_controller._ASSUMED_FPS

    win.close()


@pytest.mark.usefixtures("qapp")
def test_cameras_that_agree_are_not_a_choice(tmp_path):
    from avialsync.ui.controllers import import_controller
    from avialsync.ui.main_window import MainWindow

    win = MainWindow()
    win._video_fps["a.mp4"] = 30.0
    win._video_fps["b.mp4"] = 30.0

    assert import_controller.frame_rate_for_tracking(win, {}) == (30.0, False)

    win.close()


@pytest.mark.usefixtures("qapp")
def test_cameras_that_disagree_place_the_source_but_say_it_is_a_guess(tmp_path):
    from avialsync.ui.controllers import import_controller
    from avialsync.ui.main_window import MainWindow

    win = MainWindow()
    win._video_fps["a.mp4"] = 30.0
    win._video_fps["b.mp4"] = 60.0

    fps, provisional = import_controller.frame_rate_for_tracking(win, {})

    assert fps == 30.0
    assert provisional is True, "A guess between cameras has to be flagged, not silent"

    win.close()


@pytest.mark.usefixtures("qapp")
def test_a_source_waiting_on_its_own_camera_is_not_rebound_by_another(tmp_path, monkeypatch):
    from avialsync.loaders.tracking_loader import TrackingLoader
    from avialsync.ui.main_window import MainWindow

    win = MainWindow()
    csv = _write_dlc_csv(tmp_path / "pose.csv", n_frames=10)
    win._frame_indexed_sources.append(
        (csv, TrackingLoader, {"fps": 30.0, "overlay_video": "right.mp4"})
    )
    win._video_fps["left.mp4"] = 60.0

    enqueued = []
    monkeypatch.setattr(win, "_enqueue_import", lambda p, lc, cfg: enqueued.append((p, lc, cfg)))
    monkeypatch.setattr(win.plot_pane, "remove_channels", lambda *a: None)
    monkeypatch.setattr(win.sidebar, "remove_sensor", lambda *a: None)

    win._rebind_frame_indexed_sources()

    assert enqueued == [], "The wrong camera must not date these frames"
    assert len(win._frame_indexed_sources) == 1, "It keeps waiting for its own"

    win.close()
