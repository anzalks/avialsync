"""Materialising an edited tracker, and scanning one for flips, off the UI thread.

Both jobs here read whole channels: a rebuild writes a pyramid per edited
channel, and a scan walks two trajectories end to end.  Neither belongs on the
UI thread (architecture rule 3), and both are registered like every other job
so they get a name in the Tasks panel and an orderly abandonment at shutdown
(rule 11).

Each worker opens its **own** readers from the directories it is handed rather
than borrowing the window's.  A reader owns mmap views, and handing one across
a thread boundary makes the lifetime of those views a question about two
threads instead of one.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core import edit_cache, identity_detect
from avialsync.core.edit_program import EditProgram
from avialsync.core.identity_detect import Candidate, Trajectory
from avialsync.core.pose import PoseSchema
from avialsync.core.pyramid import PyramidReader

logger = logging.getLogger(__name__)

__all__ = ["MaterialiseWorker", "DetectionJob", "DetectionWorker"]


class MaterialiseWorker(QObject):
    """Write the edited generation one pose source's edits name."""

    #: ``(source_id, EditedCache)`` -- what to point the readers at.
    finished = Signal(str, object)
    error = Signal(str)

    def __init__(
        self, source_id: str, cache_dir: Path, program: EditProgram, schema: PoseSchema
    ) -> None:
        super().__init__()
        self._source_id = source_id
        self._cache_dir = Path(cache_dir)
        self._program = program
        self._schema = schema

    @Slot()
    def run(self) -> None:
        try:
            edited = edit_cache.materialise(self._cache_dir, self._program, self._schema)
        except Exception as error:  # noqa: BLE001 - reported, never swallowed
            logger.warning("Could not build the edited tracker", exc_info=error)
            self.error.emit(str(error))
            return
        self.finished.emit(self._source_id, edited)


@dataclasses.dataclass(frozen=True)
class DetectionJob:
    """One group and one part to scan, and where to read them from."""

    source_id: str
    group: str
    #: The part being scanned, or ``""`` for every part at once -- which is
    #: detected on each lane's centroid, because a whole-animal flip moves all
    #: of them and one body part the model lost must not decide it.
    part: str
    #: ``lane -> [(x channel, y channel), ...]``.  More than one pair only for
    #: the centroid case.
    lanes: dict[str, list[tuple[str, str]]]
    #: ``channel -> the directory to read it from``, so a scan sees the edits
    #: already accepted and does not propose them a second time.
    directories: dict[str, Path]


class DetectionWorker(QObject):
    """Propose the frames at which one group may have exchanged labels."""

    #: ``(job, candidates)`` -- the job comes back so a stale answer to a
    #: selector the user has since changed can be recognised and dropped.
    finished = Signal(object, object)
    error = Signal(str)

    def __init__(self, job: DetectionJob) -> None:
        super().__init__()
        self._job = job

    @Slot()
    def run(self) -> None:
        try:
            lanes = {lane: self._trajectory(pairs) for lane, pairs in self._job.lanes.items()}
            candidates: tuple[Candidate, ...] = identity_detect.detect(
                {lane: track for lane, track in lanes.items() if len(track.x)}
            )
        except Exception as error:  # noqa: BLE001 - reported, never swallowed
            logger.warning("Could not scan for identity swaps", exc_info=error)
            self.error.emit(str(error))
            return
        self.finished.emit(self._job, candidates)

    def _trajectory(self, pairs: list[tuple[str, str]]) -> Trajectory:
        tracks = [
            Trajectory(self._values(x_channel), self._values(y_channel))
            for x_channel, y_channel in pairs
        ]
        tracks = [track for track in tracks if len(track.x) and len(track.y)]
        if not tracks:
            return Trajectory(_empty(), _empty())
        if len(tracks) == 1:
            return tracks[0]
        return identity_detect.centroid(_aligned(tracks))

    def _values(self, channel: str) -> np.ndarray:
        directory = self._job.directories.get(channel)
        if directory is None:
            return _empty()
        return PyramidReader(directory, channel).mapped_columns()[1]


def _empty() -> np.ndarray:
    return np.zeros(0, dtype=float)


def _aligned(tracks: list[Trajectory]) -> list[Trajectory]:
    """Clip every part to the shortest, so a centroid can be stacked.

    A pose file writes one row per frame for every point, so they are equal
    already; clipping is what keeps a hand-assembled or partially imported
    source from raising instead of being scanned.
    """
    shortest = min(min(len(track.x), len(track.y)) for track in tracks)
    return [Trajectory(track.x[:shortest], track.y[:shortest]) for track in tracks]
