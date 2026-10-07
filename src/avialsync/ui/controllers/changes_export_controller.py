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

from avialsync.core import pose_export
from avialsync.ui.annotations import marker_rows
from avialsync.ui.controllers import corrections_controller, identity_controller
from avialsync.ui.export_dialog import (
    ANNOTATIONS,
    CORRECTED_POSE,
    RETRAINING_SET,
    ExportChangesDialog,
    ExportItem,
)
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


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

    pose_sources = window.point_edits.source_ids() | window.identity_swaps.source_ids()
    for source_id in sorted(pose_sources):
        source = Path(source_id)
        count = window.point_edits.count_for(source_id)
        swaps = window.identity_swaps.count_for(source_id)
        items.append(
            ExportItem(
                kind=CORRECTED_POSE,
                title=tr("Edited pose data — {source}").format(source=source.name),
                detail=tr(
                    "A copy of the pose file with {corrections} correction(s) and "
                    "{swaps} identity swap(s) applied, for analysis. "
                    "The scorer is marked so it never reads as model output."
                ).format(corrections=count, swaps=swaps),
                target=pose_export.corrected_copy_path(source),
                source_id=source_id,
            )
        )
        if not count:
            continue
        video = corrections_controller.video_for(window, source_id)
        if not video:
            continue
        video_path = Path(video)
        schema = identity_controller.schema_for(window, source_id)
        items.append(
            ExportItem(
                kind=RETRAINING_SET,
                title=tr("Retraining set — {source}").format(source=source.name),
                detail=tr(
                    "The {n} corrected frame(s) as labeled data, with their images, "
                    "ready to merge into a training set."
                ).format(n=len(_corrected_indices(window, source_id))),
                target=video_path.parent / f"{video_path.stem}_{source.stem}_training_export",
                source_id=source_id,
                video=video,
                selected=False,
                multi_animal=bool(schema and schema.multi_animal),
            )
        )
    return items


def _corrected_indices(window: MainWindow, source_id: str) -> set[int]:
    return {index for index, _point, _x, _y, _shown in window.point_edits.for_source(source_id)}


def _annotation_target(window: MainWindow) -> Path:
    """Default the annotation CSV beside the session, or beside the first camera."""
    session = window.session_runtime.path
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
            tr(
                "There is nothing to export yet — flag a frame, correct a point, "
                "or accept an identity swap first."
            )
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
        from avialsync.ui.controllers.artifact_write_controller import show_exported

        # One notification lists the results; its action opens the first
        # destination's folder when the user chose several locations.
        show_exported(
            window,
            tr("Exported: {summary}").format(summary="; ".join(str(line) for line in results)),
            chosen[0].target,
        )

    def on_error(message: str) -> None:
        window.notifications.show_error(tr("The export did not finish"), details=message)

    # Wired inside `configure`: `_run_job` returns an already-running thread, so
    # a fast export can finish before a connection made afterwards exists and
    # the user is never told (HANDOUT.md trap 31).
    # `on_finished`/`on_error` are closures, not slots on a QObject, so they
    # would be called directly in the worker thread and raise the notification
    # from there (D-051). `on_ui_thread` gives them a receiver on the window.
    def _wire(thread: QThread) -> None:
        worker.finished.connect(on_ui_thread(on_finished, window))
        worker.error.connect(on_ui_thread(on_error, window))
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)

    window._run_job(worker, label="Exporting changes", configure=_wire)


def _job_for(window: MainWindow, item: ExportItem) -> object | None:
    """Turn a chosen artifact into a job carrying only plain data.

    Everything the worker needs is resolved here, on the UI thread, so no
    reader, widget, or store is touched from the worker (rule 3).
    """
    from avialsync.engine.changes_export_worker import (
        CorrectedPoseJob,
    )

    if item.kind == ANNOTATIONS:
        return _annotation_job(window, item)

    if item.kind == CORRECTED_POSE:
        program = identity_controller.program_for(window, item.source_id)
        if not program:
            return None
        corrections: dict[int, dict[str, tuple[float, float]]] = {}
        for (point, index), value in program.corrections.items():
            frame = corrections_controller.frame_for(window, item.source_id, index)
            corrections.setdefault(frame, {})[point] = value
        routes = tuple(
            (corrections_controller.frame_for(window, item.source_id, index), mapping)
            for index, mapping in zip(program.boundaries, program.maps, strict=True)
        )
        return CorrectedPoseJob(
            source=Path(item.source_id),
            target=item.target,
            corrections=corrections,
            routes=routes,
            swaps=window.identity_swaps.count_for(item.source_id),
        )

    if item.kind == RETRAINING_SET:
        return _retraining_job_for(window, item)
    return None


def _retraining_job_for(window: MainWindow, item: ExportItem) -> object | None:
    """Capture one camera's labels, schema, and display window for the worker."""
    from avialsync.engine.changes_export_worker import RetrainingJob

    bodyparts, frames = corrections_controller.labeled_frames(window, item.source_id)
    if not frames:
        return None
    schema = identity_controller.schema_for(window, item.source_id)
    point_labels = (
        {point.name: (point.individual, point.bodypart) for point in schema.points}
        if schema is not None and schema.multi_animal
        else None
    )
    levels = next(
        (
            pane.display_levels()
            for path, pane in zip(
                window.video_grid.pane_paths(), window.video_grid.panes, strict=False
            )
            if path == item.video
        ),
        None,
    )
    return RetrainingJob(
        target=item.target,
        # The source, never its proxy: a proxy is downscaled and lossy, and the
        # labels are in the source's pixel coordinates.
        video=Path(item.video),
        video_stem=Path(item.video).stem,
        scorer=item.scorer,
        bodyparts=bodyparts,
        frames=frames,
        profile=item.profile,
        point_labels=point_labels,
        **({"display_levels": levels} if levels is not None else {}),
    )


def _annotation_job(window: MainWindow, item: ExportItem) -> object | None:
    """Capture annotation rows and source identity before starting the worker."""
    from avialsync.engine.changes_export_worker import AnnotationJob
    from avialsync.ui.controllers.artifact_write_controller import loaded_sources

    rows = marker_rows(window.annotation_store.markers)
    if not rows:
        return None
    return AnnotationJob(
        target=item.target,
        rows=rows,
        sources=loaded_sources(window),
        session=window.session_runtime.path,
    )
