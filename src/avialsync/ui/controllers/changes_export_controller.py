"""The one channel the user's own work leaves by (D-100).

Snapshot, trimmed clip, and data slice render a *range of the recording*.  This
renders *what a person did to it*: their flagged frames and labelled ranges,
their corrected pose data, and a retraining set built from the frames they
corrected.  Those three are chosen together and reported together, because they
are one body of work and the user wants one answer about where it went.

Nothing is offered for a source with nothing to export, so what the dialog shows
is exactly what there is to save.  Every destination defaults beside the data it
came from and every one is editable.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QDialog

from avialsync.core import dlc_export, pose_export
from avialsync.ui.annotations import marker_rows
from avialsync.ui.controllers import corrections_controller
from avialsync.ui.export_dialog import (
    ANNOTATIONS,
    CORRECTED_POSE,
    RETRAINING_SET,
    ExportChangesDialog,
    ExportItem,
)
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

#: Scorer name written into a retraining set. DLC keys labelled data by scorer,
#: so a set produced here stays distinguishable from the model's own and from a
#: colleague's, which is the point of the field.
RETRAINING_SCORER = "avialsync"


def available_exports(window: MainWindow) -> list[ExportItem]:
    """List every artifact this session's own work could be written as.

    Only what has content: a recording nobody corrected produces no rows, so
    what the dialog shows is exactly what there is to save.
    """
    items: list[ExportItem] = []
    if window.annotation_store.markers:
        items.append(
            ExportItem(
                kind=ANNOTATIONS,
                title=tr("Annotations"),
                detail=tr("{n} flag(s) and range(s), one row per camera.").format(
                    n=len(window.annotation_store.markers)
                ),
                target=_annotation_target(window),
            )
        )

    for source_id in sorted(window.point_edits.source_ids()):
        source = Path(source_id)
        count = window.point_edits.count_for(source_id)
        items.append(
            ExportItem(
                kind=CORRECTED_POSE,
                title=tr("Corrected pose data — {source}").format(source=source.name),
                detail=tr(
                    "A copy of the pose file with {n} correction(s) applied, for analysis. "
                    "The scorer is marked so it never reads as model output."
                ).format(n=count),
                target=pose_export.corrected_copy_path(source),
                source_id=source_id,
            )
        )
        video = corrections_controller.video_for(window, source_id)
        if not video:
            continue
        video_path = Path(video)
        items.append(
            ExportItem(
                kind=RETRAINING_SET,
                title=tr("Retraining set (DeepLabCut) — {source}").format(source=source.name),
                detail=tr(
                    "The {n} corrected frame(s) as labeled data, with their images, "
                    "ready to merge into a training set."
                ).format(n=len(_corrected_indices(window, source_id))),
                target=dlc_export.collected_data_path(
                    video_path.parent, video_path.stem, RETRAINING_SCORER
                ),
                source_id=source_id,
                video=video,
                selected=False,
            )
        )
    return items


def _corrected_indices(window: MainWindow, source_id: str) -> set[int]:
    return {index for index, _point, _x, _y in window.point_edits.for_source(source_id)}


def _annotation_target(window: MainWindow) -> Path:
    """Default the annotation CSV beside the session, or beside the first camera."""
    session = getattr(window, "_session_path", None)
    if session:
        return Path(session).with_suffix(".annotations.csv")
    videos = window.video_grid.pane_paths()
    if videos:
        return Path(videos[0]).with_name("annotations.csv")
    # Home, not a bare name: a relative path in the field would be written
    # wherever the process happens to have been started from, which is not
    # somewhere the user can predict or find it again.
    return Path.home() / "annotations.csv"


def export_changes(window: MainWindow) -> None:
    """Write the session's annotations and corrected tracking data.

    One command for both, because a user who has flagged frames and corrected
    points has made one body of work and wants one answer about where it went.
    """
    items = available_exports(window)
    if not items:
        window.notifications.show_warning(
            tr("There is nothing to export yet — flag a frame or correct a tracked point first.")
        )
        return

    dialog = ExportChangesDialog(items, window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    chosen = dialog.selected_items()
    if not chosen:
        return

    jobs = [job for job in (_job_for(window, item) for item in chosen) if job is not None]
    if not jobs:
        window.notifications.show_warning(tr("Nothing was written: no artifact had any content."))
        return

    from avialsync.engine.changes_export_worker import ChangesExportWorker

    worker = ChangesExportWorker(jobs)

    def on_finished(results: list) -> None:
        window.notifications.show_success(
            tr("Exported: {summary}").format(summary="; ".join(str(line) for line in results))
        )

    def on_error(message: str) -> None:
        window.notifications.show_error(tr("The export did not finish"), details=message)

    # Wired inside `configure`: `_run_job` returns an already-running thread, so
    # a fast export can finish before a connection made afterwards exists and
    # the user is never told (HANDOUT.md trap 31).
    def _wire(thread: QThread) -> None:
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)

    window._run_job(worker, label="Exporting changes", configure=_wire)


def _job_for(window: MainWindow, item: ExportItem) -> object | None:
    """Turn a chosen artifact into a job carrying only plain data.

    Everything the worker needs is resolved here, on the UI thread, so no
    reader, widget, or store is touched from the worker (rule 3).
    """
    from avialsync.engine.changes_export_worker import (
        AnnotationJob,
        CorrectedPoseJob,
        RetrainingJob,
    )

    if item.kind == ANNOTATIONS:
        rows = marker_rows(window.annotation_store.markers)
        return AnnotationJob(target=item.target, rows=rows) if rows else None

    if item.kind == CORRECTED_POSE:
        corrections = corrections_controller.corrections_by_frame(window, item.source_id)
        if not corrections:
            return None
        return CorrectedPoseJob(
            source=Path(item.source_id), target=item.target, corrections=corrections
        )

    if item.kind == RETRAINING_SET:
        bodyparts, frames = corrections_controller.labeled_frames(window, item.source_id)
        if not frames:
            return None
        video = Path(item.video)
        return RetrainingJob(
            target=item.target,
            video=video,
            video_stem=video.stem,
            scorer=RETRAINING_SCORER,
            bodyparts=bodyparts,
            frames=frames,
            write_images=video.exists(),
        )
    return None
