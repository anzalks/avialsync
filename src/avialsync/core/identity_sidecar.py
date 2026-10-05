"""Where an accepted identity flip lives: a CSV beside the pose file.

Same reasoning as :mod:`avialsync.core.point_edit_sidecar`, and deliberately
the same shape.  A flip is a fact about the *recording* -- "these two have been
each other since frame 6 810" -- not about the session that happened to be open
when it was found.  Keeping it in the ``.avv`` would mean reopening the same
pose file in a new session showed the swapped identities again, and a
collaborator handed the data folder got none of the work.

**The groups travel with the events.**  A row names two lanes and a group id;
the ``# groups:`` provenance line states what those lanes own, and also retains
a user-declared group before its first accepted swap. Deriving them
again from the pose file would be one line shorter and would silently
misinterpret every event the day a loader names something differently.

**Nothing here deletes or rewrites anything but this one file.**  The pose CSV
is never opened for writing.  When the last flip is undone the sidecar is
rewritten *empty* rather than removed, for the same reason the corrections one
is: a file saying "no flips" costs one inode and never risks removing something
in a data directory this process did not create.
"""

from __future__ import annotations

import csv
import datetime as _datetime
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from avialsync.core import sidecar_names
from avialsync.core.identity_groups import is_custom
from avialsync.core.identity_swaps import SwapEvent, SwapGroup

logger = logging.getLogger(__name__)

__all__ = [
    "SIDECAR_SUFFIX",
    "Swaps",
    "sidecar_path",
    "is_swap_path",
    "read",
    "write",
]

#: Appended to the source's full file name, dots made underscores, as the
#: corrections file is (:mod:`avialsync.core.sidecar_names`):
#: `pose.csv` -> `pose_csv_avialswap.csv`.
SIDECAR_SUFFIX = "_avialswap.csv"

_COLUMNS = ("frame", "group", "lane_a", "lane_b", "parts")

#: Written in the ``parts`` column for an event that moves the whole group.
_ALL = "*"
#: Separates several part names inside the one ``parts`` field.
_PART_SEPARATOR = "|"

_HEADER_COMMENT = (
    "AvialSync tracking identity swaps",
    "Each row says that two lanes -- two animals, or a left and a right --",
    "exchange labels from that frame onward, until another row changes it.",
    "The pose file named below is never modified: delete this file and the",
    "original predictions are exactly what they were.",
)


@dataclass(frozen=True)
class Swaps:
    """What a sidecar held, plus what it says about the file it belongs to."""

    events: list[SwapEvent] = field(default_factory=list)
    groups: list[SwapGroup] = field(default_factory=list)
    #: Size of the pose file when the flips were written.  Evidence, never a
    #: gate: a re-exported pose file with different frame numbering would put
    #: old flips on the wrong frames, and the caller warns rather than
    #: discarding a user's work on a guess.
    source_bytes: int | None = None
    #: Rows that could not be read.  A damaged sidecar yields what it can and
    #: says how much it lost (Law 1 -- never block, always inform).
    skipped: int = 0


def sidecar_path(source: Path | str) -> Path:
    """Return the swaps file that belongs beside *source*."""
    return sidecar_names.beside(source, SIDECAR_SUFFIX)


def is_swap_path(path: Path | str) -> bool:
    """Return whether *path* is one of our own swap sidecars.

    Drop scanning and format sniffing both consult this: the file is a CSV and
    the tracking loader would otherwise offer to import our own output.
    """
    return Path(path).name.endswith(SIDECAR_SUFFIX)


def read(source: Path | str) -> Swaps | None:
    """Read the flips beside *source*, or None when there are none.

    Returns ``None`` when no sidecar exists or it cannot be opened at all; an
    empty :class:`Swaps` when the file exists and records none.
    """
    path = sidecar_path(source)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        logger.warning("Could not read tracking identity swaps at %s", path, exc_info=True)
        return None

    source_bytes: int | None = None
    groups: list[SwapGroup] = []
    rows: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            key, separator, value = line[1:].strip().partition(":")
            if not separator:
                continue
            if key.strip() == "source_bytes":
                try:
                    source_bytes = int(value.strip())
                except ValueError:
                    source_bytes = None
            elif key.strip() == "groups":
                groups = _read_groups(value.strip(), path)
            continue
        if line.strip():
            rows.append(line)

    events: list[SwapEvent] = []
    skipped = 0
    for record in csv.DictReader(rows):
        try:
            events.append(
                SwapEvent(
                    index=int(record["frame"]),
                    group=str(record["group"]),
                    lanes=(str(record["lane_a"]), str(record["lane_b"])),
                    parts=_read_parts(record["parts"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            skipped += 1
    return Swaps(events=events, groups=groups, source_bytes=source_bytes, skipped=skipped)


def _read_groups(value: str, path: Path) -> list[SwapGroup]:
    """Parse the provenance line, or report it and carry on with the rows."""
    try:
        payload = json.loads(value)
    except ValueError:
        logger.warning("Ignoring unreadable group definitions in %s", path)
        return []
    if not isinstance(payload, list):
        return []
    groups: list[SwapGroup] = []
    for entry in payload:
        if isinstance(entry, dict):
            groups.append(SwapGroup.from_dict(entry))
    return groups


def _read_parts(value: str) -> tuple[str, ...]:
    text = (value or "").strip()
    if not text or text == _ALL:
        return ()
    return tuple(part for part in text.split(_PART_SEPARATOR) if part)


def write(
    source: Path | str,
    events: list[SwapEvent],
    groups: list[SwapGroup] | None = None,
) -> Path:
    """Write *events* beside *source* atomically and return the path.

    Raises ``OSError`` when the directory cannot be written -- an archived
    acquisition on read-only media is the expected case, and the caller falls
    back to storing the flips in the session rather than losing them.
    """
    path = Path(source)
    target = sidecar_path(path)
    try:
        source_bytes: int | None = path.stat().st_size
    except OSError:
        source_bytes = None

    referenced = {event.group for event in events}
    carried = [
        group for group in (groups or []) if group.name in referenced or is_custom(group.name)
    ]

    lines = [f"# {line}" for line in _HEADER_COMMENT]
    lines.append(f"# source: {path.name}")
    if source_bytes is not None:
        lines.append(f"# source_bytes: {source_bytes}")
    written = _datetime.datetime.now(_datetime.UTC).isoformat(timespec="seconds")
    lines.append(f"# written: {written}")
    if carried:
        lines.append("# groups: " + json.dumps([group.as_dict() for group in carried]))
    if not events:
        lines.append("# no identity swaps recorded")
    lines.append(",".join(_COLUMNS))
    for event in sorted(events):
        parts = _PART_SEPARATOR.join(event.parts) if event.parts else _ALL
        lines.append(f"{event.index},{event.group},{event.lanes[0]},{event.lanes[1]},{parts}")

    # Same atomic shape as the corrections writer: a temporary file in the
    # target's own directory, then one rename. A half-written sidecar is the
    # one outcome that would lose work rather than merely fail.
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target
