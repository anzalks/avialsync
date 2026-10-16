"""Pure guesses and checks the text import wizard makes about a time column.

Kept apart from the dialog so each rule is testable on plain strings: a wrong
timebase is the costliest silent import failure, because every alignment and
export downstream inherits it.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Sequence
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Header words that name a clock. Matched as whole tokens, never substrings:
# a bare "t" pattern searched as a substring picked `tail_x` and `Voltage`.
_TIME_TOKENS = (
    "timestamp",
    "timestamps",
    "datetime",
    "time",
    "times",
    "epoch",
    "unix",
    "elapsed",
    "seconds",
    "secs",
    "sec",
    "date",
    "ts",
    "t",
)

# Seconds-since-1970 for any date between 1973 and 5138 lies in [1e8, 1e11);
# the same instants in ms, µs and ns sit three, six and nine decades higher.
# A value under 1e8 (about three years of seconds) is elapsed time, not a
# date: calling 0.001 "Unix epoch" placed recordings in January 1970.
_EPOCH_DECADES = (
    (1e17, "epoch_ns"),
    (1e14, "epoch_us"),
    (1e11, "epoch_ms"),
    (1e8, "epoch_s"),
)

#: The format value for a plain number counted from an arbitrary zero.
ELAPSED_FORMAT = "numeric"

_UNIT_IN_HEADER = re.compile(r"[\(\[]\s*([^\)\]]{1,16}?)\s*[\)\]]\s*$")
_OFFSET_SUFFIX = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")


def header_tokens(header: str) -> list[str]:
    """Split a header into lowercase words at punctuation and camelCase."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", header)
    return [token for token in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if token]


def guess_time_column(headers: Sequence[str]) -> int:
    """Return the index of the most likely timestamp column, else 0.

    The most specific word wins: `timestamp` beats a column that only
    contains `t` as one of its words.
    """
    best_index, best_rank = 0, len(_TIME_TOKENS)
    for index, header in enumerate(headers):
        tokens = header_tokens(header.strip())
        for rank, word in enumerate(_TIME_TOKENS):
            if word in tokens and rank < best_rank:
                best_index, best_rank = index, rank
    return best_index


def guess_numeric_format(value: float) -> str:
    """Name the epoch unit a magnitude implies, or elapsed time below 1e8."""
    magnitude = abs(value)
    for floor, fmt in _EPOCH_DECADES:
        if magnitude >= floor:
            return fmt
    return ELAPSED_FORMAT


