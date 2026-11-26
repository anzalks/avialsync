"""Tests for calibrated 3D-to-2D reprojected pose CSV export (core, worker, and UI)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.calibration import Calibration, CameraModel, write_calibration
from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.errors import ExportError
from avialsync.core.inspection import SourceInspection
from avialsync.core.pose import PosePoint, PoseSchema
from avialsync.core.pyramid import PyramidBuilder, PyramidReader
from avialsync.core.reprojected_pose_export import (
    REPROJECTED_SCORER,
    is_reprojected_pose_path,
    match_3d_to_2d_names,
    project_frames_to_camera,
    reprojected_copy_path,
    write_reprojected_copy,
    write_reprojected_csv,
)
from avialsync.core.timeline import TimeMap
from avialsync.engine.changes_export_worker import ChangesExportWorker, ReprojectedPoseJob
from avialsync.engine.export_worker import ReaderReference
from avialsync.ui import recovery
from avialsync.ui.controllers import changes_export_controller
from avialsync.ui.controllers.calibration_controller import CalibrationState
from avialsync.ui.export_dialog import ANNOTATIONS, REPROJECTED_POSE
from avialsync.ui.main_window import MainWindow
from avialsync.ui.reprojected_pose_export import (
    can_export_reprojected_pose,
    ensure_reprojection_ready,
)
from tests.wheel_fixture import CAMERAS


@pytest.fixture(autouse=True)
def _isolated_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    folder = tmp_path / "appdata"
    folder.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: folder)
    yield folder


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    if isValid(win):
        win.close()


def _write_dlc_template(path: Path) -> None:
    """Write a 2D DLC/EKS CSV with scorer, likelihood, smoother columns, and a 2D-only part."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["scorer", *(["DLC_resnet50"] * 8)])
        writer.writerow(
            [
                "bodyparts",
                "nose",
                "nose",
                "nose",
                "nose",
                "paw",
                "paw",
                "whisker_only",
                "whisker_only",
            ]
        )
        writer.writerow(["coords", "x", "y", "likelihood", "zscore", "x", "y", "x", "y"])
        writer.writerow([0, 1.0, 2.0, 0.91, 0.12, 3.0, 4.0, 77.0, 88.0])
        writer.writerow([1, 5.0, 6.0, 0.42, 1.85, 7.0, 8.0, 79.0, 89.0])
        writer.writerow([2, 9.0, 10.0, 0.15, 3.40, 11.0, 12.0, 80.0, 90.0])


def _build_3d_cache(
    cache_dir: Path,
    times: np.ndarray,
    points_xyz: dict[str, np.ndarray],
) -> list[MappedChannelReader]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    readers: list[MappedChannelReader] = []
    tmap = TimeMap()
    for name, xyz in points_xyz.items():
        for axis_i, axis in enumerate(("x", "y", "z")):
            ch = f"{name}_{axis}"
            PyramidBuilder(cache_dir, ch).build_and_save(times, xyz[:, axis_i])
            readers.append(MappedChannelReader(PyramidReader(cache_dir, ch), tmap, str(cache_dir)))
    return readers


# ── Headless core: naming, matching, projection, and CSV writers ─────


def test_reprojected_path_helpers_and_name_matching() -> None:
    src = Path("/data/FaceCam_eks.csv")
    dest = reprojected_copy_path(src)
    assert dest == Path("/data/FaceCam_eks_reprojected.csv")
    assert is_reprojected_pose_path(dest)
    assert is_reprojected_pose_path("CAM_REPROJECTED.CSV")
    assert not is_reprojected_pose_path(src)

    matched = match_3d_to_2d_names(
        [
            "",
            "head_bar",
            "CaseA",
            "casea",
            "ensemble_paw",
            "snout",
            "dup1_ear",
            "dup2_ear",
            "tail",
        ],
        ["", "head_bar", "TAIL", "CASEA", "paw", "dlc_snout", "ear", "whisker"],
    )
    assert matched == {
        "head_bar": "head_bar",
        "TAIL": "tail",
        "paw": "ensemble_paw",
        "dlc_snout": "snout",
    }


