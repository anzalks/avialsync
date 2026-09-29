"""Writing a corrected copy of a pose file, for whatever reads pose files next.

The corrections sidecar answers "what did a person change"; this answers "what
should the analysis use".  It is a full copy of the DeepLabCut / LightningPose
CSV with the corrected coordinates substituted in, so anything that consumed the
original consumes this without knowing anything about AvialSync.

Three decisions are worth stating where the code is.

**The original is copied, never edited.**  The source is read row by row and a
new file is written; the input is opened read-only and is not the file that
``os.replace`` lands on.  A corrected copy that overwrote the prediction would
destroy the model's output in the act of disagreeing with it (D-099).

**The scorer is renamed.**  A strict DLC-format CSV has no comment syntax and a
fixed column layout, so there is exactly one field that can carry provenance
without breaking a reader: the scorer name.  A corrected file therefore says
``<scorer>_avialsync_corrected`` in row one.  Six months later, a file that
mixes model output with human judgement and does not say so is indistinguishable
from model output, and that is the failure this exists to prevent.

**A multi-animal file's columns are found by individual *and* body part.**
A maDLC export repeats ``snout`` once per animal, so a column index keyed by
body part alone keeps whichever animal came last and writes every correction
into that one's columns.  The point names come from
:mod:`avialsync.core.pose_header`, which is also what the loader named its
channels after, so a correction lands in the columns it was made on.

**A corrected point's likelihood becomes 1.0.**  This is not cosmetic.  The
coordinate a person corrected is usually one the model was unsure about, so it
carries a low likelihood — and the first thing most downstream code does is drop
rows below a likelihood threshold.  Leaving the old value would mean the
correction was written, exported, and then silently filtered out of the
analysis it was made for.
"""

from __future__ import annotations

import csv
import itertools
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from avialsync.core.pose_header import parse_pose_header

logger = logging.getLogger(__name__)

__all__ = ["CorrectedCopyReport", "SCORER_SUFFIX", "write_corrected_copy", "corrected_copy_path"]

#: Appended to the scorer name of a corrected copy — the one in-band field a
#: fixed-layout pose CSV leaves for saying a human touched this.
SCORER_SUFFIX = "_avialsync_corrected"

#: Written into the ``likelihood`` column of a corrected coordinate.
CORRECTED_LIKELIHOOD = "1.0"

#: A single-animal header; a multi-animal one adds an ``individuals`` row.
_MIN_HEADER_ROWS = 3


@dataclass(frozen=True)
class CorrectedCopyReport:
    """What a corrected copy turned out to contain."""

    rows: int = 0
    corrected_rows: int = 0
    corrected_points: int = 0
    #: Frames named by a correction that the pose file does not contain. Counted
    #: rather than raised: the rest of the export is still worth having, and the
    #: caller reports the number (Law 1 — never block, always inform).
    unmatched_frames: int = 0


def corrected_copy_path(source: Path | str) -> Path:
    """Return the default output path for *source*'s corrected copy."""
    path = Path(source)
    return path.with_name(f"{path.stem}_corrected{path.suffix or '.csv'}")


def write_corrected_copy(
    source: Path | str,
    target: Path | str,
    corrections: dict[int, dict[str, tuple[float, float]]],
    *,
    mark_scorer: bool = True,
) -> CorrectedCopyReport:
    """Copy *source* to *target* with *corrections* applied.

    ``corrections`` maps a **video frame number** to the body parts corrected on
    it.  Rows stream one at a time: a pose file is routinely hundreds of
    thousands of rows and this must not depend on holding one in memory.
    """
    source_path = Path(source)
    target_path = Path(target)

    with open(source_path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        # One row past the longest header shape, so the fourth row is available
        # to tell a multi-animal header from the first data row. Whatever the
        # parser does not claim as header is pushed back in front of the rows.
        peeked = list(_take(reader, _MIN_HEADER_ROWS + 1))
        header_block = parse_pose_header(peeked)
        if header_block is None:
            raise ValueError(
                f"{source_path.name} has no DeepLabCut or LightningPose header block; "
                "its first rows are not scorer/[individuals/]bodyparts/coords."
            )

        header = [list(line) for line in header_block.lines]
        columns = header_block.column_index()
        if mark_scorer:
            header[0] = _renamed_scorers(header[0])

        rows = itertools.chain(peeked[header_block.rows :], reader)
        temporary = target_path.with_name(f".{target_path.name}.tmp")
        report = _stream(rows, temporary, header, columns, corrections)

    os.replace(temporary, target_path)
    return report


def _take(reader: Iterator[list[str]], count: int) -> Iterator[list[str]]:
    """Yield up to *count* rows, stopping early on a file shorter than that."""
    for _, row in zip(range(count), reader, strict=False):
        yield row


def _renamed_scorers(scorers: list[str]) -> list[str]:
    """Mark every scorer column, leaving the index column's own label alone."""
    marked = list(scorers)
    for position, value in enumerate(marked):
        if position == 0 or not value.strip():
            continue
        if not value.endswith(SCORER_SUFFIX):
            marked[position] = f"{value}{SCORER_SUFFIX}"
    return marked


def _stream(
    reader: Iterator[list[str]],
    temporary: Path,
    header: list[list[str]],
    columns: dict[tuple[str, str], int],
    corrections: dict[int, dict[str, tuple[float, float]]],
) -> CorrectedCopyReport:
    """Write header and rows, substituting corrections as each row goes past."""
    rows = 0
    corrected_rows = 0
    corrected_points = 0
    seen_frames: set[int] = set()

    with open(temporary, "w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        for line in header:
            writer.writerow(line)
        for row in reader:
            rows += 1
            frame = _frame_of(row)
            if frame is not None:
                wanted = corrections.get(frame)
                if wanted:
                    seen_frames.add(frame)
                    replaced = _apply(row, columns, wanted)
                    if replaced:
                        corrected_rows += 1
                        corrected_points += replaced
            writer.writerow(row)

    return CorrectedCopyReport(
        rows=rows,
        corrected_rows=corrected_rows,
        corrected_points=corrected_points,
        unmatched_frames=len(set(corrections) - seen_frames),
    )


def _frame_of(row: list[str]) -> int | None:
    """Read the frame number out of a data row's index column.

    ``None`` for a row whose index is not a frame number — a labeled-data export
    keys on an image path, and no correction can be matched to it.
    """
    if not row:
        return None
    try:
        return int(float(row[0]))
    except (TypeError, ValueError):
        return None


def _apply(
    row: list[str],
    columns: dict[tuple[str, str], int],
    wanted: dict[str, tuple[float, float]],
) -> int:
    """Substitute one row's corrected coordinates in place; returns how many."""
    replaced = 0
    for part, (x, y) in wanted.items():
        x_column = columns.get((part, "x"))
        y_column = columns.get((part, "y"))
        if x_column is None or y_column is None:
            continue
        if x_column >= len(row) or y_column >= len(row):
            continue
        row[x_column] = repr(float(x))
        row[y_column] = repr(float(y))
        # See the module docstring: a corrected point that keeps the model's low
        # likelihood is dropped by the first threshold downstream, which would
        # silently discard the correction it was exported for.
        likelihood_column = columns.get((part, "likelihood"))
        if likelihood_column is not None and likelihood_column < len(row):
            row[likelihood_column] = CORRECTED_LIKELIHOOD
        replaced += 1
    return replaced
