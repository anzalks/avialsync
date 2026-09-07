"""Where a hand correction lives: a CSV beside the pose file it corrects.

A correction is a fact about the *recording* — "the nose was really here at
frame 4120" — not about the session that happened to be open when it was made.
Keeping it in the ``.avv`` bound it to a viewing arrangement: reopening the same
pose file in a new session showed none of it, and a collaborator handed the data
folder got none of it either. So the sidecar is the authority and the session
records only a count, which is what lets a missing sidecar be *reported* rather
than silently show fewer points (D-099).

**CSV, not JSON.** A few hundred rows that a person will want to check belong in
something they can open in pandas or a spreadsheet without a parser. The
provenance header is `#`-commented, which both `polars.read_csv(comment_prefix=)`
and `pandas.read_csv(comment=)` skip.

**Beside the file, not inside `.avialcache/`.** That directory is derived state,
rebuilt from a content hash and safe to delete; corrections are irreplaceable
human work. Putting them there would mean a cache clear ate an afternoon of it.

**Nothing here deletes or rewrites anything but this one file.** The pose CSV is
never opened for writing. When the last correction for a source is undone the
sidecar is rewritten *empty* rather than removed — leaving a file that says "no
corrections" costs one inode and never risks removing something in a data
directory that this process did not create.
"""

from __future__ import annotations

import csv
import datetime as _datetime
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "SIDECAR_SUFFIX",
    "Correction",
    "Corrections",
    "sidecar_path",
    "is_correction_path",
    "read",
    "write",
]

#: Appended to the source's **full** file name, matching the `<file>.avialcache/`
#: convention: `eks.csv` -> `eks.csv.avialfix.csv`. Appending to the whole name
#: rather than the stem is what keeps `a.csv` and `a.h5` from colliding.
SIDECAR_SUFFIX = ".avialfix.csv"

_COLUMNS = ("frame", "bodypart", "x", "y")
_HEADER_COMMENT = (
    "AvialSync tracking corrections",
    "Hand corrections to predicted body-part positions, made with Fix Tracker.",
    "The pose file named below is never modified: delete this file and the",
    "original predictions are exactly what they were.",
)


@dataclass(frozen=True, slots=True)
class Correction:
    """One corrected coordinate, as it is written to disk."""

    frame: int
    bodypart: str
    x: float
    y: float


@dataclass(frozen=True)
class Corrections:
    """What a sidecar held, plus what it says about the file it corrects."""

    entries: list[Correction] = field(default_factory=list)
    #: Size of the pose file when the corrections were written. Recorded as
    #: evidence, never as a gate: a re-exported pose file with different frame
    #: numbering would put old corrections on the wrong frames, and the caller
    #: warns about that rather than discarding a user's work on a guess.
    source_bytes: int | None = None
    #: Rows that could not be read. A damaged sidecar yields what it can and
    #: says how much it lost (Law 1 — never block, always inform).
    skipped: int = 0


def sidecar_path(source: Path | str) -> Path:
    """Return the corrections file that belongs beside *source*."""
    path = Path(source)
    return path.with_name(path.name + SIDECAR_SUFFIX)


def is_correction_path(path: Path | str) -> bool:
    """Return whether *path* is one of our own corrections sidecars.

    Drop scanning and format sniffing both consult this: the file is a CSV and
    the tracking loader would otherwise offer to import our own output.
    """
    return Path(path).name.endswith(SIDECAR_SUFFIX)


def read(source: Path | str) -> Corrections | None:
    """Read the corrections beside *source*, or None when there are none.

    Returns ``None`` when no sidecar exists or it cannot be opened at all; an
    empty :class:`Corrections` when the file exists and records none.
    """
    path = sidecar_path(source)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        logger.warning("Could not read tracking corrections at %s", path, exc_info=True)
        return None

    source_bytes: int | None = None
    rows: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            key, separator, value = line[1:].strip().partition(":")
            if separator and key.strip() == "source_bytes":
                try:
                    source_bytes = int(value.strip())
                except ValueError:
                    source_bytes = None
            continue
        if line.strip():
            rows.append(line)

    entries: list[Correction] = []
    skipped = 0
    for record in csv.DictReader(rows):
        try:
            entries.append(
                Correction(
                    frame=int(record["frame"]),
                    bodypart=str(record["bodypart"]),
                    x=float(record["x"]),
                    y=float(record["y"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            skipped += 1
    return Corrections(entries=entries, source_bytes=source_bytes, skipped=skipped)


def write(source: Path | str, entries: list[Correction]) -> Path:
    """Write *entries* beside *source* atomically and return the path.

    Raises ``OSError`` when the directory cannot be written — an archived
    acquisition on read-only media is the expected case, and the caller falls
    back to storing the corrections in the session rather than losing them.
    """
    path = Path(source)
    target = sidecar_path(path)
    try:
        source_bytes: int | None = path.stat().st_size
    except OSError:
        source_bytes = None

    lines = [f"# {line}" for line in _HEADER_COMMENT]
    lines.append(f"# source: {path.name}")
    if source_bytes is not None:
        lines.append(f"# source_bytes: {source_bytes}")
    written = _datetime.datetime.now(_datetime.UTC).isoformat(timespec="seconds")
    lines.append(f"# written: {written}")
    if not entries:
        lines.append("# no corrections recorded")
    lines.append(",".join(_COLUMNS))
    for entry in sorted(entries, key=lambda item: (item.frame, item.bodypart)):
        lines.append(f"{entry.frame},{entry.bodypart},{entry.x!r},{entry.y!r}")

    # Same atomic shape as the session writer: a temporary file in the target's
    # own directory, then one rename. A half-written corrections file is the one
    # outcome that would lose work rather than merely fail.
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target