def test_project_frames_to_camera_filters_nan_and_points_behind_camera() -> None:
    cam = CameraModel(
        name="Front",
        size=(640, 480),
        matrix=np.array([[500.0, 0.0, 320.0], [0.0, 500.0, 240.0], [0.0, 0.0, 1.0]]),
        distortions=np.zeros(5),
        rotation=np.zeros(3),
        translation=np.zeros(3),
    )
    world = {
        "all_nan": np.full((2, 3), np.nan),
        "all_behind": np.array([[0.0, 0.0, -10.0], [1.0, 2.0, 0.0]]),
        "mixed": np.array(
            [
                [np.nan, 0.0, 50.0],
                [0.0, 0.0, -5.0],
                [10.0, -20.0, 100.0],
            ]
        ),
    }
    projected = project_frames_to_camera(cam, world)
    assert np.all(np.isnan(projected["all_nan"]))
    assert np.all(np.isnan(projected["all_behind"]))
    assert np.all(np.isnan(projected["mixed"][:2]))
    assert np.allclose(projected["mixed"][2], [370.0, 140.0])


def test_write_reprojected_copy_preserves_scorer_likelihood_derived_and_unmatched_columns(
    tmp_path: Path,
) -> None:
    source = tmp_path / "FaceCam_eks.csv"
    _write_dlc_template(source)
    target = reprojected_copy_path(source)

    projected = {
        "nose": np.array([[101.5, 202.25], [np.nan, np.nan]]),
        "ensemble_paw": np.array([[301.0, 401.0], [302.0, 402.0]]),
    }
    report = write_reprojected_copy(
        source,
        target,
        projected,
        sources=(tmp_path / "pose3d.csv",),
        session=tmp_path / "trial.avv",
    )
    # Frame 0: nose + paw projected (2); Frame 1: nose NaN (cleared) + paw projected (1);
    # Frame 2: past len(xy)=2 -> nose + paw cleared (2).
    assert report.rows == 3
    assert report.projected_rows == 2
    assert report.projected_points == 3
    assert report.cleared_points == 3

    rows = list(csv.reader(target.open(newline="", encoding="utf-8")))
    # Header rows — including original scorer — stay untouched!
    original_rows = list(csv.reader(source.open(newline="", encoding="utf-8")))
    assert rows[:3] == original_rows[:3]

    # Row 0 (frame 0): nose x/y & paw x/y replaced; likelihood, zscore, whisker_only untouched!
    assert float(rows[3][1]) == pytest.approx(101.5)
    assert float(rows[3][2]) == pytest.approx(202.25)
    assert rows[3][3] == "0.91"
    assert rows[3][4] == "0.12"
    assert float(rows[3][5]) == pytest.approx(301.0)
    assert float(rows[3][6]) == pytest.approx(401.0)
    assert rows[3][7:9] == ["77.0", "88.0"]

    # Row 1 (frame 1): nose cleared to "", likelihood 0.42 & zscore 1.85 untouched, paw projected!
    assert rows[4][1:5] == ["", "", "0.42", "1.85"]
    assert float(rows[4][5]) == pytest.approx(302.0)
    assert float(rows[4][6]) == pytest.approx(402.0)
    assert rows[4][7:9] == ["79.0", "89.0"]

    # Row 2 (frame 2): out-of-range in projected -> cleared x/y, likelihood 0.15 untouched!
    assert rows[5][1:5] == ["", "", "0.15", "3.4"]
    assert rows[5][5:9] == ["", "", "80.0", "90.0"]

    companion = target.with_name("FaceCam_eks_reprojected_avialsync.json")
    meta = json.loads(companion.read_text(encoding="utf-8"))
    assert meta["format"] == "avialsync-reprojected-pose/1"
    assert meta["edit_counts"]["projected_points"] == 3


