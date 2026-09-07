"""The one export channel: what it offers, what it writes, and what it says.

Export used to be four menu items and a fifth button on the annotation panel,
each with its own dialog and — in the panel's case — its own copy of the CSV
layout, written on the UI thread. This covers the single surface that replaced
it, and carries forward the three properties the removed
``AnnotationExportWorker`` used to pin: the row layout, that the worker cannot
see later edits to the store, and that an unwritable path is reported rather
than swallowed.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.dlc_export import LabeledFrame
from avialsync.core.point_edits import PointKey, PointMove
from avialsync.engine.changes_export_worker import (
    AnnotationJob,
    ChangesExportWorker,
    CorrectedPoseJob,
    RetrainingJob,
)
from avialsync.ui import recovery
from avialsync.ui.annotations import MARKER_COLUMNS, AnnotationStore, VideoFrame, marker_rows
from avialsync.ui.controllers import changes_export_controller
from avialsync.ui.export_dialog import ANNOTATIONS, CORRECTED_POSE, RETRAINING_SET
from avialsync.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def isolated_recovery_dir(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    yield target


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    if isValid(win):
        win.close()


def _pose_file(tmp_path: Path) -> Path:
    path = tmp_path / "eks.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["scorer", "DLC", "DLC", "DLC", "DLC"])
        writer.writerow(["bodyparts", "nose", "nose", "tail", "tail"])
        writer.writerow(["coords", "x", "y", "x", "y"])
        for frame in range(4):
            writer.writerow([frame, 10.0 + frame, 20.0, 30.0 + frame, 40.0])
    return path


def _run(worker: ChangesExportWorker, qtbot) -> tuple[list, list]:
    """Run a worker on this thread; it touches nothing that needs another."""
    results: list = []
    errors: list = []
    worker.finished.connect(results.append)
    worker.error.connect(errors.append)
    worker.run()
    return results, errors


# ── the annotation rows ──────────────────────────────────────────────


def test_one_row_per_marker_and_camera() -> None:
    """Carried over from the removed worker's own test."""
    store = AnnotationStore()
    store.add_point(
        1.0,
        label="stance",
        video_frames=[
            VideoFrame(path="/cam/a.mp4", frame_index=30, media_timestamp=1.0),
            VideoFrame(path="/cam/b.mp4", frame_index=31, media_timestamp=1.01),
        ],
    )
    store.add_point(2.0, label="swing")

    rows = marker_rows(store.markers)

    assert len(rows) == 3, "two cameras on the first marker, none on the second"
    assert rows[0][:3] == ["stance", "", 1.0]
    assert rows[2][3:] == ["", "", ""], "a marker with no footage still gets a row"


def test_the_layout_is_defined_once(tmp_path: Path, qtbot) -> None:
    """Three copies of these columns existed; the header comes from one now."""
    target = tmp_path / "ann.csv"
    worker = ChangesExportWorker([AnnotationJob(target=target, rows=[["a", "", 1.0, "", "", ""]])])

    _run(worker, qtbot)

    assert target.read_text(encoding="utf-8").splitlines()[0] == ",".join(MARKER_COLUMNS)


def test_the_worker_cannot_see_later_edits_to_the_store(tmp_path: Path, qtbot) -> None:
    """Rows are resolved on the UI thread, so the worker holds no store at all.

    A stronger form of the deep copy the old worker made: there is nothing left
    for a later edit to leak through.
    """
    store = AnnotationStore()
    store.add_point(1.0, label="original")
    job = AnnotationJob(target=tmp_path / "ann.csv", rows=marker_rows(store.markers))

    store.clear()
    store.add_point(9.0, label="changed")
    _run(ChangesExportWorker([job]), qtbot)

    text = job.target.read_text(encoding="utf-8")
    assert "original" in text
    assert "changed" not in text


def test_an_unwritable_path_is_reported(tmp_path: Path, qtbot) -> None:
    """A missing folder means a typo. Inventing it would hide the mistake."""
    worker = ChangesExportWorker([AnnotationJob(target=tmp_path / "nope" / "ann.csv", rows=[])])

    results, errors = _run(worker, qtbot)

    assert errors
    assert not results


# ── the worker's own reporting ───────────────────────────────────────


def test_every_artifact_is_reported_in_one_answer(tmp_path: Path, qtbot) -> None:
    """They are chosen together, so the user gets one result, not three."""
    source = _pose_file(tmp_path)
    jobs = [
        AnnotationJob(target=tmp_path / "ann.csv", rows=[["a", "", 1.0, "", "", ""]]),
        CorrectedPoseJob(
            source=source,
            target=tmp_path / "eks_corrected.csv",
            corrections={1: {"nose": (99.0, 88.0)}},
        ),
    ]

    results, errors = _run(ChangesExportWorker(jobs), qtbot)

    assert not errors
    assert len(results[0]) == 2
    assert "1 annotation row(s)" in results[0][0]
    assert "1 corrected point(s)" in results[0][1]


