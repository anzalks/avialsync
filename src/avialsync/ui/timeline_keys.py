"""Keyboard reading of the Data Streams lanes.

Gap, sync, identity and message details used to exist only as hover tooltips,
so the lanes were unusable without a mouse. Up and Down choose a lane; Left
and Right move the playhead to the previous or next thing on it (an event, a
span edge, a marker, a trial); Home and End go to the session's ends. The
lane's own detail at the playhead is what assistive technology reads.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np


def lane_times(payload: object) -> np.ndarray:
    """Sorted instants a keyboard step can land on in one lane."""
    times: Iterable[float]
    if hasattr(payload, "events"):
        times = (time for time, _ in payload.events)
    elif hasattr(payload, "markers"):
        times = (start for start, _end, _ in payload.markers)
    elif hasattr(payload, "segments"):
        times = (start for start, _end, _ in payload.segments)
    elif hasattr(payload, "start") and hasattr(payload, "end"):
        whole = ((payload.start, payload.end),)
        spans = getattr(payload, "spans", ()) or whole
        times = (edge for span in spans for edge in span)
    else:
        return np.empty(0)
    return np.unique(np.fromiter(times, dtype=np.float64))


def step_target(times: np.ndarray, cursor: float, direction: int) -> float | None:
    """The next instant after *cursor* (direction > 0) or the last one before it."""
    if len(times) == 0:
        return None
    # A microsecond of slack, so stepping from an event lands on the next one
    # rather than on itself after the seek rounds the playhead.
    slack = 1e-6
    if direction > 0:
        index = int(np.searchsorted(times, cursor + slack, side="right"))
        return float(times[index]) if index < len(times) else None
    index = int(np.searchsorted(times, cursor - slack, side="left")) - 1
    return float(times[index]) if index >= 0 else None
