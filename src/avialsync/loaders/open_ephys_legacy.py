"""Free text an Open Ephys *original-format* recording carries.

The original format — one ``.continuous`` file per channel, from GUI versions
before the binary format — keeps whatever the experimenter typed in a plain
``messages.events`` beside the samples.  neo reads everything else in the folder
and deliberately not this: ``openephysrawio.py`` filters the file out by name
and leaves the event channel that would carry it commented out, marked "not
implemented yet".  So the prose is simply absent, with nothing reporting that it
is (D-085).

The file is ASCII, and unlike every other file in the folder it has **no**
1024-byte header — it is lines of ``<sample number> <text>``.  The first lines
are the recording's own sync preamble::

    0 Software time: 145610@1000000Hz
    0 Processor: 101 start time: 0@30000Hz

Those are read for the sample rate and then withheld, exactly as the binary
format's ``sync_messages.txt`` is parsed for its epoch rather than shown: a
preamble is what places the clock, not something the experimenter wrote.

The rate comes only from the ``start time:`` line.  The ``Software time:`` line
carries a 1 MHz software clock, and taking its rate instead would divide every
message time by about 33.

Reference: Open Ephys "Open Ephys format" (GUI v0.5 and earlier).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from avialsync.core.messages import MAX_MESSAGES, Message, clean

logger = logging.getLogger(__name__)

#: The file that holds the prose, and the one neo declines to read.
MESSAGES_NAME = "messages.events"

#: Every other file in an original-format folder opens with this many bytes of
#: ``key = value;`` text.  ``messages.events`` does not, which is why it is
#: read as text from byte zero.
_HEADER_SIZE = 1024

#: ``0 Processor: 101 start time: 0@30000Hz`` — the acquisition rate, declared
#: by the recording itself.
_START_TIME_PATTERN = re.compile(r"start\s+time:\s*\d+@([\d.]+)\s*Hz", re.IGNORECASE)

#: ``sampleRate = 30000.0;`` inside a ``.continuous`` header, used when the
#: preamble does not declare a rate.
_HEADER_RATE_PATTERN = re.compile(rb"sampleRate\s*=\s*([\d.]+)")

#: A line the recording wrote about itself rather than for a reader.  Consumed
#: for the clock it declares and never shown.
_PREAMBLE_PATTERN = re.compile(
    r"^\s*-?\d+\s+(?:Software\s+time:|Processor:\s*\d+\s+start\s+time:)", re.IGNORECASE
)

#: ``<sample number> <whatever was typed>``.
_MESSAGE_PATTERN = re.compile(r"^\s*(-?\d+)\s+(.*)$")


def is_legacy_recording(path: Path) -> bool:
    """Return whether *path* is an original-format recording directory.

    Both halves are required.  ``messages.events`` alone is not a recording, and
    a folder of ``.continuous`` files without one simply has no prose to read.
    """
    if not path.is_dir() or not (path / MESSAGES_NAME).is_file():
        return False
    return any(path.glob("*.continuous"))


def read_messages(recording: Path) -> list[Message]:
    """Return what the experimenter typed during an original-format recording.

    Times are sample numbers divided by the acquisition rate and **not** rebased
    on the first recorded sample, because that is the axis neo puts the samples
    on: ``_segment_t_start`` is ``timestamp0 / sampling_rate``.  Rebasing here
    would offset every note from the trace it describes by the recording's own
    start.

    A note whose rate cannot be established stays untimed rather than being
    pinned to zero (D-078).  Open Ephys' own stamp is also known to keep running
    while recording is paused, so a message in a paused recording names a moment
    slightly past the sample it was typed at — that is the file's claim, and it
    is reported as the file makes it rather than silently corrected.
    """
    text = _read_text(recording / MESSAGES_NAME)
    if text is None:
        return []

    lines = [line for line in text.splitlines() if line.strip()]
    rate = _declared_rate(lines) or _rate_from_continuous_header(recording)
    if rate is None:
        logger.info(
            "Open Ephys recording %s declares no sample rate; its messages stay untimed.",
            recording.name,
        )

    found: list[Message] = []
    for line in lines:
        if len(found) >= MAX_MESSAGES:
            break
        if _PREAMBLE_PATTERN.match(line):
            continue
        match = _MESSAGE_PATTERN.match(line)
        if match is None:
            # No leading stamp at all.  The file did not time this, so neither
            # do we; it is still something somebody wrote.
            body = clean(line)
            if body:
                found.append(Message(text=body, time=None, channel=MESSAGES_NAME))
            continue
        body = clean(match.group(2))
        if not body:
            continue
        stamp = float(match.group(1))
        found.append(
            Message(
                text=body,
                time=None if rate is None else stamp / rate,
                channel=MESSAGES_NAME,
            )
        )
    return found


def _read_text(path: Path) -> str | None:
    """Return the messages file as text, or ``None`` when it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        logger.warning("Cannot read Open Ephys messages at %s", path, exc_info=True)
        return None


def _declared_rate(lines: list[str]) -> float | None:
    """Return the acquisition rate the sync preamble declares, if it does."""
    for line in lines:
        match = _START_TIME_PATTERN.search(line)
        if match is None:
            continue
        try:
            rate = float(match.group(1))
        except ValueError:  # pragma: no cover - the pattern only matches numbers
            continue
        if rate > 0.0:
            return rate
    return None


def _rate_from_continuous_header(recording: Path) -> float | None:
    """Return the rate from any ``.continuous`` header in *recording*.

    The preamble is missing from recordings whose first lines were lost to the
    pause bug, and every ``.continuous`` file states the rate in its own header,
    so the folder can still answer for itself.
    """
    for candidate in sorted(recording.glob("*.continuous")):
        try:
            with candidate.open("rb") as handle:
                header = handle.read(_HEADER_SIZE)
        except OSError:
            continue
        match = _HEADER_RATE_PATTERN.search(header)
        if match is None:
            continue
        try:
            rate = float(match.group(1))
        except ValueError:  # pragma: no cover - the pattern only matches numbers
            continue
        if rate > 0.0:
            return rate
    return None
