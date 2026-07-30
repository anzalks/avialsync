"""Background workers for session persistence and annotation export.

Architecture rule 3: the UI thread never blocks.  Session save/load, autosave, and
annotation export all write or parse files whose size grows with the recording —
a million-frame exact mapping or a ten-thousand-marker annotation set is not a
"fast enough" operation, and on a slow or network drive none of them are.

Every worker here takes an immutable snapshot of what it needs at construction
time, so the UI thread can keep mutating its own state while the job runs.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from avialview.core.session import SessionState


@dataclass(frozen=True)
class AnnotationRow:
    """One flattened ``(marker, video)`` export row.

    Snapshotted on the UI thread so the worker never touches a live
    ``AnnotationStore`` that the user may still be editing.
    """

    label: str
    comment: str
    t_master: float
    video_path: str
    frame_index: str | int
    media_timestamp: str | float


ANNOTATION_HEADER = (
    "label",
    "comment",
    "t_master",
    "video_path",
    "frame_index",
    "media_timestamp",
)


class SessionSaveWorker(QObject):
    """Serialise a session snapshot to disk off the UI thread."""

    finished = Signal(str)  # path
    error = Signal(str)

    def __init__(self, state: SessionState, path: Path) -> None:
        super().__init__()
        self._state = state
        self._path = path

    @Slot()
    def run(self) -> None:
        try:
            self._state.save(self._path)
        except (OSError, TypeError, ValueError) as error:
            self.error.emit(str(error))
            return
        self.finished.emit(str(self._path))


class SessionLoadWorker(QObject):
    """Parse and validate a ``.avv`` file off the UI thread.

    Only parsing moves here.  Applying the result — creating panes, starting
    imports — stays on the UI thread, where Qt object ownership belongs.
    """

    finished = Signal(str, object)  # path, SessionState
    error = Signal(str)

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    @Slot()
    def run(self) -> None:
        try:
            state = SessionState.load(self._path)
        except (OSError, KeyError, TypeError, ValueError) as error:
            self.error.emit(str(error))
            return
        self.finished.emit(str(self._path), state)


class AnnotationExportWorker(QObject):
    """Write annotation rows to CSV off the UI thread."""

    finished = Signal(str, int)  # path, row count
    error = Signal(str)

    def __init__(self, rows: list[AnnotationRow], path: Path) -> None:
        super().__init__()
        self._rows = rows
        self._path = path

    @Slot()
    def run(self) -> None:
        try:
            with open(self._path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(ANNOTATION_HEADER)
                for row in self._rows:
                    writer.writerow(
                        [
                            row.label,
                            row.comment,
                            row.t_master,
                            row.video_path,
                            row.frame_index,
                            row.media_timestamp,
                        ]
                    )
        except (OSError, ValueError) as error:
            self.error.emit(str(error))
            return
        self.finished.emit(str(self._path), len(self._rows))
