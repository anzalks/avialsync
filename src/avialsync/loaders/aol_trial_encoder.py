"""The signals a microscope trial saved: wheel speed, and the stimulus TTL it commanded.

The class keeps its first name (``AOLTrialEncoderSource``) because sessions
record a source's loader by class name; it now reads two channels from the
same ``params.mat``, which is also why they are one source: a source is named
by one file. The stimulus TTL is rebuilt from the controller's settings
(:mod:`~avialsync.loaders.aol_trial_stimulus`, D-211).

Rigs whose controller reads the encoder itself keep no ``encoder_log.txt``: each
trial's ``params.mat`` holds ``behaviour/encoder``, one-element MATLAB cells like
the timing fields. Only the speed is shown. It is rpm -- six times its integral
follows the logged angle (6.03 and 5.96 degrees per rpm-second on two trials of
2026-09-03 experiment_2) -- the same channel and unit the encoder log gives.

``wheel_speed_time`` counts seconds from the trial's start (it spans the trial's
recorded length), so a trial's samples sit on its ``STARTTIME`` like its imaging,
and a joined experiment's trials sit back to back at the joined starts the
ribbon scan uses (D-205). Samples past a trial's slot on the joined timeline are
dropped, so trials never overlap. Where an ``encoder_log.txt`` is open already
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
    """Wheel speed across one trial, or an experiment's trials back to back."""

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
        """One chunk per trial, each at its joined start."""
        if ch == STIMULUS_CHANNEL:
            yield from self._stimulus_chunks()
            return
        if ch != SPEED_CHANNEL:
            raise MissingColumnError(ch, [SPEED_CHANNEL, STIMULUS_CHANNEL])
        ends: Sequence[float] = [*self._starts[1:], np.inf]
        for folder, start, end in zip(self._folders, self._starts, ends, strict=True):
            wheel = read_wheel_speed(folder)
            if wheel is None:
                logger.warning("%s logged no wheel speed; its trial has none.", folder.name)
                continue
            times, speed = wheel
            inside = start + times < end
            if inside.any():
                yield start + times[inside], speed[inside]

    def _stimulus_chunks(self) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """The commanded TTL across each trial's slot; zero for a trial without one."""
        ends: Sequence[float | None] = [*self._starts[1:], None]
        for folder, start, end, schedule in zip(
            self._folders, self._starts, ends, self._stimuli, strict=True
        ):
            # Up to the next trial; the last runs its recorded length.
            length = end - start if end is not None else trial_length(folder)
            if length is None or length <= 0:
                continue
            times, level = ttl_trace(schedule, length)
            yield start + times, level