def test_a_retraining_set_without_its_video_says_so(tmp_path: Path, qtbot) -> None:
    """A labeled-data folder with no images cannot be trained on."""
    job = RetrainingJob(
        target=tmp_path / "labeled-data" / "SideCam" / "CollectedData_avialsync.csv",
        video=tmp_path / "missing.mp4",
        video_stem="SideCam",
        scorer="avialsync",
        bodyparts=["nose"],
        frames=[LabeledFrame(frame=3, positions={"nose": (1.0, 2.0)})],
        write_images=False,
    )

    results, errors = _run(ChangesExportWorker([job]), qtbot)

    assert not errors
    assert "images not written" in results[0][0]
    assert job.target.exists(), "the labels are still worth writing"


def test_an_unknown_job_is_an_error_not_a_silent_skip(tmp_path: Path, qtbot) -> None:
    results, errors = _run(ChangesExportWorker([object()]), qtbot)

    assert errors and "Unknown export job" in errors[0]
    assert not results


# ── what the dialog is offered ───────────────────────────────────────


def test_nothing_is_offered_for_a_session_with_no_changes(window: MainWindow) -> None:
    """What is on screen is exactly what there is to save."""
    assert changes_export_controller.available_exports(window) == []


def test_annotations_are_offered_once_there_is_one(window: MainWindow) -> None:
    window.annotation_store.add_point(1.0, label="stance")

    kinds = [item.kind for item in changes_export_controller.available_exports(window)]

    assert kinds == [ANNOTATIONS]


def test_a_corrected_source_offers_both_of_its_artifacts(
    window: MainWindow, tmp_path: Path
) -> None:
    from tests.test_fix_tracker import _register_pose_source

    pose = _pose_file(tmp_path)
    _register_pose_source(window, str(pose), [0.0, 0.1, 0.2, 0.3], rate=10.0)
    window.video_grid.point_moved.emit(
        PointMove(key=PointKey(str(pose), "nose", 1), before=None, after=(99.0, 88.0))
    )

    items = changes_export_controller.available_exports(window)

    assert [item.kind for item in items] == [CORRECTED_POSE, RETRAINING_SET]
    assert items[0].target == tmp_path / "eks_corrected.csv"
    assert items[1].target.parts[-3:] == ("labeled-data", "cam", "CollectedData_avialsync.csv")


def test_the_retraining_set_is_not_ticked_by_default(window: MainWindow, tmp_path: Path) -> None:
    """It decodes a video frame per label; that is a choice, not a default."""
    from tests.test_fix_tracker import _register_pose_source

    pose = _pose_file(tmp_path)
    _register_pose_source(window, str(pose), [0.0, 0.1, 0.2, 0.3], rate=10.0)
    window.video_grid.point_moved.emit(
        PointMove(key=PointKey(str(pose), "nose", 1), before=None, after=(99.0, 88.0))
    )

    items = changes_export_controller.available_exports(window)

    assert items[0].selected is True
    assert items[1].selected is False


def test_a_retraining_job_carries_the_whole_pose(window: MainWindow, tmp_path: Path) -> None:
    """Every body part on the frame, with the correction substituted in."""
    from tests.test_fix_tracker import _register_pose_source

    pose = _pose_file(tmp_path)
    _register_pose_source(window, str(pose), [0.0, 0.1, 0.2, 0.3], rate=10.0)
    window.video_grid.point_moved.emit(
        PointMove(key=PointKey(str(pose), "nose", 1), before=None, after=(99.0, 88.0))
    )

    from avialsync.ui.controllers import corrections_controller

    bodyparts, frames = corrections_controller.labeled_frames(window, str(pose))

    assert bodyparts == ["nose"], "the stand-in source declares one body part"
    assert len(frames) == 1
    assert frames[0].frame == 1
    assert frames[0].positions["nose"] == (99.0, 88.0)


def test_corrections_are_grouped_by_the_frame_they_sit_on(
    window: MainWindow, tmp_path: Path
) -> None:
    """The shape the corrected-copy writer streams against."""
    from avialsync.ui.controllers import corrections_controller
    from tests.test_fix_tracker import _register_pose_source

    pose = _pose_file(tmp_path)
    _register_pose_source(window, str(pose), [10.0, 10.1, 10.2, 10.3], rate=10.0)
    window.video_grid.point_moved.emit(
        PointMove(key=PointKey(str(pose), "nose", 1), before=None, after=(99.0, 88.0))
    )

    grouped = corrections_controller.corrections_by_frame(window, str(pose))

    assert grouped == {101: {"nose": (99.0, 88.0)}}, "keyed by video frame, not sample index"
