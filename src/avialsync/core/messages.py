"""Free-text records the acquisition system stored alongside the data.

Experimentalists annotate recordings while they run — a note typed into the
acquisition software when the animal starts the task, a comment appended to a
file after the session ended.  Those records are evidence written by the rig,
not by this application, which is what separates them from
:mod:`avialsync.ui.annotations`: a marker there is authored, editable, and
exported; a message here is read-only and belongs to the source file.

No PySide6 imports — enforced by ``test_headless_core.py``.
"""

from __future__ import annotations

import dataclasses
from typing import Any

#: Messages are display evidence, so the number carried through the sidecar
#: manifest and into the panel is bounded, exactly like
#: :data:`~avialsync.engine.importer.MAX_GAP_LOCATIONS`.  A rig configured to
#: log a line per trial is a few thousand records; one misconfigured to log a
#: line per sample would otherwise put millions of strings into a JSON file that
#: is read synchronously on every cache hit.
MAX_MESSAGES = 5_000

#: Longest single message kept intact.  Anything past this is truncated with an
#: ellipsis: a stray binary blob decoded as text is not worth a megabyte of
#: manifest, and no table cell can show it anyway.
MAX_MESSAGE_CHARS = 2_000


@dataclasses.dataclass(frozen=True)
class Message:
    """One free-text record read from a source file.

    ``time`` is in the *source's* own timeline, exactly like a sample timestamp.
    The same :class:`~avialsync.core.timeline.TimeMap` that places the source's
    channels on the master clock therefore places its messages, so correcting an
    offset moves a note and the trace it describes together.

    ``time`` is ``None`` when the record carries no time at all — a file header,
    a comment appended after the recording stopped.  Such a record is shown as
    an untimed note rather than pinned to the start of the timeline: placing it
    anywhere on the clock would assert a moment the file never recorded.
    """

    text: str
    time: float | None = None

    #: The stream inside the file that carried it, when the file has more than
    #: one.  Open Ephys names its annotation stream ``MessageCenter``; knowing
    #: which stream spoke is what tells a user whether a note came from the
    #: acquisition software or from a hardware event line.
    channel: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "time": self.time, "channel": self.channel}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Message:
        raw_time = d.get("time")
        return cls(
            text=str(d.get("text", "")),
            time=None if raw_time is None else float(raw_time),
            channel=str(d.get("channel", "")),
        )


def clean(text: str) -> str:
    """Return *text* as a single-line, length-bounded message body.

    Embedded newlines are folded to spaces because every consumer is a one-line
    table cell or a tooltip; a multi-line record would silently render as its
    first line alone, which is worse than showing all of it compressed.
    """
    folded = " ".join(str(text).split())
    if len(folded) > MAX_MESSAGE_CHARS:
        return folded[: MAX_MESSAGE_CHARS - 1] + "…"
    return folded


def bounded(messages: list[Message]) -> tuple[Message, ...]:
    """Return *messages* sorted with untimed records first, capped at the limit.

    Untimed records lead because they are the file's preamble — the header a
    reader wants before the timeline starts — and because there is no time to
    sort them by.  Timed records follow in source-time order.
    """
    untimed = [m for m in messages if m.time is None]
    timed = sorted((m for m in messages if m.time is not None), key=lambda m: float(m.time or 0.0))
    return tuple((untimed + timed)[:MAX_MESSAGES])