def test_write_reprojected_copy_edge_cases_and_validation(tmp_path: Path) -> None:
    source = tmp_path / "pose.csv"
    # Header where "broken" has only x (no y), plus malformed/short/empty/negative data rows
    with open(source, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["scorer", "DLC", "DLC", "DLC"])
        writer.writerow(["bodyparts", "nose", "nose", "broken"])
        writer.writerow(["coords", "x", "y", "x"])
        writer.writerow([])
        writer.writerow(["not_a_frame", "1", "2", "3"])
        writer.writerow(["-1", "1", "2", "3"])
        writer.writerow(["0", "1"])  # shorter than y_col=2
        writer.writerow(["1", "5", "6", "7"])

    with pytest.raises(ValueError, match="different path"):
        write_reprojected_copy(source, source, {})

    bad = tmp_path / "plain.csv"
    bad.write_text("time,val\n0.0,1.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no DeepLabCut"):
        write_reprojected_copy(bad, tmp_path / "plain_reprojected.csv", {})

    # Empty targets dict exercises `and targets` False branch
    unmatched_target = tmp_path / "unmatched_reprojected.csv"
    rep_unmatched = write_reprojected_copy(source, unmatched_target, {"other": np.zeros((2, 2))})
    assert rep_unmatched.rows == 5
    assert rep_unmatched.projected_points == 0

    # Matched nose + incomplete "broken" column + malformed rows
    edge_target = tmp_path / "edge_reprojected.csv"
    rep_edge = write_reprojected_copy(
        source,
        edge_target,
        {
            "nose": np.array([[10.0, 20.0], [30.0, 40.0]]),
            "broken": np.array([[1.0, 2.0], [3.0, 4.0]]),
        },
    )
    assert rep_edge.rows == 5
    assert rep_edge.projected_points == 1
    assert rep_edge.cleared_points == 0


def test_write_reprojected_csv_standalone_single_and_multi_animal(tmp_path: Path) -> None:
    single_target = tmp_path / "CamA_reprojected.csv"
    rep_single = write_reprojected_csv(
        single_target,
        ["nose"],
        {"nose": np.array([[12.5, 34.5], [np.nan, np.nan]])},
        frame_count=3,
    )
    assert rep_single.rows == 3
    assert rep_single.projected_rows == 1
    assert rep_single.projected_points == 1
    assert rep_single.cleared_points == 2
    rows_single = list(csv.reader(single_target.open(newline="", encoding="utf-8")))
    assert rows_single[0] == ["scorer", REPROJECTED_SCORER, REPROJECTED_SCORER, REPROJECTED_SCORER]
    assert rows_single[1] == ["bodyparts", "nose", "nose", "nose"]
    assert rows_single[2] == ["coords", "x", "y", "likelihood"]
    assert rows_single[3] == ["0", "12.5", "34.5", "1.0"]
    assert rows_single[4] == ["1", "", "", ""]
    assert rows_single[5] == ["2", "", "", ""]

    multi_target = tmp_path / "CamB_reprojected.csv"
    rep_multi = write_reprojected_csv(
        multi_target,
        ["m1_nose"],
        {"m1_nose": np.array([[50.0, 60.0]])},
        frame_count=1,
        point_labels={"m1_nose": ("m1", "nose")},
    )
    assert rep_multi.projected_points == 1
    rows_multi = list(csv.reader(multi_target.open(newline="", encoding="utf-8")))
    assert rows_multi[1] == ["individuals", "m1", "m1", "m1"]
    assert rows_multi[2] == ["bodyparts", "nose", "nose", "nose"]


# ── Worker & UI integration: Export Changes + Exports tab ────────────


