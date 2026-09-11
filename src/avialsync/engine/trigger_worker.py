"""Read declared trigger trains off the UI thread.

A DAQ export is a few hundred thousand rows of sampled logic and thresholding
it is not free, so it goes through a worker like every other file read
(architecture rule 3). Every train in one file is read in one job: a user who
declared four is waiting for the file, not for four passes over it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.errors import SyncEvidenceError
from avialsync.core.source import TriggerSource
from avialsync.core.triggers import TriggerKind

__all__ = ["TriggerReadWorker", "TriggerTrainResult"]


@dataclass(frozen=True)
class TriggerTrainResult:
    """One train, read and ready to be offered as alignment evidence."""

    train_id: str
    kind: TriggerKind
    times: np.ndarray
    durations: np.ndarray | None = None
    #: The source this train is evidence about, when the file named one.
    target: str = ""
    #: Where the train skips a beat, from `triggers.locate_drops`.
    drops: tuple[int, ...] = field(default_factory=tuple)

    @property
    def count(self) -> int:
        return int(len(self.times))


class TriggerReadWorker(QObject):
    """Open a trigger file and read every train its configuration declares."""

    finished = Signal(object)  # list[TriggerTrainResult]
    error = Signal(str)

    def __init__(self, source: TriggerSource, path: Path, config: dict[str, Any]) -> None:
        super().__init__()
        self._source = source
        self._path = path
        self._config = config

    @Slot()
    def run(self) -> None:
        """Read every declared train, or report the first that will not read.

        All or nothing on purpose. A partial set would leave the user to notice
        which of their trains was missing, from a dialog that had just told
        them the import succeeded.
        """
        from avialsync.core.triggers import locate_drops

        try:
            self._source.open(self._path, self._config)
            results: list[TriggerTrainResult] = []
            for train_id in self._source.trains():
                times, durations = self._source.read_train(train_id)
                if len(times) < 2:
                    raise SyncEvidenceError(
                        f"{train_id!r} yielded {len(times)} events. A train needs at "
                        "least two to place anything -- check the threshold, or whether "
                        "this column is a logical line at all."
                    )
                results.append(
                    TriggerTrainResult(
                        train_id=train_id,
                        kind=TriggerKind(self._source.kind_of(train_id)),
                        times=times,
                        durations=durations,
                        target=self._source.target_hint(train_id),
                        drops=locate_drops(times),
                    )
                )
        except Exception as error:  # noqa: BLE001 - a provider is third-party code
            self.error.emit(str(error))
            return
        self.finished.emit(results)
