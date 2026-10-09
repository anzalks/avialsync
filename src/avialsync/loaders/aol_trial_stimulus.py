"""The stimulus TTL a microscope trial commanded, rebuilt from its saved settings (D-211).

The controller's stimulus trigger generator is configured per trial -- enabled
for acquisition (``EnableInFuncProtocol``), a ``Delay`` from the trial's start,
a ``PulseWidth``, and ``N_Stims`` pulses every ``Period`` -- and saved inside the
controller's MATLAB object in ``params.mat``. No edge is recorded, so this is
the *commanded* schedule: exact if the hardware fires it on time, and labelled
as such wherever it is shown.

The settings live in two places. The controller object's own copy is a group
directly under ``#refs#``; a struct inside the DAQ/FPGA settings carries
another, which on every trial of 2026-09-03 experiment_2 stayed at its inert
defaults (disabled, 1 ms) while the object's copy said "4 s, 1 s" exactly when
``Log.txt`` did. The object's copy is the one read; a trial whose object holds
two enabled, disagreeing settings is reported and given none.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np

logger = logging.getLogger(__name__)

_FIELDS = ("EnableInFuncProtocol", "Delay", "PulseWidth", "N_Stims", "Period")
#: The TTL trace is sampled at this rate between its edges, which are exact.
SAMPLE_RATE_HZ = 1000.0


@dataclass(frozen=True)
class StimulusSchedule:
    """When a trial's stimulus TTL goes high and for how long, from its start."""

    delay: float
    width: float
    count: int = 1
    period: float = 0.0

    def pulses(self) -> list[tuple[float, float]]:
        """``(onset, offset)`` of every pulse, seconds from the trial's start.

        ``N_Stims`` of 0 or 1 is one pulse (every enabled trial on record says
        0 and its note says one stimulus); a train needs a positive period, or
        every pulse would land on the first.
        """
        count = self.count if self.period > 0 else 1
        return [
            (self.delay + k * self.period, self.delay + k * self.period + self.width)
            for k in range(max(1, count))
        ]


def _scalar(group: h5py.Group, name: str) -> float:
    values = np.asarray(group[name][()]).ravel()
    return float(values[0]) if values.size else 0.0


def read_stimulus(folder: Path) -> StimulusSchedule | None:
    """The stimulus a trial commanded during acquisition, or ``None`` when it had none."""
    try:
        with h5py.File(folder / "params.mat", "r") as handle:
            refs = handle.get("#refs#")
            if not isinstance(refs, h5py.Group):
                return None
            schedules = set()
            for name in refs:
                group = refs[name]
                if not isinstance(group, h5py.Group) or not set(_FIELDS) <= set(group):
                    continue
                if _scalar(group, "EnableInFuncProtocol") <= 0:
                    continue
                schedules.add(
                    StimulusSchedule(
                        delay=_scalar(group, "Delay"),
                        width=_scalar(group, "PulseWidth"),
                        count=int(_scalar(group, "N_Stims")),
                        period=_scalar(group, "Period"),
                    )
                )
    except (OSError, KeyError, ValueError):
        return None
    if len(schedules) > 1:
        logger.warning(
            "%s commands %d different stimuli; none is shown.", folder.name, len(schedules)
        )
        return None
    schedule = next(iter(schedules), None)
    if schedule is None or schedule.width <= 0:
        return None
    return schedule


def trial_length(folder: Path) -> float | None:
    """A trial's recorded length (``timings/summary``), read without its pixels."""
    from avialsync.loaders.aol_microscope_trial import _cell_value

    try:
        with h5py.File(folder / "params.mat", "r") as handle:
            values = _cell_value(handle, "timings/summary")
    except (OSError, KeyError, ValueError):
        return None
    return float(values[0]) if values is not None and np.isfinite(values[0]) else None


def ttl_trace(schedule: StimulusSchedule | None, length: float) -> tuple[np.ndarray, np.ndarray]:
    """``(seconds from the trial's start, 0/1)`` across ``[0, length)``.

    Sampled at :data:`SAMPLE_RATE_HZ`, with every edge added as its own sample
    so onsets and offsets sit exactly where the schedule puts them. A trial
    without a stimulus is a flat zero: the row says "no stimulus", not "no data".
    """
    times = np.arange(0.0, max(length, 0.0), 1.0 / SAMPLE_RATE_HZ)
    pulses = [] if schedule is None else schedule.pulses()
    edges = [edge for pulse in pulses for edge in pulse if 0.0 <= edge < length]
    times = np.unique(np.concatenate((times, np.asarray(edges, dtype=np.float64))))
    level = np.zeros(len(times), dtype=np.float64)
    for onset, offset in pulses:
        level[(times >= onset) & (times < offset)] = 1.0
    return times, level
