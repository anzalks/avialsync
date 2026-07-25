"""Time display mode enum and single formatting authority (D-020).

All time-displaying widgets must call format_time() — never format inline.
"""

from __future__ import annotations

import datetime
from enum import Enum, auto


class TimeDisplayMode(Enum):
    RELATIVE = auto()   # HH:MM:SS.fff from master-clock zero
    UTC = auto()        # absolute UTC wall clock
    LOCAL_TOD = auto()  # local time-of-day


def format_time(t_seconds: float, mode: TimeDisplayMode, t_epoch: float = 0.0) -> str:
    """Format *t_seconds* according to *mode*.

    t_epoch is the Unix epoch of master-clock zero.  When 0.0 (unknown),
    RELATIVE is used regardless of the requested mode.
    """
    if mode == TimeDisplayMode.RELATIVE or t_epoch == 0.0:
        return _fmt_relative(t_seconds)
    abs_t = t_epoch + t_seconds
    dt = datetime.datetime.fromtimestamp(abs_t, tz=datetime.UTC)
    if mode == TimeDisplayMode.UTC:
        ms = dt.microsecond // 1000
        return dt.strftime("%H:%M:%S.") + f"{ms:03d} UTC"
    local_dt = dt.astimezone()
    ms = local_dt.microsecond // 1000
    return local_dt.strftime("%H:%M:%S.") + f"{ms:03d}"


def _fmt_relative(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"
