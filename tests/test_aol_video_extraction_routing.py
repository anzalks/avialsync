"""AOL session routing for video-extraction-toolbox exports.

These are ordinary recorded signals, not pose: they carry no `role` and belong
on plot rows beside the encoder trace, unlike the `pose-2d`/`pose-3d` outputs
sitting in the same recording folder (D-046).
"""

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("h5py")
scipy_io = pytest.importorskip("scipy.io")

from tests.test_aol_video_extraction_loader import write_export  # noqa: E402

TIMING = "1\t0.000\t08-05-2026;09:35:26.3120\n2\t4.346\t08-05-2026;09:35:26.3160\n"


def _session_with_cameras(tmp_path: Path, *cameras: str) -> Path:
    session = tmp_path / "09-35-24"
    session.mkdir(exist_ok=True)
    for camera in cameras:
        (session / f"{camera}.mp4").write_bytes(b"\x00" * 64)
        (session / f"{camera}-relative times.txt").write_text(TIMING, encoding="utf-8")
    (session / "trial_config.yml").write_text("hardware:\n  camera_fps: 230.0\n", encoding="utf-8")
    return session


@pytest.fixture()
def session_with_exports(tmp_path: Path) -> Path:
    """A two-camera session carrying a video-extraction export for each."""
    session = _session_with_cameras(tmp_path, "FaceCam", "SideCam")
    variant = session / "video-extraction" / "default"
    write_export(variant, camera="FaceCam")
    write_export(variant, camera="SideCam")
    return session


def test_manifest_finds_one_export_per_camera(session_with_exports: Path) -> None:
    from avialsync.loaders.aol_session_loader import build_manifest

    manifest = build_manifest(session_with_exports)

    assert len(manifest.video_extraction_files) == 2
    by_camera = {export.camera: export for export in manifest.video_extraction_files}
    assert set(by_camera) == {"FaceCam", "SideCam"}
    assert all(export.variant == "default" for export in by_camera.values())
    assert all(export.metrics == ("flow_kinematics",) for export in by_camera.values())
    # A SideCam export must never be attributed to FaceCam.
    for camera, export in by_camera.items():
        assert export.path.name == f"{camera}.mat"


def test_export_items_are_plain_signals_not_pose(session_with_exports: Path) -> None:
    from avialsync.core.registry import LoaderRegistry
    from avialsync.loaders.aol_session_loader import AOLSessionSource

    layout = AOLSessionSource().scan(session_with_exports, LoaderRegistry())
    items = [item for item in layout.items if item.path.suffix == ".mat"]

    assert len(items) == 2
    for item in items:
        assert "role" not in item.config, "an ROI metric is not pose data (D-046)"
        assert item.config["auto_resolved"] is True
        # It carries its own time axis, so it must not be treated as frame-indexed.
        assert "_is_frame_indexed" not in item.config


def test_export_items_carry_both_timing_reference_points(session_with_exports: Path) -> None:
    """Only the loader can tell which axis its file holds, so it gets both."""
    from avialsync.core.registry import LoaderRegistry
    from avialsync.loaders.aol_session_loader import AOLSessionSource

    layout = AOLSessionSource().scan(session_with_exports, LoaderRegistry())
    item = next(item for item in layout.items if item.path.name == "FaceCam.mat")
    video = next(item for item in layout.items if item.path.name == "FaceCam.mp4")

    assert item.config["anchor_epoch"] == layout.anchor_epoch
    # The camera's rebased start is the same one its own video is placed at.
    np.testing.assert_allclose(item.config["start_epoch"], -video.config["offset"])


def test_export_item_is_labelled_by_camera_and_metric(session_with_exports: Path) -> None:
    from avialsync.core.registry import LoaderRegistry
    from avialsync.loaders.aol_session_loader import AOLSessionSource

    layout = AOLSessionSource().scan(session_with_exports, LoaderRegistry())
    labels = {item.label for item in layout.items if item.path.suffix == ".mat"}

    assert "FaceCam.mat - FaceCam flow_kinematics" in labels
    assert "SideCam.mat - SideCam flow_kinematics" in labels


def test_the_export_supersedes_the_per_roi_store_for_its_camera(tmp_path: Path) -> None:
    """The two hold the same numbers; importing both would plot every ROI twice.

    The per-ROI v6 store is what the exporter reads *from*, and it carries no
    time axis -- so its samples would land on synthesised timestamps beside the
    same data on real ones.
    """
    from avialsync.loaders.aol_session_loader import build_manifest

    session = _session_with_cameras(tmp_path, "FaceCam", "SideCam")
    write_export(session / "video-extraction" / "default", camera="FaceCam")

    # The upstream store, mirroring the acquisition tree, for both cameras.
    for camera in ("FaceCam", "SideCam"):
        store = session / "saved_analysis_data" / "09-35-24" / camera
        store.mkdir(parents=True)
        scipy_io.savemat(
            str(store / "542401452481478__flow_kinematics.mat"),
            {"roi_metric_data": np.zeros((4, 10))},
        )

    manifest = build_manifest(session)

    assert {e.camera for e in manifest.video_extraction_files} == {"FaceCam"}
    # FaceCam is served by its export; SideCam still falls back to the store.
    assert {m.camera for m in manifest.metric_files} == {"SideCam"}


def test_a_session_without_exports_is_unchanged(tmp_path: Path) -> None:
    """The per-ROI store still loads on its own when no export exists."""
    from avialsync.loaders.aol_session_loader import build_manifest

    session = _session_with_cameras(tmp_path, "FaceCam")
    store = session / "saved_analysis_data" / "09-35-24" / "FaceCam"
    store.mkdir(parents=True)
    scipy_io.savemat(str(store / "111__motion_index.mat"), {"roi_metric_data": np.zeros((3, 1))})

    manifest = build_manifest(session)

    assert manifest.video_extraction_files == []
    assert len(manifest.metric_files) == 1
    assert manifest.metric_files[0].camera == "FaceCam"


def test_a_foreign_mat_file_is_not_claimed(tmp_path: Path) -> None:
    """No sidecar, no match: the tree holds MATLAB files from other tools."""
    from avialsync.loaders.aol_session_loader import build_manifest

    session = _session_with_cameras(tmp_path, "FaceCam")
    scipy_io.savemat(str(session / "something_else.mat"), {"unrelated": np.zeros((2, 2))})

    manifest = build_manifest(session)

    assert manifest.video_extraction_files == []
    assert manifest.metric_files == []
