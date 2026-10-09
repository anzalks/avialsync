"""Clock evidence and unambiguous camera-to-trial matching for AOL recordings."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from avialsync.loaders.aol_microscope_trial import MicroscopeTrial


@dataclass(frozen=True)
class TrialMatch:
    """A trial selected by camera wall-clock proximity, with its evidence."""

    trial: MicroscopeTrial
    camera_local_epoch: float
    controller_utc_offset_s: int
    residual_s: float


def derive_utc_offset(trials: list[MicroscopeTrial], day: dt.date) -> int | None:
    """Infer a shared 15-minute-zone offset from folder times and UTC STARTTIME."""
    offsets: set[int] = set()
    for trial in trials:
        if trial.start_epoch <= 0:
            continue
        try:
            hour, minute, second = (int(part) for part in trial.folder.name.split("-"))
            local_clock = dt.datetime.combine(day, dt.time(hour, minute, second), tzinfo=dt.UTC)
        except (ValueError, OverflowError):
            continue
        delta = local_clock.timestamp() - trial.start_epoch
        offsets.add(round(delta / 900.0) * 900)
    return next(iter(offsets)) if len(offsets) == 1 else None


def match_trial(
    trials: list[MicroscopeTrial],
    camera_local_epoch: float,
    utc_offset_s: int,
    tolerance_s: float = 10.0,
) -> TrialMatch | None:
    """Match containment first, else one nearest STARTTIME inside the tolerance."""
    camera_utc = camera_local_epoch - utc_offset_s
    containing = [
        trial
        for trial in trials
        if trial.start_epoch <= camera_utc <= trial.start_epoch + trial.duration
    ]
    if len(containing) == 1:
        trial = containing[0]
        return TrialMatch(trial, camera_local_epoch, utc_offset_s, camera_utc - trial.start_epoch)
    if len(containing) > 1:
        return None
    candidates = sorted(
        ((abs(camera_utc - trial.start_epoch), trial) for trial in trials),
        key=lambda item: item[0],
    )
    if not candidates or candidates[0][0] > tolerance_s:
        return None
    if len(candidates) > 1 and candidates[1][0] <= tolerance_s:
        return None
    trial = candidates[0][1]
    return TrialMatch(trial, camera_local_epoch, utc_offset_s, camera_utc - trial.start_epoch)


def day_directory(saved_root: Path, camera_local_epoch: float) -> Path:
    """The one dated acquisition folder represented by a camera stamp."""
    day = dt.datetime.fromtimestamp(camera_local_epoch, tz=dt.UTC).date()
    return saved_root / day.isoformat()
