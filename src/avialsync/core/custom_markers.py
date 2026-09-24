"""Hand-placed 3D markers: one point clicked in every camera, triangulated.

A pose model tracks the body parts it was trained on. A user often needs one
more -- a landmark on the rig, a point the model never learned -- and until now
had to retrain to get it. A custom marker is that point, placed by hand on the
current frame in each camera view and triangulated with the rig's calibration
(:mod:`avialsync.core.calibration`) into the same frame as the anipose pose.

A marker exists on **one frame**: the one it was placed on. Carrying it across
frames (and interpolating between them) is a later step, and nothing here
assumes it will not come.

**Never written into a pose file.** Like a Fix Tracker correction (D-099), a
marker lives in files of its own beside the data it extends, which this module
reads and writes:

* ``<Camera>_eks.custom_markers.csv`` beside each camera's 2D pose file, in
  DeepLabCut's three-header-row layout -- the clicks, per camera;
* ``_eks.custom_markers.csv`` beside the 3D pose file, in anipose's layout --
  the triangulated result, with ``_error`` and ``_ncams`` as anipose writes them.

The 2D files are the authority: they are what the user did. The 3D file is
derived from them and rewritten whenever they change.

This module is headless (architecture rule 2): observers are plain callables.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import logging
import math
import os
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "MARKER_SUFFIX",
    "CustomMarker",
    "CustomMarkerStore",
    "marker_file_for",
    "is_custom_marker_path",
    "write_2d",
    "read_2d",
    "write_3d",
    "read_3d",
]

#: Replaces the pose file's ``.csv``: ``FaceCam_eks.csv`` ->
#: ``FaceCam_eks.custom_markers.csv``, the name the lab asked for.
MARKER_SUFFIX = ".custom_markers.csv"

#: DLC keys a column set by scorer; this one says a person placed the points.
SCORER = "avialsync_custom"


@dataclasses.dataclass(frozen=True)
class CustomMarker:
    """One named marker on one frame, as placed and as triangulated.

    ``views`` holds ``(camera, x, y)`` per camera it was placed in, sorted by
    camera so two equal markers compare equal. ``xyz`` and ``error`` are None
    until it has been triangulated.
    """

    name: str
    frame: int
    views: tuple[tuple[str, float, float], ...] = ()
    xyz: tuple[float, float, float] | None = None
    error: float | None = None

    @property
    def key(self) -> tuple[str, int]:
        """The identity the store files it under."""
        return (self.name, self.frame)

    @property
    def cameras(self) -> tuple[str, ...]:
        """Cameras this marker has been placed in."""
        return tuple(view[0] for view in self.views)

    def view(self, camera: str) -> tuple[float, float] | None:
        """Where the marker sits in *camera*, in that video's pixels."""
        for name, x, y in self.views:
            if name == camera:
                return (x, y)
        return None

    def with_view(self, camera: str, x: float, y: float) -> CustomMarker:
        """A copy placed at *(x, y)* in *camera*; the 3D result is dropped."""
        views = {name: (vx, vy) for name, vx, vy in self.views}
        views[camera] = (float(x), float(y))
        return dataclasses.replace(
            self,
            views=tuple((name, *views[name]) for name in sorted(views)),
            xyz=None,
            error=None,
        )


