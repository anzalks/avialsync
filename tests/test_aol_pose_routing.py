"""AOL pose routing: 2D overlays per camera, 3D to the 3D view, neither plotted.

2D and 3D pose data must reach the video overlay and the 3D view without
creating plot rows: one AOL session emits 27 3D channels and ~81 2D channels
per camera, which would bury the recorded signals the plot exists to show.
"""

from pathlib import Path

import pytest

from avialview.engine.drop_worker import DropScanWorker
from avialview.loaders.aol_session_loader import build_manifest


def _write_2d_pose(path: Path, bodyparts: tuple[str, ...], rows: int = 3) -> None:
    """Write a DeepLabCut/LightningPose multi-index CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    scorer = ["scorer"] + ["m"] * (len(bodyparts) * 3)
    parts = ["bodyparts"] + [bp for bp in bodyparts for _ in range(3)]
    coords = ["coords"] + ["x", "y", "likelihood"] * len(bodyparts)
    lines = [",".join(scorer), ",".join(parts), ",".join(coords)]
    for frame in range(rows):
        values = [str(frame)]
        for index in range(len(bodyparts)):
            values += [str(100.0 + index + frame), str(200.0 + index + frame), "0.99"]
        lines.append(",".join(values))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture()
def aol_session(tmp_path: Path) -> Path:
    """An AOL session with two cameras, an ensemble + two models, and 3D EKS."""
    session = tmp_path / "09-35-24"
    session.mkdir()

    timing = "1\t0.000\t08-05-2026;09:35:26.3120\n2\t4.346\t08-05-2026;09:35:26.3160\n"
    for camera in ("FaceCam", "SideCam"):
        (session / f"{camera}.mp4").write_bytes(b"\x00" * 64)
        (session / f"{camera}-relative times.txt").write_text(timing, encoding="utf-8")

    (session / "trial_config.yml").write_text("hardware:\n  camera_fps: 230.0\n", encoding="utf-8")

    bodyparts = ("head_bar", "left_toe")
    for camera in ("FaceCam", "SideCam"):
        _write_2d_pose(session / "predictions" / "default_sv" / f"{camera}_eks.csv", bodyparts)
        for model in ("model_0", "model_1"):
            _write_2d_pose(
                session / "predictions" / "default_sv" / model / f"{camera}.csv", bodyparts
            )

    eks_dir = session / "pose-3d" / "default_sv"
    eks_dir.mkdir(parents=True)
    (eks_dir / "_eks.csv").write_text(
        "head_bar_x,head_bar_y,head_bar_z,left_toe_x,left_toe_y,left_toe_z,fnum\n"
        "-56.7,5.9,461.3,-29.8,54.7,461.4,0\n"
        "-56.6,5.8,461.2,-29.7,54.6,461.3,1\n",
        encoding="utf-8",
    )
    return session


def test_manifest_binds_each_2d_track_to_its_camera(aol_session: Path) -> None:
    manifest = build_manifest(aol_session)

    assert len(manifest.pose_2d_tracks) == 6  # 2 cameras x (1 ensemble + 2 models)
    by_camera: dict[str, set[str]] = {}
    for track in manifest.pose_2d_tracks:
        by_camera.setdefault(track.camera, set()).add(track.model)
    assert by_camera == {
        "FaceCam": {"eks", "model_0", "model_1"},
        "SideCam": {"eks", "model_0", "model_1"},
    }
    # A SideCam file must never be attributed to FaceCam.
    for track in manifest.pose_2d_tracks:
        assert track.camera.lower() in track.path.stem.lower() + track.path.parent.name.lower()


def test_2d_candidates_target_their_own_camera_video(aol_session: Path) -> None:
    from avialview.core.registry import LoaderRegistry

    worker = DropScanWorker([aol_session], LoaderRegistry())
    candidates = worker._collect_aol_candidates(aol_session)

    overlay = [
        (path, config)
        for path, _loader, config in candidates
        if config and config.get("role") == "overlay2d"
    ]
    assert len(overlay) == 6
    for path, config in overlay:
        camera = config["overlay_camera"]
        assert Path(config["overlay_video"]).name.startswith(camera), (
            f"{path.name} targets {config['overlay_video']} but belongs to {camera}"
        )
        # 2D overlays are drawn on the pane's own media clock.
        assert "start_epoch" not in config

    ensembles = [c for _p, c in overlay if c["overlay_is_ensemble"]]
    assert len(ensembles) == 2
    assert {c["overlay_label"] for _p, c in overlay} == {"eks", "model_0", "model_1"}


def test_3d_candidate_is_tagged_for_the_3d_view(aol_session: Path) -> None:
    from avialview.core.registry import LoaderRegistry

    worker = DropScanWorker([aol_session], LoaderRegistry())
    candidates = worker._collect_aol_candidates(aol_session)

    pose3d = [c for _p, _l, c in candidates if c and c.get("role") == "pose3d"]
    assert len(pose3d) == 1
    assert pose3d[0]["start_epoch"] > 0.0  # 3D lives on master time


def test_eks_without_camera_name_does_not_match_every_video(aol_session: Path) -> None:
    """'_eks.csv' has an empty leading token; it must not match by empty substring."""
    from avialview.core.registry import LoaderRegistry

    manifest = build_manifest(aol_session)
    # Give the two cameras distinct start epochs.
    paths = sorted(manifest.video_start_epochs)
    manifest.video_start_epochs[paths[0]] = 1000.0
    manifest.video_start_epochs[paths[1]] = 2000.0

    worker = DropScanWorker([aol_session], LoaderRegistry())
    resolved = worker._resolve_eks_start_epoch(
        aol_session / "pose-3d" / "default_sv" / "_eks.csv", manifest
    )
    # Falls back to the earliest camera start, deterministically.
    assert resolved == 1000.0


def _finish_import(
    window: object,
    source_path: str,
    cache_dir: Path,
    channels: list[str],
    config: dict[str, object],
) -> None:
    """Complete one import through the routing path, without the worker/dialog.

    Mirrors test_ui_main.test_programmatic_import_completion_needs_no_progress_dialog:
    the import worker and its progress dialog are covered elsewhere, and what
    matters here is the routing decision _on_import_finished makes.
    """
    import numpy as np

    from avialview.core.inspection import SourceInspection
    from avialview.core.pyramid import PyramidBuilder

    cache_dir.mkdir(parents=True, exist_ok=True)
    times = np.array([0.0, 1.0], dtype=np.float64)
    for index, channel in enumerate(channels):
        PyramidBuilder(cache_dir, channel).build_and_save(
            times, np.array([100.0 + index, 101.0 + index], dtype=np.float64)
        )
    window._on_import_finished(  # type: ignore[attr-defined]
        source_path,
        str(cache_dir),
        channels,
        (0.0, 1.0),
        SourceInspection(path=source_path, import_config=dict(config)),
    )


def test_2d_pose_overlays_its_camera_and_is_not_plotted(tmp_path: Path, qtbot, monkeypatch) -> None:
    """2D pose reaches only its own camera's overlay, and creates no plot rows."""
    from avialview.ui.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "_run_diagnostics", lambda _self: None)
    window = MainWindow()
    qtbot.addWidget(window)

    face_video = str(tmp_path / "FaceCam.mp4")
    side_video = str(tmp_path / "SideCam.mp4")
    channels = ["head_bar_x", "head_bar_y", "left_toe_x", "left_toe_y"]

    for camera, video in (("FaceCam", face_video), ("SideCam", side_video)):
        for label, ensemble in (("eks", True), ("model_0", False), ("model_1", False)):
            _finish_import(
                window,
                f"{camera}_{label}.csv",
                tmp_path / f"{camera}_{label}.avialcache",
                channels,
                {
                    "role": "overlay2d",
                    "overlay_video": video,
                    "overlay_camera": camera,
                    "overlay_label": label,
                    "overlay_is_ensemble": ensemble,
                },
            )

    assert window.plot_pane.channels == [], (
        f"2D pose created plot rows: {[c.name for c in window.plot_pane.channels]}"
    )
    assert set(window._overlay_sources) == {face_video, side_video}
    for video in (face_video, side_video):
        assert len(window._overlay_sources[video]) == 3  # ensemble + 2 models

    window.close()


