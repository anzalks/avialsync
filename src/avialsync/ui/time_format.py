"""Time display mode enum and single formatting authority (D-020, D-173).

All time-displaying widgets must call format_time() — never format inline.
Numbers follow one policy (D-173): a full stop as the decimal separator and no
digit grouping, everywhere the application shows or accepts a number.
"""

from __future__ import annotations

import datetime
from enum import Enum, auto

from PySide6.QtCore import QLocale


def number_locale() -> QLocale:
    """The locale every number is shown in: C digits, full stop, no grouping (D-173)."""
    locale = QLocale.c()
    locale.setNumberOptions(QLocale.NumberOption.OmitGroupSeparator)
    return locale


def apply_number_locale() -> None:
    """Make :func:`number_locale` Qt's default, before any widget is built.

    Spin boxes and validators read the default locale when they are created;
    pyqtgraph's tick labels and the readouts already use Python formatting,
    which is the same full stop. One default reaches every widget, so no
    control can be left showing the operating system's separator.
    """
    QLocale.setDefault(number_locale())


def format_number(value: float, decimals: int) -> str:
    """Format *value* with *decimals* places under the number policy."""
    return number_locale().toString(float(value), "f", decimals)


class TimeDisplayMode(Enum):
    RELATIVE = auto()  # HH:MM:SS.fff from master-clock zero
    UTC = auto()  # absolute UTC wall clock
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
    """Format signed elapsed time without wrapping negative values by a day."""
    total_milliseconds = round(abs(t) * 1000)
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    sign = "-" if t < 0 else ""
    return f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