class CustomMarkerStore:
    """Every custom marker in the session, keyed by ``(name, frame)``.

    Observers are told the key that changed, or None for a bulk load -- the
    same contract as :class:`~avialsync.core.point_edits.PointEditStore`, and
    for the same reason: persistence hangs off the mutation, not off this.
    """

    def __init__(self) -> None:
        self._markers: dict[tuple[str, int], CustomMarker] = {}
        self._observers: list[Callable[[tuple[str, int] | None], None]] = []

    def __len__(self) -> int:
        return len(self._markers)

    def __iter__(self) -> Iterator[CustomMarker]:
        return iter(list(self._markers.values()))

    def get(self, name: str, frame: int) -> CustomMarker | None:
        """The marker called *name* on *frame*, or None."""
        return self._markers.get((name, int(frame)))

    def at_frame(self, frame: int) -> list[CustomMarker]:
        """Every marker placed on *frame*, sorted by name."""
        return sorted(
            (m for m in self._markers.values() if m.frame == int(frame)), key=lambda m: m.name
        )

    def names(self) -> set[str]:
        """Every marker name in use, on any frame."""
        return {name for name, _ in self._markers}

    def set(self, name: str, frame: int, marker: CustomMarker | None) -> bool:
        """Store *marker* under ``(name, frame)``, or remove it when None.

        Returns whether anything changed, so a no-op does not push an undo
        entry or rewrite a file.
        """
        key = (name, int(frame))
        if marker is None:
            if key not in self._markers:
                return False
            del self._markers[key]
        else:
            if self._markers.get(key) == marker:
                return False
            self._markers[key] = marker
        self._notify(key)
        return True

    def load(self, markers: Iterable[CustomMarker]) -> None:
        """Replace everything with *markers*, as read back from disk."""
        self._markers = {marker.key: marker for marker in markers}
        self._notify(None)

    def clear(self) -> None:
        """Forget every marker (a new session)."""
        if self._markers:
            self._markers.clear()
            self._notify(None)

    def observe(self, callback: Callable[[tuple[str, int] | None], None]) -> Callable[[], None]:
        """Call *callback* after every change; returns a disposer."""
        self._observers.append(callback)

        def _dispose() -> None:
            if callback in self._observers:
                self._observers.remove(callback)

        return _dispose

    def _notify(self, key: tuple[str, int] | None) -> None:
        for callback in list(self._observers):
            callback(key)


# ── files ────────────────────────────────────────────────────────────


def marker_file_for(pose_file: Path | str) -> Path:
    """The custom-marker file that sits beside *pose_file*."""
    path = Path(pose_file)
    return path.with_name(path.stem + MARKER_SUFFIX)


def is_custom_marker_path(path: Path | str) -> bool:
    """Whether *path* is one of our own marker files.

    Drop scanning, format sniffing, and the AOL manifest consult this: the files
    are pose-shaped CSVs, and ``_eks.custom_markers.csv`` even matches the
    ``*_eks*.csv`` glob that finds 3D pose, so without it our own output would
    be offered back as data.
    """
    return Path(path).name.lower().endswith(MARKER_SUFFIX)


def _atomic_write(target: Path, rows: list[list[str]]) -> Path:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(buffer.getvalue(), encoding="utf-8")
    os.replace(temporary, target)
    return target


def _number(value: float | None) -> str:
    return "" if value is None or not math.isfinite(value) else repr(float(value))


def _ordered_names(markers: Iterable[CustomMarker]) -> list[str]:
    return sorted({marker.name for marker in markers})


def write_2d(target: Path | str, camera: str, markers: Iterable[CustomMarker]) -> Path:
    """Write every marker placed in *camera* as a DeepLabCut-layout CSV.

    One row per frame holding any marker; a marker absent from a frame is an
    empty cell, never ``0,0`` (see :mod:`avialsync.core.dlc_export`). The
    likelihood is 1.0: a person put it there. A file with no markers keeps its
    three header rows, rather than being deleted -- nothing here removes a file
    from a data folder.
    """
    placed = [m for m in markers if m.view(camera) is not None]
    names = _ordered_names(placed)
    rows = [
        ["scorer"] + [SCORER] * (3 * len(names)),
        ["bodyparts"] + [name for name in names for _ in range(3)],
        ["coords"] + ["x", "y", "likelihood"] * len(names),
    ]
    by_frame: dict[int, dict[str, tuple[float, float]]] = {}
    for marker in placed:
        view = marker.view(camera)
        if view is not None:
            by_frame.setdefault(marker.frame, {})[marker.name] = view
    for frame in sorted(by_frame):
        row = [str(frame)]
        for name in names:
            view = by_frame[frame].get(name)
            row += ["", "", ""] if view is None else [_number(view[0]), _number(view[1]), "1.0"]
        rows.append(row)
    return _atomic_write(Path(target), rows)


