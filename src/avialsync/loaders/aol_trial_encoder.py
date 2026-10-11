"""The signals a microscope trial saved: wheel speed, and the stimulus TTL it commanded.

The class keeps its first name (``AOLTrialEncoderSource``) because sessions
record a source's loader by class name; it now reads two channels from the
same ``params.mat``, which is also why they are one source: a source is named
by one file. The stimulus TTL is rebuilt from the controller's settings
(:mod:`~avialsync.loaders.aol_trial_stimulus`).

Rigs whose controller reads the encoder itself keep no ``encoder_log.txt``: each
trial's ``params.mat`` holds ``behaviour/encoder``, one-element MATLAB cells like
the timing fields. Only the speed is shown. It is rpm -- six times its integral
follows the logged angle (6.03 and 5.96 degrees per rpm-second on two trials of
2026-09-03 experiment_2) -- the same channel and unit the encoder log gives.

``wheel_speed_time`` counts seconds from the trial's start (it spans the trial's
recorded length), so a trial's samples sit on its ``STARTTIME`` like its imaging,
and an experiment's trials sit at the starts the ribbon scan uses (D-217).
Samples past a trial's length are dropped, so trials never overlap, and the
stimulus TTL stops at each trial's end: between trials nothing was recorded,
and the plot shows a gap there rather than a level. Where an ``encoder_log.txt`` is open already
(trials dropped onto an AOL camera session that has one), that log's speed is
the one shown and this one is not offered.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from avialsync.core.errors import MissingColumnError, SourceOpenError
from avialsync.core.source import ChannelInfo, TimeSeriesSource
from avialsync.core.trials import into_slot
from avialsync.loaders.aol_microscope_trial import _cell_value
from avialsync.loaders.aol_trial_stimulus import (
    StimulusSchedule,
    read_stimulus,
    trial_length,
    ttl_trace,
)

logger = logging.getLogger(__name__)

#: The same channel name and unit as the encoder log's velocity.
SPEED_CHANNEL = "encoder_velocity"
#: The commanded stimulus TTL, 0 or 1, rebuilt from the trial's settings.
STIMULUS_CHANNEL = "stimulus_ttl"
#: The encoder log an AOL camera session plots instead, when it has one.
ENCODER_LOG = "encoder_log.txt"
_SPEED = "behaviour/encoder/wheel_speed"
_TIME = "behaviour/encoder/wheel_speed_time"


def read_wheel_speed(folder: Path) -> tuple[np.ndarray, np.ndarray] | None:
    """``(seconds from the trial's start, rpm)`` from a trial's ``params.mat``, or nothing."""
    try:
        with h5py.File(folder / "params.mat", "r") as handle:
            speed = _cell_value(handle, _SPEED)
            times = _cell_value(handle, _TIME)
    except (OSError, KeyError, ValueError):
        return None
    if speed is None or times is None:
        return None
    count = min(len(speed), len(times))
    times = np.asarray(times[:count], dtype=np.float64)
    speed = np.asarray(speed[:count], dtype=np.float64)
    keep = np.isfinite(times)
    # Strictly increasing: a repeated or backward stamp is not a second sample.
    previous = np.maximum.accumulate(np.concatenate(([-np.inf], np.where(keep, times, -np.inf))))
    keep &= times > previous[:-1]
    if not keep.any():
        return None
    return times[keep], speed[keep]


def has_wheel_speed(folder: Path) -> bool:
    """Whether a trial's ``params.mat`` declares the wheel speed (names only, no samples)."""
    try:
        with h5py.File(folder / "params.mat", "r") as handle:
            return _SPEED in handle and _TIME in handle
    except (OSError, ValueError):
        return False


def _trial_folders(config: dict[str, Any]) -> list[Path]:
    folders = config.get("trial_folders") or [config.get("trial_folder")]
    return [Path(str(folder)) for folder in folders if folder]


class AOLTrialEncoderSource(TimeSeriesSource):
    """Wheel speed and stimulus TTL across one trial, or each of an experiment's trials."""

    @classmethod
    def display_name(cls) -> str:
        return "Trial Signals (MATLAB)"

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Never claimed by a drop: a trial's session declares it (it is not a file of its own)."""
        return 0.0

    def __init__(self) -> None:
        self._folders: list[Path] = []
        self._starts: list[float] = []
        self._lengths: list[float | None] = []
        self._has_speed = False
        self._stimuli: list[StimulusSchedule | None] = []

    def open(self, path: Path, config: dict[str, Any]) -> None:
        folders = _trial_folders(config)
        if not folders:
            raise SourceOpenError(f"No microscope trial is named for the wheel speed in {path}.")
        starts = [float(start) for start in config.get("trial_starts") or [0.0] * len(folders)]
        if len(starts) != len(folders):
            raise SourceOpenError("The wheel speed's trials and their starts disagree in number.")
        self._folders, self._starts = folders, starts
        self._lengths = _lengths(config, starts, folders)
        wanted = bool(config.get("wheel_speed", True))
        self._has_speed = wanted and any(has_wheel_speed(folder) for folder in folders)
        self._stimuli = [read_stimulus(folder) for folder in folders]

    def channels(self) -> list[ChannelInfo]:
        # rate_hz stays None: the controller logs about 1 kHz, irregularly, and
        # the TTL's exact edges sit between its regular samples.
        found = []
        if self._has_speed:
            found.append(ChannelInfo(name=SPEED_CHANNEL, unit="rpm", dtype="Float64", rate_hz=None))
        if any(self._stimuli):
            found.append(ChannelInfo(name=STIMULUS_CHANNEL, unit="", dtype="Float64", rate_hz=None))
        return found

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """One chunk per trial, each at its start on the session timeline."""
        if ch == STIMULUS_CHANNEL:
            yield from self._stimulus_chunks()
            return
        if ch != SPEED_CHANNEL:
            raise MissingColumnError(ch, [SPEED_CHANNEL, STIMULUS_CHANNEL])
        for folder, start, length in zip(self._folders, self._starts, self._lengths, strict=True):
            wheel = read_wheel_speed(folder)
            if wheel is None:
                logger.warning("%s logged no wheel speed; its trial has none.", folder.name)
                continue
            placed = into_slot(*wheel, start, np.inf if length is None else length)
            if placed is not None:
                yield placed

    def _stimulus_chunks(self) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """The commanded TTL across each trial; zero for a trial without one."""
        for folder, start, length, schedule in zip(
            self._folders, self._starts, self._lengths, self._stimuli, strict=True
        ):
            # The last trial of a session saved before D-217 runs its recorded length.
            length = trial_length(folder) if length is None else length
            if length is None or length <= 0:
                continue
            times, level = ttl_trace(schedule, length)
            placed = start + times
            # Strictly increasing on the session timeline, whatever float rounding
            # the shift by *start* does: pulse extraction rejects a repeated time.
            keep = np.concatenate(([True], np.diff(placed) > 0))
            yield placed[keep], level[keep]


def _lengths(
    config: dict[str, Any], starts: Sequence[float], folders: Sequence[Path]
) -> list[float | None]:
    """Each trial's length on the timeline: as the session stored it, else up to the next.

    A session saved before D-217 stored back-to-back starts and no lengths;
    there each trial ran up to the next one's start, and the last one's end
    is left open.
    """
    stored = config.get("trial_lengths")
    if stored and len(stored) == len(folders):
        return [float(length) for length in stored]
    return [*(b - a for a, b in zip(starts, starts[1:], strict=False)), None]
