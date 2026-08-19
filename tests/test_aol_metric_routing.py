"""AOL extracted-metric routing: data_root MAT exports become plot rows.

Unlike pose data (D-046), extracted per-frame metrics (optical flow, motion
index, ...) are ordinary recorded signals -- they carry no `role` and must
reach the plot pane exactly like the encoder trace.
"""

from pathlib import Path

import numpy as np
import pytest

scipy_io = pytest.importorskip("scipy.io")


def _write_metric_mat(path: Path, data: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scipy_io.savemat(str(path), {"roi_metric_data": data})


@pytest.fixture()
def aol_session_with_metrics(tmp_path: Path) -> Path:
    """An AOL session with one camera plus a nested data_root-style export."""
    session = tmp_path / "09-35-24"
    session.mkdir()

    (session / "EyeCam.mp4").write_bytes(b"\x00" * 64)
    (session / "EyeCam-relative times.txt").write_text(
        "1\t0.000\t08-05-2026;09:35:26.3120\n", encoding="utf-8"
    )
    (session / "trial_config.yml").write_text("hardware:\n  camera_fps: 100.0\n", encoding="utf-8")

    # A data_root folder, arbitrarily named and nested, per the schema's own
    # "the folder name is not fixed" contract.
    data_root = session / "optical_flow_and_MI_data" / "09-35-24" / "EyeCam"
    _write_metric_mat(data_root / "111__motion_index.mat", np.array([[0.1], [0.2], [0.3]]))
    _write_metric_mat(
        data_root / "222__optical_flow.mat",
        np.array([[0.1, 1.0, 2.0, 0.5, 9.0], [0.2, 1.1, 2.1, 0.6, 9.1]]),
    )
    # Never a channel: a static reference frame, not a time series.
    _write_metric_mat(data_root / "thumbnail.mat", np.zeros((4, 4)))

    return session


def test_manifest_finds_metric_files_regardless_of_data_root_name(
    aol_session_with_metrics: Path,
) -> None:
    from avialsync.loaders.aol_session_loader import build_manifest

    manifest = build_manifest(aol_session_with_metrics)

    assert len(manifest.metric_files) == 2
    metrics = {(mf.roi_id, mf.metric) for mf in manifest.metric_files}
    assert metrics == {("111", "motion_index"), ("222", "optical_flow")}
    assert all(mf.camera == "EyeCam" for mf in manifest.metric_files)
    assert not any("thumbnail" in str(mf.path) for mf in manifest.metric_files)


def test_metric_items_carry_no_role_and_reach_plot_rows(
    aol_session_with_metrics: Path,
) -> None:
    from avialsync.core.registry import LoaderRegistry
    from avialsync.loaders.aol_session_loader import AOLSessionSource

    layout = AOLSessionSource().scan(aol_session_with_metrics, LoaderRegistry())

    metric_items = [
        item
        for item in layout.items
        if "motion_index" in item.path.name or "optical_flow" in item.path.name
    ]
    assert len(metric_items) == 2
    for item in metric_items:
        assert "role" not in item.config  # ordinary signal, not pose (D-046)
        assert item.config["auto_resolved"] is True
        assert item.config["fps"] == 100.0

    labels = {item.label for item in metric_items}
    assert "111__motion_index.mat — EyeCam motion index" in labels
    assert "222__optical_flow.mat — EyeCam optical flow" in labels


def test_metric_items_time_align_to_the_same_camera_epoch_as_video(
    aol_session_with_metrics: Path,
) -> None:
    """The metric file's start_epoch must match its camera's video, not 0."""
    from avialsync.core.registry import LoaderRegistry
    from avialsync.loaders.aol_session_loader import AOLSessionSource

    layout = AOLSessionSource().scan(aol_session_with_metrics, LoaderRegistry())

    video_item = next(item for item in layout.items if item.path.name == "EyeCam.mp4")
    metric_item = next(item for item in layout.items if item.path.name == "111__motion_index.mat")

    # Video's config carries offset = -start_epoch; the metric loader carries
    # start_epoch directly (frame-indexed, like EKS). Both must agree.
    np.testing.assert_allclose(-video_item.config["offset"], metric_item.config["start_epoch"])


def test_metric_file_in_unmatched_camera_folder_still_loads(tmp_path: Path) -> None:
    """A data_root dropped without its sibling videos still loads, unaligned."""
    from avialsync.core.registry import LoaderRegistry
    from avialsync.loaders.aol_session_loader import AOLSessionSource

    session = tmp_path / "09-35-24"
    session.mkdir()
    (session / "EyeCam.mp4").write_bytes(b"\x00" * 64)
    (session / "EyeCam-relative times.txt").write_text(
        "1\t0.000\t08-05-2026;09:35:26.3120\n", encoding="utf-8"
    )
    _write_metric_mat(session / "data" / "UnknownCam" / "1__motion_index.mat", np.array([[1.0]]))

    layout = AOLSessionSource().scan(session, LoaderRegistry())
    metric_item = next(item for item in layout.items if item.path.name == "1__motion_index.mat")

    assert "role" not in metric_item.config
    assert metric_item.config["start_epoch"] == 0.0
    assert "UnknownCam" in metric_item.label
