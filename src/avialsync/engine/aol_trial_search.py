"""Registered worker for finding one AOL microscope trial beside camera data."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.loaders.aol_microscope_trial import is_microscope_trial, read_trial
from avialsync.loaders.aol_trial_matching import (
    day_directory,
    derive_utc_offset,
    match_trial,
)


class AOLTrialSearchWorker(QObject):
    """Read trial metadata for the camera's stamped day and report one match."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, saved_root: Path, camera_local_epoch: float, tolerance_s: float) -> None:
        super().__init__()
        self.saved_root = saved_root
        self.camera_local_epoch = camera_local_epoch
        self.tolerance_s = tolerance_s

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.search())
        except (OSError, ValueError, TypeError) as error:
            self.error.emit(str(error))

    def search(self) -> dict[str, Any]:
        day = day_directory(self.saved_root, self.camera_local_epoch)
        if not day.is_dir():
            return {"status": "missing_day", "day": str(day)}
        trials = []
        for experiment in sorted(day.glob("experiment_*")):
            if not experiment.is_dir():
                continue
            for folder in sorted(experiment.iterdir()):
                if is_microscope_trial(folder):
                    trials.append(read_trial(folder, verify=False))
        if not trials:
            return {"status": "no_trials", "day": str(day)}
        date = dt.datetime.fromtimestamp(self.camera_local_epoch, tz=dt.UTC).date()
        zone_offset = derive_utc_offset(trials, date)
        if zone_offset is None:
            return {"status": "inconsistent_zone", "day": str(day), "count": len(trials)}
        match = match_trial(trials, self.camera_local_epoch, zone_offset, self.tolerance_s)
        if match is None:
            return {"status": "ambiguous_or_distant", "day": str(day), "count": len(trials)}
        return {
            "status": "matched",
            "folder": str(match.trial.folder),
            "start_epoch": match.trial.start_epoch,
            "duration": match.trial.duration,
            "camera_local_epoch": match.camera_local_epoch,
            "utc_offset_s": match.controller_utc_offset_s,
            "residual_s": match.residual_s,
            "day": str(day),
        }