def test_3d_pose_reaches_the_3d_view_and_is_not_plotted(tmp_path: Path, qtbot, monkeypatch) -> None:
    from avialview.ui.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "_run_diagnostics", lambda _self: None)
    window = MainWindow()
    qtbot.addWidget(window)

    _finish_import(
        window,
        "_eks.csv",
        tmp_path / "eks.avialcache",
        ["head_bar_x", "head_bar_y", "head_bar_z"],
        {"role": "pose3d"},
    )

    assert window.plot_pane.channels == []
    assert window._pose_3d_sources
    assert window.tracking_3d_pane.canvas.point_count == 1
    window.close()


def test_non_pose_sources_still_plot(tmp_path: Path, qtbot, monkeypatch) -> None:
    """Ordinary recorded signals keep their plot rows."""
    from avialview.ui.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "_run_diagnostics", lambda _self: None)
    window = MainWindow()
    qtbot.addWidget(window)

    _finish_import(window, "encoder_log.txt", tmp_path / "enc.avialcache", ["encoder_velocity"], {})

    assert [c.name for c in window.plot_pane.channels] == ["encoder_velocity"]
    assert not window._overlay_sources
    assert not window._pose_3d_sources
    window.close()


def test_overlay_tracks_get_distinct_colours_and_labels(tmp_path: Path, qtbot, monkeypatch) -> None:
    """Overlaid models must be distinguishable by label, not colour alone."""
    from avialview.ui.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "_run_diagnostics", lambda _self: None)
    window = MainWindow()
    qtbot.addWidget(window)

    video = str(tmp_path / "FaceCam.mp4")
    captured: list[object] = []
    monkeypatch.setattr(
        window.video_grid,
        "set_overlay_tracks",
        lambda _path, tracks: captured.append(tracks),
    )

    for label, ensemble in (("eks", True), ("model_0", False), ("model_1", False)):
        _finish_import(
            window,
            f"FaceCam_{label}.csv",
            tmp_path / f"FaceCam_{label}.avialcache",
            ["head_bar_x", "head_bar_y"],
            {
                "role": "overlay2d",
                "overlay_video": video,
                "overlay_camera": "FaceCam",
                "overlay_label": label,
                "overlay_is_ensemble": ensemble,
            },
        )

    tracks = captured[-1]
    labels = [track.label for track in tracks]
    colours = [track.color for track in tracks]
    assert sorted(labels) == ["eks", "model_0", "model_1"]
    assert len(set(colours)) == 3, "overlaid sources must not share a colour"
    ensembles = [track for track in tracks if track.is_ensemble]
    assert len(ensembles) == 1 and ensembles[0].label == "eks"
    window.close()
