"""Clock drift as time gained per hour of recording (D-184).

Drift is a rate: how far one clock runs ahead of another as time passes. It is
held, stored, fitted and shown in one unit everywhere -- milliseconds gained
per hour (``ms/h``) -- so a camera whose clock gains 54 ms every hour of
recording has ``drift_ms_per_hour == 54.0``, and the number a person types is
the number the mapping uses. Where a source's sample rate is known, the same
drift is also told in frames or samples per hour.

Session files written before schema 12 stored a dimensionless rate in parts per
million under another key; :func:`drift_from_legacy_entry` is the one place
that reads them.
"""

from __future__ import annotations

from collections.abc import Mapping

__all__ = [
    "LEGACY_DRIFT_KEY",
    "MS_PER_HOUR",
    "describe_drift",
    "drift_from_legacy_entry",
    "rate_from_drift",
    "drift_from_rate",
]

#: Milliseconds in an hour: a drift in ms/h divided by this is the seconds a
#: clock gains per second, the factor the time mapping multiplies by.
MS_PER_HOUR = 3_600_000.0

#: The key and scale pre-schema-12 sessions used: a rate times one million.
LEGACY_DRIFT_KEY = "drift_ppm"  # read from older session files; never written
_LEGACY_TO_MS_PER_HOUR = MS_PER_HOUR / 1_000_000.0


def rate_from_drift(drift_ms_per_hour: float) -> float:
    """Seconds gained per second for a clock that gains *drift_ms_per_hour*."""
    return drift_ms_per_hour / MS_PER_HOUR


def drift_from_rate(rate: float) -> float:
    """The drift, in ms/h, of a clock gaining *rate* seconds per second."""
    return rate * MS_PER_HOUR


def drift_from_legacy_entry(entry: Mapping[str, object], key: str = "drift_ms_per_hour") -> float:
    """Read *key*, or convert the drift an older session file stored instead."""
    if key in entry:
        return _number(entry[key])
    if LEGACY_DRIFT_KEY in entry:
        return _number(entry[LEGACY_DRIFT_KEY]) * _LEGACY_TO_MS_PER_HOUR
    return 0.0


def _number(value: object) -> float:
    if isinstance(value, (int, float, str)):
        return float(value)
    raise ValueError(f"A drift must be a number, not {value!r}")


def describe_drift(
    drift_ms_per_hour: float, *, sample_rate_hz: float = 0.0, samples: str = "samples"
) -> str:
    """``+54.0 ms/h``, or ``+54.0 ms/h (≈1.6 frames/h)`` when a rate is given.

    Two decimals below 1 ms/h so a small drift does not read as none; seconds
    per hour past 1000 ms/h, which only an implausible fit reaches.
    """
    gain = float(drift_ms_per_hour)
    if gain == 0.0:
        text = "0 ms/h"
    elif abs(gain) >= 1000.0:
        text = f"{gain / 1000.0:+.1f} s/h"
    elif abs(gain) < 1.0:
        text = f"{gain:+.2f} ms/h"
    else:
        text = f"{gain:+.1f} ms/h"
    if sample_rate_hz > 0.0 and gain != 0.0:
        per_hour = abs(gain) / 1000.0 * sample_rate_hz
        text += f" (≈{per_hour:.2g} {samples}/h)"
    return text
