"""Writing a corrected copy of a pose file, for whatever reads pose files next.

The corrections sidecar answers "what did a person change"; this answers "what
should the analysis use".  It is a full copy of the DeepLabCut / LightningPose
CSV with the corrected coordinates substituted in, so anything that consumed the
original consumes this without knowing anything about AvialSync.

Three decisions are worth stating where the code is.

**The original is copied, never edited.**  The source is read row by row and a
new file is written; the input is opened read-only and is not the file that
``os.replace`` lands on.  A corrected copy that overwrote the prediction would
destroy the model's output in the act of disagreeing with it.

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

**An identity swap is a permutation of the columns, row by row.**  The same
file carries both kinds of edit, because they are one body of work about one
recording and an analysis wants one file.  The order is fixed and it
matters: a correction lands in the column it was made on, and the routing then
carries it wherever that column is displayed.  Reversed, a correction made
before a flip would stay on screen while the animal it belongs to walked away
with the other label.  The whole point moves together -- coordinates, likelihood
and any extra per-point fields -- because a coordinate separated from its
confidence is not a pose.

**A corrected point's likelihood becomes 1.0.**  This is not cosmetic.  The
coordinate a person corrected is usually one the model was unsure about, so it
carries a low likelihood — and the first thing most downstream code does is drop
rows below a likelihood threshold.  Leaving the old value would mean the
correction was written, exported, and then silently filtered out of the
analysis it was made for.
"""

from __future__ import annotations

import bisect
import csv
import itertools
import logging
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from avialsync.core.artifact_io import publish
from avialsync.core.artifact_provenance import record, write_companion
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
    #: Rows whose columns an accepted identity swap moved.
    swapped_rows: int = 0
    #: Frames named by a correction that the pose file does not contain. Counted
    #: rather than raised: the rest of the export is still worth having, and the
    #: caller reports the number (never block, always inform).
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
    routes: Sequence[tuple[int, Mapping[str, str]]] = (),
    mark_scorer: bool = True,
) -> CorrectedCopyReport:
    """Copy *source* to *target* with *corrections* and *routes* applied.

    ``corrections`` maps a **video frame number** to the body parts corrected on
    it, named by the column they belong to.  ``routes`` is the accepted identity
    swaps as ``(from this frame, display point -> the point whose data it
    shows)``, ascending, which is what
    :meth:`avialsync.core.edit_program.EditProgram.route_at` produces.

    Rows stream one at a time: a pose file is routinely hundreds of thousands of
    rows and this must not depend on holding one in memory.
    """
    source_path = Path(source)
    target_path = Path(target)
    if source_path.resolve() == target_path.resolve():
        raise ValueError("The corrected copy must have a different path from the recording.")

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
        result: list[CorrectedCopyReport] = []

        def write(temporary: Path) -> None:
            result.append(_stream(rows, temporary, header, columns, corrections, tuple(routes)))

        publish(target_path, write, kind="corrected-pose", sources=(source_path,))
        report = result[0]
    write_companion(
        target_path,
        record(
            "corrected-pose",
            (source_path,),
            edit_counts={
                "corrected_points": report.corrected_points,
                "swapped_rows": report.swapped_rows,
            },
        ),
        sources=(source_path,),
    )
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


def _compile_routes(
    columns: dict[tuple[str, str], int],
    routes: tuple[tuple[int, Mapping[str, str]], ...],
) -> tuple[list[int], tuple[tuple[tuple[int, int], ...], ...]]:
    """Precompute ``(dst_col, src_col)`` integer index pairs once per routing interval."""
    if not routes:
        return [], ()
    fields_by_point: dict[str, dict[str, int]] = {}
    for (point, field), col_idx in columns.items():
        fields_by_point.setdefault(point, {})[field] = col_idx
    boundaries = [boundary for boundary, _ in routes]
    compiled: list[tuple[tuple[int, int], ...]] = []
    for _boundary, route in routes:
        pairs: list[tuple[int, int]] = []
        for display, data in route.items():
            if display == data:
                continue
            d_cols = fields_by_point.get(display)
            s_cols = fields_by_point.get(data)
            if d_cols is None or s_cols is None:
                continue
            for field, dst_idx in d_cols.items():
                src_idx = s_cols.get(field)
                if src_idx is not None and dst_idx != src_idx:
                    pairs.append((dst_idx, src_idx))
        compiled.append(tuple(pairs))
    return boundaries, tuple(compiled)


def _apply_compiled_remap(row: list[str], pairs: tuple[tuple[int, int], ...]) -> bool:
    """Apply precomputed ``(dst_col, src_col)`` column permutation to one CSV *row*."""
    if not pairs:
        return False
    row_len = len(row)
    staged = [(dst, row[src]) for dst, src in pairs if dst < row_len and src < row_len]
    moved = False
    for dst, value in staged:
        if row[dst] != value:
            moved = True
            row[dst] = value
    return moved


def _stream(
    reader: Iterator[list[str]],
    temporary: Path,
    header: list[list[str]],
    columns: dict[tuple[str, str], int],
    corrections: dict[int, dict[str, tuple[float, float]]],
    routes: tuple[tuple[int, Mapping[str, str]], ...],
) -> CorrectedCopyReport:
    """Write header and rows, applying corrections then routing to each one."""
    rows = 0
    corrected_rows = 0
    corrected_points = 0
    swapped_rows = 0
    seen_frames: set[int] = set()
    boundaries, compiled_routes = _compile_routes(columns, routes)

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
                if boundaries and frame >= boundaries[0]:
                    pairs = compiled_routes[bisect.bisect_right(boundaries, frame) - 1]
                    if pairs and _apply_compiled_remap(row, pairs):
                        swapped_rows += 1
            writer.writerow(row)

    return CorrectedCopyReport(
        rows=rows,
        corrected_rows=corrected_rows,
        corrected_points=corrected_points,
        swapped_rows=swapped_rows,
        unmatched_frames=len(set(corrections) - seen_frames),
    )


def _route_at(
    routes: tuple[tuple[int, Mapping[str, str]], ...],
    boundaries: list[int],
    frame: int,
) -> Mapping[str, str]:
    """The identity in force on *frame*: the last route at or before it."""
    if not routes or frame < boundaries[0]:
        return {}
    return routes[bisect.bisect_right(boundaries, frame) - 1][1]


def _reroute(row: list[str], columns: dict[tuple[str, str], int], route: Mapping[str, str]) -> bool:
    """Move each point's cells to the point that displays them.

    Read wholly before anything is written: a swap is a cycle, and writing as
    it goes would hand the second point what the first had just been given.
    """
    _, compiled = _compile_routes(columns, ((0, route),))
    return _apply_compiled_remap(row, compiled[0]) if compiled else False


def _frame_of(row: list[str]) -> int | None:
    """Read the frame number out of a data row's index column.

    ``None`` for a row whose index is not a frame number — a labeled-data export
    keys on an image path, and no correction can be matched to it.
    """
    if not row:
        return None
    try:
        return int(float(row[0]))
    except (TypeError, ValueError, OverflowError):
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