def guess_format(sample_values: Sequence[str]) -> str:
    """Guess the timestamp format from sample values ("" when unknown)."""
    values = [value.strip() for value in sample_values if value.strip()]
    if not values:
        return ""
    v = values[0]
    try:
        return guess_numeric_format(float(v))
    except ValueError:
        pass

    patterns = (
        (r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+", "%Y-%m-%dT%H:%M:%S.%f"),
        (r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", "%Y-%m-%dT%H:%M:%S"),
        (r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+", "%Y-%m-%d %H:%M:%S.%f"),
        (r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", "%Y-%m-%d %H:%M:%S"),
        (r"\d{1,2}\.\d{1,2}\.\d{4}", "%d.%m.%Y %H:%M:%S"),
        (r"\d{1,2}/\d{1,2}/\d{4}", "%m/%d/%Y %H:%M:%S"),
        (r"\d{1,2}:\d{2}:\d{2}\.\d+", "%H:%M:%S.%f"),
        (r"\d{1,2}:\d{2}:\d{2}", "%H:%M:%S"),
    )
    for pattern, fmt in patterns:
        if re.match(pattern, v):
            return fmt
    return ""


def format_category(fmt: str) -> str:
    """`numeric`, `datetime` or `time_of_day`, by the loader's own rule."""
    if not fmt or fmt == ELAPSED_FORMAT or fmt.startswith("epoch_"):
        return "numeric"
    if fmt in ("iso8601", "datetime") or any(d in fmt for d in ("%Y", "%m", "%d")):
        return "datetime"
    if fmt == "time_of_day" or any(d in fmt for d in ("%H", "%M", "%S")):
        return "time_of_day"
    return "numeric"


def values_carry_offset(sample_values: Sequence[str]) -> bool:
    """Whether text timestamps state their own UTC offset (`Z`, `+02:00`)."""
    values = [value.strip() for value in sample_values if value.strip()]
    return bool(values) and all(_OFFSET_SUFFIX.search(value) for value in values)


def needs_timezone(fmt: str, sample_values: Sequence[str]) -> bool:
    """A zone decides the instant only for text times that do not state one."""
    category = format_category(fmt)
    if category == "numeric":
        if fmt:
            return False
        # Auto-detect over text the guesser could not name still parses as text.
        try:
            float(next(v for v in sample_values if v.strip()))
        except (StopIteration, ValueError):
            return any(v.strip() for v in sample_values)
        return False
    return not values_carry_offset(sample_values)


def unit_from_header(header: str) -> str:
    """The unit a header declares in a trailing `(mV)` or `[V]`, else ""."""
    match = _UNIT_IN_HEADER.search(header.strip())
    return match.group(1).strip() if match else ""


_UNIT_SECONDS = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9}


def _epoch_seconds(fmt: str, unit: str) -> float:
    if fmt.startswith("epoch_") and fmt != "epoch_s":
        return _UNIT_SECONDS.get(fmt.removeprefix("epoch_"), 1.0)
    if fmt == "epoch_s":
        return 1.0
    return _UNIT_SECONDS.get(unit, 1.0)


def parse_sample_times(
    values: Sequence[str],
    fmt: str,
    unit: str,
    timezone: str,
    *,
    euro_decimal: bool = False,
) -> list[float] | None:
    """Seconds for the preview rows as the loader would read them, or None.

    Only the bounded preview prefix is ever passed here, so this stays on the
    UI thread well inside its budget.
    """
    texts = [value.strip() for value in values if value.strip()]
    if not texts:
        return None
    category = format_category(fmt)
    try:
        if category == "numeric":
            scale = _epoch_seconds(fmt, unit)
            if euro_decimal:
                texts = [text.replace(",", ".") for text in texts]
            return [float(text) * scale for text in texts]
        zone: datetime.tzinfo = datetime.UTC
        if timezone:
            try:
                zone = ZoneInfo(timezone)
            except (ZoneInfoNotFoundError, ValueError):
                zone = datetime.UTC
        out: list[float] = []
        for text in texts:
            if category == "datetime":
                stamp = (
                    datetime.datetime.fromisoformat(text)
                    if fmt in ("", "iso8601", "datetime")
                    else datetime.datetime.strptime(text, fmt)
                )
            else:
                clock = datetime.datetime.strptime(text, fmt or "%H:%M:%S.%f")
                stamp = datetime.datetime.combine(datetime.date(1970, 1, 1), clock.time())
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=zone)
            out.append(stamp.timestamp())
        return out
    except ValueError:
        return None


@dataclass(frozen=True)
class TimeSummary:
    """What the preview rows will become once parsed."""

    start: str
    rows: int
    span_s: float
    step_s: float


def summarize_times(seconds: Sequence[float] | None, fmt: str) -> TimeSummary | None:
    """Summarize parsed preview times, or None when nothing parsed.

    `start` is elapsed seconds for an elapsed column and a UTC date-time
    otherwise; the wizard owns the translated sentence around it.
    """
    if not seconds:
        return None
    first, last = seconds[0], seconds[-1]
    steps = sorted(b - a for a, b in zip(seconds, seconds[1:], strict=False))
    step = steps[len(steps) // 2] if steps else 0.0
    if format_category(fmt) == "numeric" and guess_numeric_format(first) == ELAPSED_FORMAT:
        start = f"{first:.6g} s"
    else:
        start = (
            datetime.datetime.fromtimestamp(first, tz=datetime.UTC)
            .isoformat(sep=" ", timespec="milliseconds")
            .replace("+00:00", " UTC")
        )
    return TimeSummary(start=start, rows=len(seconds), span_s=last - first, step_s=step)