def read_2d(source: Path | str) -> dict[tuple[str, int], tuple[float, float]]:
    """Read a file :func:`write_2d` wrote: ``(name, frame) -> (x, y)``.

    A missing file is an empty result; an unreadable row is skipped and logged,
    so one damaged line does not cost the rest (AGENTS rule 10).
    """
    path = Path(source)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError):
        logger.warning("Could not read custom markers at %s", path, exc_info=True)
        return {}
    records = list(csv.reader(lines))
    if len(records) < 3:
        return {}
    bodyparts, coords = records[1], records[2]
    columns: dict[str, dict[str, int]] = {}
    for index in range(1, min(len(bodyparts), len(coords))):
        columns.setdefault(bodyparts[index], {})[coords[index]] = index
    result: dict[tuple[str, int], tuple[float, float]] = {}
    for record in records[3:]:
        try:
            frame = int(float(record[0]))
        except (IndexError, ValueError):
            logger.warning("Skipping unreadable custom-marker row in %s", path.name)
            continue
        for name, axes in columns.items():
            try:
                x = record[axes["x"]]
                y = record[axes["y"]]
            except (KeyError, IndexError):
                continue
            if x and y:
                try:
                    result[(name, frame)] = (float(x), float(y))
                except ValueError:
                    logger.warning("Skipping unreadable %s at frame %d", name, frame)
    return result


_IDENTITY_TRANSFORM = [f"M_{i}{j}" for i in range(3) for j in range(3)] + [
    f"center_{i}" for i in range(3)
]
_IDENTITY_VALUES = ["1.0" if i == j else "0.0" for i in range(3) for j in range(3)] + ["0.0"] * 3


def write_3d(target: Path | str, markers: Iterable[CustomMarker]) -> Path:
    """Write triangulated markers in anipose's ``pose-3d`` CSV layout.

    ``<name>_x/_y/_z/_error/_ncams/_score`` per marker, anipose's identity
    ``M_ij``/``center_i`` (a hand-placed point is already in the calibration's
    frame), and ``fnum``. One row per frame holding any triangulated marker.
    """
    solved = [m for m in markers if m.xyz is not None]
    names = _ordered_names(solved)
    header = [
        f"{name}_{field}" for name in names for field in ("x", "y", "z", "error", "ncams", "score")
    ]
    rows = [header + _IDENTITY_TRANSFORM + ["fnum"]]
    by_frame: dict[int, dict[str, CustomMarker]] = {}
    for marker in solved:
        by_frame.setdefault(marker.frame, {})[marker.name] = marker
    for frame in sorted(by_frame):
        row: list[str] = []
        for name in names:
            entry = by_frame[frame].get(name)
            if entry is None or entry.xyz is None:
                row += [""] * 6
            else:
                row += [_number(v) for v in entry.xyz]
                row += [_number(entry.error), str(len(entry.views)), "1.0"]
        rows.append(row + _IDENTITY_VALUES + [str(frame)])
    return _atomic_write(Path(target), rows)


def read_3d(
    source: Path | str,
) -> dict[tuple[str, int], tuple[tuple[float, float, float], float | None]]:
    """Read a file :func:`write_3d` wrote: ``(name, frame) -> (xyz, error)``."""
    path = Path(source)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError):
        logger.warning("Could not read custom markers at %s", path, exc_info=True)
        return {}
    result: dict[tuple[str, int], tuple[tuple[float, float, float], float | None]] = {}
    reader = csv.DictReader(text.splitlines())
    names = sorted({field[:-2] for field in (reader.fieldnames or []) if field.endswith("_x")})
    for record in reader:
        try:
            frame = int(float(record["fnum"]))
        except (KeyError, TypeError, ValueError):
            continue
        for name in names:
            try:
                xyz = (
                    float(record[f"{name}_x"]),
                    float(record[f"{name}_y"]),
                    float(record[f"{name}_z"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            raw_error = record.get(f"{name}_error") or ""
            try:
                error: float | None = float(raw_error) if raw_error else None
            except ValueError:
                error = None
            result[(name, frame)] = (xyz, error)
    return result