def test_worker_reprojected_pose_job_respects_time_map_and_gaps(tmp_path: Path, qtbot) -> None:
    cam = CAMERAS["Front"]
    truth_0 = np.array([10.0, -20.0, 95.0])
    truth_1 = np.array([15.0, -15.0, 100.0])
    truth_2 = np.array([20.0, -10.0, 105.0])
    # Regular dt=0.1 except a 2.0 s gap between index 1 (t=1.1) and index 2 (t=3.1).
    times_3d = np.array([1.0, 1.1, 3.1, 3.2], dtype=np.float64)
    readers = _build_3d_cache(
        tmp_path / "cache3d",
        times_3d,
        {"nose": np.vstack([truth_0, truth_1, truth_2, truth_2])},
    )
    by_ch = {r.channel_id: ReaderReference.from_reader(r) for r in readers}
    template = tmp_path / "Front_eks.csv"
    _write_dlc_template(template)
    target = reprojected_copy_path(template)

    # Video local times [0.0, 1.0, 2.1] shifted by offset=-1.0 -> master [1.0, 2.0, 3.1].
    # At master 2.0, sample index 1 (t=1.1) precedes the 2.0 s gap -> masked as NaN!
    video_map = TimeMap(offset=-1.0)
    job = ReprojectedPoseJob(
        target=target,
        video=tmp_path / "Front.mp4",
        camera=cam,
        pose_3d_source=tmp_path / "pose3d.csv",
        calibration_path=tmp_path / "calibration.toml",
        axes={"nose": (by_ch["nose_x"], by_ch["nose_y"], by_ch["nose_z"])},
        video_time_map=video_map,
        template_2d=template,
        frame_times=np.array([0.0, 1.0, 2.1], dtype=np.float64),
    )
    worker = ChangesExportWorker([job])
    results: list[list[str]] = []
    errors: list[str] = []
    worker.finished.connect(results.append)
    worker.error.connect(errors.append)
    worker.run()

    assert not errors
    assert "2 reprojected point(s) in 3 row(s)" in results[0][0]
    rows = list(csv.reader(target.open(newline="", encoding="utf-8")))
    px0 = cam.project(truth_0)[0]
    px2 = cam.project(truth_2)[0]
    assert float(rows[3][1]) == pytest.approx(float(px0[0]))
    assert float(rows[3][2]) == pytest.approx(float(px0[1]))
    assert rows[3][3] == "0.91"  # likelihood untouched
    assert rows[4][1:4] == ["", "", "0.42"]  # gapped 3D interval cleared, likelihood kept
    assert float(rows[5][1]) == pytest.approx(float(px2[0]))
    assert float(rows[5][2]) == pytest.approx(float(px2[1]))
    assert rows[5][3] == "0.15"  # likelihood untouched

    for r in readers:
        r.source_reader.close()


def test_export_changes_and_exports_tab_offer_reprojected_pose_and_preserve_manual_selection(
    window: MainWindow, tmp_path: Path, qtbot
) -> None:
    assert not window._act_export_changes.isEnabled()
    assert not can_export_reprojected_pose(window)

    cam_front = str(tmp_path / "Front.mp4")
    cam_left = str(tmp_path / "Left.mp4")
    (tmp_path / "Front.mp4").write_bytes(b"")
    (tmp_path / "Left.mp4").write_bytes(b"")
    pose_front = tmp_path / "Front_eks.csv"
    _write_dlc_template(pose_front)

    pose3d_dir = tmp_path / "pose-3d"
    pose3d_dir.mkdir()
    pose3d_path = str(pose3d_dir / "session_3d.csv")
    cal_path = pose3d_dir / "calibration.toml"
    write_calibration(
        cal_path,
        Calibration(cameras=(CAMERAS["Front"], CAMERAS["Left"])),
    )

    truth = np.array([[10.0, -20.0, 95.0], [12.0, -18.0, 98.0], [14.0, -16.0, 100.0]])
    readers = _build_3d_cache(
        tmp_path / "cache_ui",
        np.array([0.0, 0.1, 0.2], dtype=np.float64),
        {"nose": truth, "paw": truth + 5.0},
    )
    window._pose_3d_sources[pose3d_path] = readers
    window._inspections[pose3d_path] = SourceInspection(
        path=Path(pose3d_path),
        pose=PoseSchema(
            points=(
                PosePoint("", "nose", ("x", "y", "z")),
                PosePoint("", "paw", ("x", "y", "z")),
            )
        ),
    )
    window.video_grid._paths = [cam_front, cam_left]
    window._video_frame_times[cam_front] = np.array([0.0, 0.1, 0.2])
    window._video_frame_times[cam_left] = np.array([0.0, 0.1, 0.2])
    window._overlay_sources[cam_front] = {
        str(pose_front): {"label": "EKS", "is_ensemble": True, "points": {}}
    }
    window._calibration_state = CalibrationState(
        path=cal_path,
        cameras={cam_front: CAMERAS["Front"], cam_left: CAMERAS["Left"]},
    )
    window._refresh_action_availability()

    # Both File -> Export Changes... and the Exports inspector tab button follow the same QAction!
    assert window._act_export_changes.isEnabled()
    assert window.export_panel._buttons["changes"].isEnabled()

    # With no manual edits, reprojected exports are offered and ticked by default.
    items = changes_export_controller.available_exports(window)
    assert [it.kind for it in items] == [REPROJECTED_POSE, REPROJECTED_POSE]
    assert all(it.selected for it in items)
    assert items[0].target == tmp_path / "Front_eks_reprojected.csv"
    assert items[1].target == tmp_path / "Left_reprojected.csv"

    # Execute both jobs (template copy on Front + standalone synthesis on Left)
    jobs = [changes_export_controller._job_for(window, it) for it in items]
    assert all(isinstance(j, ReprojectedPoseJob) for j in jobs)
    worker = ChangesExportWorker(jobs)
    done: list[list[str]] = []
    worker.finished.connect(done.append)
    worker.run()
    assert len(done) == 1 and len(done[0]) == 2
    assert items[0].target.is_file()
    assert items[1].target.is_file()

    # When a manual annotation also exists, manual changes stay ticked and reprojections unticked.
    window.annotation_store.add_point(0.1, label="reach")
    mixed = changes_export_controller.available_exports(window)
    assert [it.kind for it in mixed] == [ANNOTATIONS, REPROJECTED_POSE, REPROJECTED_POSE]
    assert mixed[0].selected is True
    assert mixed[1].selected is False
    assert mixed[2].selected is False

    for r in readers:
        r.source_reader.close()


