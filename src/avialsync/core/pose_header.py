"""Reading the multi-index header block of a DeepLabCut / LightningPose CSV.

Three places consume a pose CSV -- the loader, the corrected-copy exporter and
the calibration reader -- and all three need the same two answers: how many
header rows to skip, and what to call each column.  This is the one authority
for both (rule 15).

**Multi-animal files carry a fourth header row and repeat body-part names.**  A
maDLC export inserts ``individuals`` between ``scorer`` and ``bodyparts``, and
every animal then contributes its own ``snout``, ``leftEar``, ``tailBase``.  Any
reader that keys a column by body part alone maps both mice onto one set of
names and keeps whichever came last -- silently, with no parse error -- so a
correction made on one animal would be written into the other's columns.  The
point name therefore carries the individual: ``testMouse_snout`` and
``conSpecific_snout`` are two points, as they are in the recording.  DLC's
reserved ``single`` individual (arena corners and other unique parts) is
prefixed the same way, because one rule that always holds is worth more here
than a shorter name in one case.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from avialsync.core.pose import PosePoint, PoseSchema

__all__ = ["PoseHeader", "read_pose_header", "parse_pose_header"]

#: Row one's first cell, in every DLC and LightningPose export.
_SCORER = "scorer"
#: Row two's first cell in a multi-animal export, absent in a single-animal one.
_INDIVIDUALS = "individuals"
_BODYPARTS = "bodyparts"
_COORDS = "coords"
#: Stands in for a column the header leaves unnamed, so flattened names stay
#: distinct without ever colliding with a body part called the same thing.
_UNNAMED_PREFIX = "_unnamed_column_"


@dataclass(frozen=True)
class PoseHeader:
    """The parsed header block of one pose CSV.

    ``columns`` is per data column, positionally: ``columns[0]`` describes the
    index column and is ``("", "")``.  ``points`` and ``coords`` are the same
    information split, so callers that want one do not index the other.
    """

    #: How many lines the header occupies -- 3, or 4 when multi-animal.
    rows: int
    #: The header lines themselves, in file order, each already split on commas.
    lines: tuple[tuple[str, ...], ...]
    #: Per column, ``(point name, coordinate)``; the index column is ``("", "")``.
    columns: tuple[tuple[str, str], ...]
    #: Whether an ``individuals`` row was present (a multi-animal export).
    multi_animal: bool

    @property
    def points(self) -> tuple[str, ...]:
        """Per column, the point name -- ``individual_bodypart`` when present."""
        return tuple(point for point, _ in self.columns)

    @property
    def coords(self) -> tuple[str, ...]:
        """Per column, the coordinate: ``x``, ``y``, ``z``, ``likelihood``, ..."""
        return tuple(coord for _, coord in self.columns)

    def flat_names(self, index_name: str = "frame_index") -> list[str]:
        """Per column, ``point_coord`` -- the channel names the loader exposes.

        Column zero takes *index_name*; a column the header does not name takes
        a positional placeholder.  Every name is distinct, because a CSV reader
        given a duplicate column name either rejects the file or silently keeps
        one of the two.  :meth:`named_columns` is how a caller tells the
        placeholders apart from real points.
        """
        names = [index_name]
        for position, (point, coord) in enumerate(self.columns[1:], start=1):
            names.append(f"{point}_{coord}" if point else f"{_UNNAMED_PREFIX}{position}")
        return names

    def named_columns(self, index_name: str = "frame_index") -> list[str]:
        """The subset of :meth:`flat_names` that names an actual coordinate."""
        names = self.flat_names(index_name)
        return [
            name for position, name in enumerate(names) if position and self.columns[position][0]
        ]

    def pose_schema(self, *, frame_indexed: bool = True) -> PoseSchema:
        """Build the format-neutral schema this header describes (D-140).

        This module is the DeepLabCut/LightningPose *CSV* detail; `PoseSchema`
        is what every consumer reads, whatever the file was. A coordinate that
        is not an axis -- ``likelihood``, and the ensemble smoother's
        ``x_ens_var``, ``zscore``, ``nll``, ``x_posterior_var`` -- is reported
        as derived rather than silently becoming another channel to pyramid.
        """
        axes: dict[tuple[str, str], list[str]] = {}
        likelihood: set[tuple[str, str]] = set()
        derived: list[str] = []
        for position, (point, coord) in enumerate(self.columns):
            if position == 0 or not point:
                continue
            individual, bodypart = self._split_point(point)
            key = (individual, bodypart)
            lowered = coord.lower()
            if lowered in ("x", "y", "z"):
                axes.setdefault(key, []).append(lowered)
            elif lowered == "likelihood":
                axes.setdefault(key, [])
                likelihood.add(key)
            else:
                axes.setdefault(key, [])
                if coord not in derived:
                    derived.append(coord)

        points = tuple(
            PosePoint(
                individual=individual,
                bodypart=bodypart,
                axes=tuple(a for a in ("x", "y", "z") if a in found),
                has_likelihood=(individual, bodypart) in likelihood,
            )
            for (individual, bodypart), found in axes.items()
        )
        return PoseSchema(
            points=tuple(p for p in points if p.axes),
            frame_indexed=frame_indexed,
            derived=tuple(derived),
        )

    def _split_point(self, point: str) -> tuple[str, str]:
        """Recover ``(individual, bodypart)`` from a name this header built.

        Single-animal columns never carried an individual, so the whole name is
        the body part; a multi-animal one was joined here and splits back on the
        first separator, which is why the individual is joined as a prefix.
        """
        if not self.multi_animal:
            return "", point
        individual, separator, bodypart = point.partition("_")
        return (individual, bodypart) if separator else ("", point)

    def column_index(self) -> dict[tuple[str, str], int]:
        """Map ``(point name, coordinate)`` to its column position.

        Built from ``columns``, so the point names here are the same ones the
        loader named its channels after and a correction keyed by point name
        lands in that point's own columns.
        """
        return {
            (point, coord.lower()): position
            for position, (point, coord) in enumerate(self.columns)
            if point
        }


def parse_pose_header(lines: list[list[str]]) -> PoseHeader | None:
    """Parse an already-split header block, or ``None`` if it is not one.

    *lines* must hold at least the first four lines of the file; the fourth is
    only inspected to tell a multi-animal header from the first data row.
    """
    if len(lines) < 3:
        return None
    first = _cell(lines[0], 0)
    second = _cell(lines[1], 0)
    if first != _SCORER:
        return None

    if second == _INDIVIDUALS:
        if len(lines) < 4 or _cell(lines[2], 0) != _BODYPARTS or _cell(lines[3], 0) != _COORDS:
            return None
        individuals, bodyparts, coords = lines[1], lines[2], lines[3]
        rows = 4
        multi_animal = True
    elif second == _BODYPARTS:
        if _cell(lines[2], 0) != _COORDS:
            return None
        individuals, bodyparts, coords = [], lines[1], lines[2]
        rows = 3
        multi_animal = False
    else:
        return None

    width = min(len(bodyparts), len(coords))
    columns: list[tuple[str, str]] = [("", "")]
    for position in range(1, width):
        part = bodyparts[position].strip()
        coord = coords[position].strip()
        if not part or not coord:
            # A ragged column names nothing; it stays unnamed rather than
            # borrowing its neighbour's identity.
            columns.append(("", ""))
            continue
        if multi_animal:
            individual = _cell(individuals, position)
            point = f"{individual}_{part}" if individual else part
        else:
            point = part
        columns.append((point, coord))

    return PoseHeader(
        rows=rows,
        lines=tuple(tuple(line) for line in lines[:rows]),
        columns=tuple(columns),
        multi_animal=multi_animal,
    )


def read_pose_header(path: Path | str) -> PoseHeader | None:
    """Read *path*'s header block, or ``None`` if it is not a pose CSV.

    Never raises on a file that simply is not one: the callers use this to
    decide whether it is, and an unreadable file is not a pose file either.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            lines = [handle.readline() for _ in range(4)]
    except (OSError, UnicodeError):
        return None
    if not lines[0]:
        return None
    return parse_pose_header([line.rstrip("\r\n").split(",") for line in lines])


def _cell(row: list[str] | tuple[str, ...], position: int) -> str:
    """The stripped cell at *position*, or ``""`` past the end of the row."""
    return row[position].strip() if position < len(row) else ""
