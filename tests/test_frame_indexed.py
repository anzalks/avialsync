"""Tests for frame-indexed source contract and DLC fps resolution (D-019)."""

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Unit: source contract
# ---------------------------------------------------------------------------


def test_base_class_is_frame_indexed_defaults_false():
    """TimeSeriesSource.is_frame_indexed() should default to False."""
    from kinochronix.core.source import TimeSeriesSource

    class _Minimal(TimeSeriesSource):
        @classmethod
        def can_open(cls, path):
            return 0.0

        def open(self, path, config):
            pass

        def channels(self):
            return []

        def time_bounds(self):
            return (0.0, 0.0)

        def read_chunks(self, ch):
            return iter([])

        def read(self, ch, t0, t1, max_points):
            return ([], [], [], [])

        def config_widget(self):
            return None

    assert _Minimal().is_frame_indexed() is False


def test_tracking_loader_is_frame_indexed():
    """TrackingLoader.is_frame_indexed() must return True."""
    from kinochronix.loaders.tracking_loader import TrackingLoader

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


def test_tracking_loader_time_bounds_with_fps(tmp_path):
    """Time bounds should scale with fps."""
    from kinochronix.loaders.tracking_loader import TrackingLoader

    csv = _write_dlc_csv(tmp_path / "pose.csv", n_frames=31)

    loader = TrackingLoader()
    loader.open(csv, {"fps": 10.0})
    t0, t1 = loader.time_bounds()
    # frame indices 0..30 → 0/10 = 0.0, 30/10 = 3.0
    assert abs(t0 - 0.0) < 1e-6
    assert abs(t1 - 3.0) < 1e-6


def test_tracking_loader_time_bounds_rebind(tmp_path):
    """Opening with a different fps should produce different time bounds."""
    from kinochronix.loaders.tracking_loader import TrackingLoader

    csv = _write_dlc_csv(tmp_path / "pose.csv", n_frames=31)

    loader1 = TrackingLoader()
    loader1.open(csv, {"fps": 10.0})
    _, t1_slow = loader1.time_bounds()

    loader2 = TrackingLoader()
    loader2.open(csv, {"fps": 30.0})
    _, t1_fast = loader2.time_bounds()

    assert t1_slow > t1_fast, "Slower fps should give a longer timeline"
    assert abs(t1_slow - 3.0) < 1e-6  # 30 frames @ 10 fps = 3 s
    assert abs(t1_fast - 1.0) < 1e-6  # 30 frames @ 30 fps = 1 s


# ---------------------------------------------------------------------------
# Integration: MainWindow provisional DLC → video → rebind (no mpv)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("qapp")
def test_provisional_dlc_stored_when_no_video(tmp_path):
    """_frame_indexed_sources accumulates provisional entries when no video is loaded."""
    from kinochronix.core.registry import LoaderRegistry
    from kinochronix.loaders.tracking_loader import TrackingLoader
    from kinochronix.ui.main_window import MainWindow

    csv = _write_dlc_csv(tmp_path / "pose.csv", n_frames=10)
    win = MainWindow()

    # No videos loaded yet
    assert len(win._video_fps) == 0

    # Registry must pick TrackingLoader for a DLC CSV
    registry = LoaderRegistry()
    assert registry.find_best_loader(csv) is TrackingLoader

    # Simulate provisional registration directly (the path _start_data_import takes
    # when no video is loaded and the user confirms a nominal fps)
    win._frame_indexed_sources.append((csv, 10.0))
    assert win._frame_indexed_sources == [(csv, 10.0)]

    win.close()


@pytest.mark.usefixtures("qapp")
def test_rebind_clears_provisional_list(tmp_path, monkeypatch):
    """_rebind_frame_indexed_sources should clear the provisional list."""
    from kinochronix.ui.main_window import MainWindow

    win = MainWindow()

    csv = _write_dlc_csv(tmp_path / "pose.csv", n_frames=10)
    win._frame_indexed_sources.append((csv, 10.0))

    # Patch _enqueue_import and plot/sidebar so no actual work runs
    enqueued = []
    monkeypatch.setattr(win, "_enqueue_import", lambda p, lc, cfg: enqueued.append((p, lc, cfg)))
    monkeypatch.setattr(win.plot_pane, "remove_channels", lambda *a: None)
    monkeypatch.setattr(win.sidebar, "remove_sensor", lambda *a: None)

    win._rebind_frame_indexed_sources(25.0)

    assert win._frame_indexed_sources == [], "Provisional list must be cleared after rebind"
    assert len(enqueued) == 1
    p, lc, cfg = enqueued[0]
    assert p == csv
    assert cfg["fps"] == 25.0

    win.close()


@pytest.mark.usefixtures("qapp")
def test_rebind_uses_new_fps(tmp_path, monkeypatch):
    """After rebind, re-enqueued import uses the video fps, not the provisional fps."""
    from kinochronix.ui.main_window import MainWindow

    win = MainWindow()

    csv = _write_dlc_csv(tmp_path / "pose.csv", n_frames=30)
    provisional_fps = 5.0
    video_fps = 30.0
    win._frame_indexed_sources.append((csv, provisional_fps))

    enqueued = []
    monkeypatch.setattr(win, "_enqueue_import", lambda p, lc, cfg: enqueued.append((p, lc, cfg)))
    monkeypatch.setattr(win.plot_pane, "remove_channels", lambda *a: None)
    monkeypatch.setattr(win.sidebar, "remove_sensor", lambda *a: None)

    win._rebind_frame_indexed_sources(video_fps)

    assert enqueued[0][2]["fps"] == video_fps
    assert enqueued[0][2]["fps"] != provisional_fps

    win.close()