def test_ensure_reprojection_ready_requests_calibration_only_when_needed(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cam_a = str(tmp_path / "A.mp4")
    cam_b = str(tmp_path / "B.mp4")
    pose3d = str(tmp_path / "pose-3d" / "p3d.csv")
    readers = _build_3d_cache(tmp_path / "c3d", np.array([0.0, 0.1]), {"nose": np.ones((2, 3))})
    window._pose_3d_sources[pose3d] = readers
    window.video_grid._paths = [cam_a, cam_b]

    asked: list[bool] = []
    monkeypatch.setattr(
        "avialsync.ui.controllers.calibration_controller.acquire_calibration",
        lambda _w, on_ready, _on_cancel: (asked.append(True), on_ready()),
    )
    proceeded: list[bool] = []
    assert (
        ensure_reprojection_ready(
            window, has_manual_changes=True, proceed=lambda: proceeded.append(True)
        )
        is False
    )
    assert not asked

    assert (
        ensure_reprojection_ready(
            window, has_manual_changes=False, proceed=lambda: proceeded.append(True)
        )
        is True
    )
    assert asked == [True]
    assert proceeded == [True]

    for r in readers:
        r.source_reader.close()


def test_worker_cancellation_and_missing_video_raise_export_error(tmp_path: Path) -> None:
    readers = _build_3d_cache(tmp_path / "cancel_cache", np.array([0.0]), {"nose": np.ones((1, 3))})
    by_ch = {r.channel_id: ReaderReference.from_reader(r) for r in readers}
    missing_video_job = ReprojectedPoseJob(
        target=tmp_path / "out_reprojected.csv",
        video=tmp_path / "absent.mp4",
        camera=CAMERAS["Front"],
        pose_3d_source=tmp_path / "p3d.csv",
        calibration_path=tmp_path / "cal.toml",
        axes={"nose": (by_ch["nose_x"], by_ch["nose_y"], by_ch["nose_z"])},
        frame_times=None,
    )
    from avialsync.engine.reprojected_pose_job import run_reprojected_pose_job

    with pytest.raises(ExportError, match="unavailable"):
        run_reprojected_pose_job(missing_video_job)

    cancel_job = ReprojectedPoseJob(
        target=tmp_path / "out_reprojected.csv",
        video=tmp_path / "absent.mp4",
        camera=CAMERAS["Front"],
        pose_3d_source=tmp_path / "p3d.csv",
        calibration_path=tmp_path / "cal.toml",
        axes={"nose": (by_ch["nose_x"], by_ch["nose_y"], by_ch["nose_z"])},
        frame_times=np.array([0.0]),
    )
    with pytest.raises(ExportError, match="cancelled"):
        run_reprojected_pose_job(cancel_job, should_cancel=lambda: True)

    for r in readers:
        r.source_reader.close()
