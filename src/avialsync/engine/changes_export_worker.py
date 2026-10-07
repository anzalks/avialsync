"""Writing the user's own work out, off the UI thread.

Every artifact the Export Changes dialog can produce is written here: the
annotation CSV, an edited copy of a pose file, and a DeepLabCut or Lightning
Pose retraining set with the frames it labels.  One worker rather than one per format, because they
are selected together and the user wants one answer about whether it worked.

Nothing in this file reaches into the application.  Each job carries the plain
data it needs — rows, coordinates, paths — resolved on the UI thread while the
dialog was open, so no reader, widget, or store is touched from here
(architecture rule 3).
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

from avialsync.core import dlc_export, pose_export
from avialsync.core.artifact_io import publish_dir
from avialsync.core.dlc_export import LabeledFrame
from avialsync.core.errors import ExportError
from avialsync.engine.display_pipeline import DisplayLevels, to_display_array

logger = logging.getLogger(__name__)

__all__ = ["AnnotationJob", "CorrectedPoseJob", "RetrainingJob", "ChangesExportWorker"]


@dataclasses.dataclass
class AnnotationJob:
    """Write the annotation markers as CSV."""

    target: Path
    rows: list[list[Any]]
    sources: tuple[Path, ...] = ()
    session: Path | None = None


@dataclasses.dataclass
class CorrectedPoseJob:
    """Copy a pose file with its corrections and accepted identity swaps."""

    source: Path
    target: Path
    #: Video frame -> body part -> corrected ``(x, y)``.
    corrections: dict[int, dict[str, tuple[float, float]]]
    #: Ascending frame boundaries and the display-to-source routing in force.
    routes: tuple[tuple[int, Mapping[str, str]], ...] = ()
    swaps: int = 0


@dataclasses.dataclass
class RetrainingJob:
    """Write corrected frames as DeepLabCut or Lightning Pose labels, plus their images."""

    target: Path  # A new bundle folder whose contents go into the project root.
    video: Path
    video_stem: str
    scorer: str
    bodyparts: list[str]
    frames: list[LabeledFrame]
    profile: str = "dlc"
    point_labels: dict[str, tuple[str, str]] | None = None
    display_levels: DisplayLevels = dataclasses.field(default_factory=DisplayLevels)


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
        write_marker_rows(job.target, job.rows, sources=job.sources, session=job.session)
        return f"{len(job.rows)} annotation row(s) → {job.target.name}"

    @staticmethod
    def _write_corrected_pose(job: CorrectedPoseJob) -> str:
        report = pose_export.write_corrected_copy(
            job.source, job.target, job.corrections, routes=job.routes
        )
        line = (
            f"{report.corrected_points} corrected point(s), {job.swaps} identity swap(s) "
            f"in {report.rows} row(s) "
            f"→ {job.target.name}"
        )
        if report.unmatched_frames:
            line += f" ({report.unmatched_frames} correction(s) named absent frames)"
        return line

    def _write_retraining_set(self, job: RetrainingJob) -> str:
        if not job.video.is_file():
            raise ExportError(
                f"The video for {job.video_stem} is unavailable; no training set was written."
            )
        if job.target.exists():
            raise ExportError(f"{job.target.name} already exists; choose a new export folder.")
        if job.profile == "lightning_pose" and job.point_labels:
            raise ExportError("Lightning Pose export needs a single-animal pose source.")
        if not job.frames:
            raise ExportError("There are no corrected frames to export.")
        result: list[dlc_export.LabeledDataReport] = []
        kind = "lightning-pose-retraining" if job.profile == "lightning_pose" else "dlc-retraining"

        def write(staging: Path) -> None:
            image_dir = staging / "labeled-data" / job.video_stem
            image_dir.mkdir(parents=True)
            self._write_frame_images(job, image_dir)
            csv_path = dlc_export.training_csv_path(
                staging, job.video_stem, job.scorer, job.profile
            )
            result.append(
                dlc_export.write_labeled_data(
                    csv_path,
                    job.video_stem,
                    job.scorer,
                    job.bodyparts,
                    job.frames,
                    sources=(job.video,),
                    point_labels=job.point_labels,
                    kind=kind,
                )
            )

        publish_dir(job.target, write, kind=kind, sources=(job.video,))
        return (
            f"{result[0].frames} labelled frame(s), {result[0].frames} image(s) → {job.target.name}"
        )

    def _write_frame_images(self, job: RetrainingJob, directory: Path) -> None:
        """Decode and save the PNG each label refers to.

        The reader is opened once and closed here, on this thread, because that
        is where it was opened — the same ownership rule the panes follow.
        """
        from avialsync.engine.pyav_reader import PyAVReader

        reader = PyAVReader(job.video)
        try:
            seen: set[int] = set()
            for item in sorted(job.frames, key=lambda frame: frame.frame):
                if self._cancelled:
                    raise ExportError("Training set export was cancelled.")
                if item.frame in seen or not 0 <= item.frame < reader.frame_count:
                    raise ExportError(
                        f"Frame {item.frame} is duplicated or absent from {job.video.name}."
                    )
                seen.add(item.frame)
                try:
                    pixels, _grey = to_display_array(
                        reader.frame_at_index(item.frame), job.display_levels
                    )
                except Exception as error:
                    raise ExportError(
                        f"Could not decode frame {item.frame} of {job.video.name}."
                    ) from error
                height, width = pixels.shape[:2]
                for part, (x, y) in item.positions.items():
                    if (
                        not np.isfinite(x)
                        or not np.isfinite(y)
                        or not (0 <= x < width and 0 <= y < height)
                    ):
                        raise ExportError(
                            f"{part} on frame {item.frame} lies outside its {width}×{height} image."
                        )
                if not _save_png(pixels, directory / dlc_export.image_name(item.frame)):
                    raise ExportError(f"Could not save image for frame {item.frame}.")
        finally:
            reader.close()


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
    from avialsync.core.artifact_io import publish
    from avialsync.core.artifact_provenance import record

    metadata = record("dlc-frame")
    from avialsync.engine.snapshot import PNG_CREATION_TIME_KEY, PNG_SOFTWARE_KEY

    image.setText(PNG_SOFTWARE_KEY, str(metadata["software"]))
    image.setText(PNG_CREATION_TIME_KEY, str(metadata["written"]))

    def write(temporary: Path) -> None:
        # PySide6's QImage stub says bytes, but this runtime accepts str (see snapshot.py).
        if not image.save(str(temporary), "PNG"):  # type: ignore[call-overload]
            raise OSError(f"Could not save {path.name}")

    try:
        publish(path, write, kind="dlc-frame")
    except OSError:
        return False
    return True
