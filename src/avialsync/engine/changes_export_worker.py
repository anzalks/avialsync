"""Writing the user's own work out, off the UI thread.

Every artifact the Export Changes dialog can produce is written here: the
annotation CSV, a corrected copy of a pose file, and a DeepLabCut retraining set
with the frames it labels.  One worker rather than one per format, because they
are selected together and the user wants one answer about whether it worked.

Nothing in this file reaches into the application.  Each job carries the plain
data it needs — rows, coordinates, paths — resolved on the UI thread while the
dialog was open, so no reader, widget, or store is touched from here
(architecture rule 3).
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

from avialsync.core import dlc_export, pose_export
from avialsync.core.dlc_export import LabeledFrame

logger = logging.getLogger(__name__)

__all__ = ["AnnotationJob", "CorrectedPoseJob", "RetrainingJob", "ChangesExportWorker"]


@dataclasses.dataclass
class AnnotationJob:
    """Write the annotation markers as CSV."""

    target: Path
    rows: list[list[Any]]


@dataclasses.dataclass
class CorrectedPoseJob:
    """Copy a pose file with its corrections applied."""

    source: Path
    target: Path
    #: Video frame -> body part -> corrected ``(x, y)``.
    corrections: dict[int, dict[str, tuple[float, float]]]


@dataclasses.dataclass
class RetrainingJob:
    """Write corrected frames as DeepLabCut labeled data, plus their images."""

    target: Path
    video: Path
    video_stem: str
    scorer: str
    bodyparts: list[str]
    frames: list[LabeledFrame]
    #: Whether to decode and save the PNG each label refers to. A labeled-data
    #: folder without its images cannot be trained on, so this is on unless the
    #: video is unavailable.
    write_images: bool = True


class ChangesExportWorker(QObject):
    """Run every selected export in turn and report one result."""

    finished = Signal(list)  # list[str] — one human-readable line per artifact
    error = Signal(str)
    progress = Signal(int, int)

    def __init__(self, jobs: list[Any]) -> None:
        super().__init__()
        self._jobs = list(jobs)
        self._cancelled = False

    def cancel(self) -> None:
        """Ask the worker to stop after the artifact it is on."""
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        results: list[str] = []
        try:
            for position, job in enumerate(self._jobs):
                if self._cancelled:
                    results.append("Export cancelled.")
                    break
                self.progress.emit(position, len(self._jobs))
                results.append(self._run_one(job))
            self.progress.emit(len(self._jobs), len(self._jobs))
        except Exception as error:  # noqa: BLE001 - reported, never swallowed
            logger.warning("Export failed", exc_info=error)
            self.error.emit(str(error))
            return
        self.finished.emit(results)

    def _run_one(self, job: Any) -> str:
        if isinstance(job, AnnotationJob):
            return self._write_annotations(job)
        if isinstance(job, CorrectedPoseJob):
            return self._write_corrected_pose(job)
        if isinstance(job, RetrainingJob):
            return self._write_retraining_set(job)
        raise TypeError(f"Unknown export job: {type(job).__name__}")

    @staticmethod
    def _write_annotations(job: AnnotationJob) -> str:
        from avialsync.ui.annotations import write_marker_rows

        # No mkdir: a missing parent means the user typed a path that is not
        # there, and inventing the folder hides the typo instead of reporting
        # it. The retraining set is the exception, and says why.
        write_marker_rows(job.target, job.rows)
        return f"{len(job.rows)} annotation row(s) → {job.target.name}"

    @staticmethod
    def _write_corrected_pose(job: CorrectedPoseJob) -> str:
        report = pose_export.write_corrected_copy(job.source, job.target, job.corrections)
        line = (
            f"{report.corrected_points} corrected point(s) in {report.rows} row(s) "
            f"→ {job.target.name}"
        )
        if report.unmatched_frames:
            line += f" ({report.unmatched_frames} correction(s) named absent frames)"
        return line

    def _write_retraining_set(self, job: RetrainingJob) -> str:
        report = dlc_export.write_labeled_data(
            job.target, job.video_stem, job.scorer, job.bodyparts, job.frames
        )
        line = f"{report.frames} labelled frame(s) → {job.target.name}"
        if not job.write_images:
            return line + " (no video available, images not written)"
        written, failed = self._write_frame_images(job)
        line += f", {written} image(s)"
        if failed:
            line += f" ({failed} frame(s) could not be decoded)"
        return line

    def _write_frame_images(self, job: RetrainingJob) -> tuple[int, int]:
        """Decode and save the PNG each label refers to.

        The reader is opened once and closed here, on this thread, because that
        is where it was opened — the same ownership rule the panes follow.
        """
        from avialsync.engine.pyav_reader import PyAVReader, to_rgb_array

        directory = job.target.parent
        directory.mkdir(parents=True, exist_ok=True)
        written = 0
        failed = 0
        reader = PyAVReader(job.video)
        try:
            for item in sorted(job.frames, key=lambda frame: frame.frame):
                if self._cancelled:
                    break
                try:
                    rgb = np.ascontiguousarray(to_rgb_array(reader.frame_at_index(item.frame)))
                except Exception as error:  # noqa: BLE001 - one frame, not the export
                    logger.warning(
                        "Could not decode frame %d of %s", item.frame, job.video, exc_info=error
                    )
                    failed += 1
                    continue
                if _save_png(rgb, directory / dlc_export.image_name(item.frame)):
                    written += 1
                else:
                    failed += 1
        finally:
            reader.close()
        return written, failed


def _save_png(rgb: np.ndarray, path: Path) -> bool:
    """Save an RGB or greyscale array as a PNG.

    ``QImage`` borrows the buffer rather than copying it, so *rgb* is held for
    the whole call: dropping it first would encode freed memory.
    """
    if rgb.ndim == 2:
        height, width = rgb.shape
        image = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_Grayscale8)
    else:
        height, width, _ = rgb.shape
        image = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888)
    return bool(image.save(str(path), b"PNG"))
