"""Which calibration a recording uses: ``pose-3d/calibration_ref.txt``.

Many experiments share one rig and so one calibration. Copying a
``calibration.toml`` into each of them makes a dozen copies that must agree and
have no rule for which wins when they do not; so a session instead carries a
small text file naming the calibration it uses and the cameras it expects::

    # Sources required
    SideCam.mp4
    FrontCam.mp4
    FaceCam.mp4

    # 3d rotation matrix location
    "C:/rigs/rig2/calibration.toml"

Copied as it is into another experiment's ``pose-3d/`` folder, it works there
too, provided the videos are named the same.

**Parsing is by shape, not by position.** Comment lines start a section and are
otherwise ignored; the line that names a ``.toml`` is the calibration, and every
other line is a source. A quoted path wins over the rest of its line, so the
template's ``/path/to/calibration.toml or "C:/.../real.toml"`` resolves to the
quoted one. A relative path is taken from the reference file's own folder, which
is what lets a calibration kept beside it travel with the folder.

**Resolution order** is this file, then a ``calibration.toml`` in ``pose-3d/``,
then one in the session folder itself -- where anipose users keep it.
"""

from __future__ import annotations

import datetime as _datetime
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from avialsync.core.calibration import Calibration

__all__ = [
    "REF_NAME",
    "CALIBRATION_NAME",
    "POSE_3D_DIR",
    "CalibrationLink",
    "pose3d_dir_for",
    "read_ref",
    "write_ref",
    "keep_aside",
    "unused_name",
    "locate",
    "camera_names",
]

REF_NAME = "calibration_ref.txt"
CALIBRATION_NAME = "calibration.toml"
POSE_3D_DIR = "pose-3d"

_SOURCES_HEADER = "# Sources required"
_CALIBRATION_HEADER = "# 3d rotation matrix location"
_QUOTED = re.compile(r'"([^"]+)"')


@dataclass(frozen=True)
class CalibrationLink:
    """A calibration file, the videos it covers, and what named it."""

    calibration: Path
    #: Video file names, in the order the reference lists them. Empty for a
    #: calibration found by name rather than through a reference.
    sources: tuple[str, ...] = ()
    #: The ``calibration_ref.txt`` that pointed here, or None.
    ref_file: Path | None = None


def pose3d_dir_for(path: Path | str) -> Path:
    """Return the ``pose-3d`` folder that owns *path*.

    The nearest ancestor named ``pose-3d``; failing that, a ``pose-3d`` inside
    *path* when *path* is a folder (a session folder), else *path*'s own folder.
    """
    path = Path(path)
    for ancestor in (path, *path.parents):
        if ancestor.name.lower() == POSE_3D_DIR:
            return ancestor
    if path.is_dir():
        return path / POSE_3D_DIR
    return path.parent


def _parse_path(line: str, base: Path) -> Path:
    quoted = _QUOTED.findall(line)
    text = (quoted[-1] if quoted else line).strip()
    candidate = Path(text)
    # A reference travels between platforms with the folder: ``C:/rigs/...``
    # or ``\\server\share\...`` is absolute on Windows, and ``/rigs/...`` has
    # no drive there. Joining either onto this folder would report a path
    # nobody wrote (on Windows, ``/rigs`` would pick up the folder's ``C:``).
    if candidate.is_absolute() or PureWindowsPath(text).anchor:
        return candidate
    return base / candidate


def read_ref(path: Path | str) -> CalibrationLink | None:
    """Read a ``calibration_ref.txt``; None when it names no ``.toml``."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    sources: list[str] = []
    calibration: Path | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ".toml" in line.lower():
            calibration = _parse_path(line, path.parent)
        else:
            sources.append(line.strip('"'))
    if calibration is None:
        return None
    return CalibrationLink(calibration=calibration, sources=tuple(sources), ref_file=path)


def write_ref(folder: Path | str, sources: Sequence[str], calibration: Path | str) -> Path:
    """Write ``calibration_ref.txt`` in *folder*, creating the folder if needed.

    The folder is the ``pose-3d`` convention rather than a path the user typed,
    so creating it is not the typo-hiding D-100 forbids for export targets.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / REF_NAME
    lines = [_SOURCES_HEADER, *sources, "", _CALIBRATION_HEADER, f'"{Path(calibration)}"']
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


def keep_aside(folder: Path | str) -> Path | None:
    """Move an existing ``calibration_ref.txt`` aside under a dated name; where it went.

    Labs edit these by hand and copy them between experiments, so replacing
    one outright -- even one naming a file that no longer exists -- loses what
    it said. Renamed, not copied: the new file takes the name and the old one
    keeps its content. None when there was nothing to keep.
    """
    current = Path(folder) / REF_NAME
    if not current.exists():
        return None
    stamp = _datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = unused_name(Path(folder) / f"calibration_ref.{stamp}.txt")
    current.rename(target)
    return target


def unused_name(path: Path) -> Path:
    """*path*, or ``stem-2.suffix``, ``stem-3.suffix`` ... -- whichever does not exist yet."""
    candidate, index = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        index += 1
    return candidate


def locate(pose3d_dir: Path | str) -> CalibrationLink | None:
    """Find the calibration for the session owning *pose3d_dir*, or None.

    A reference whose ``.toml`` does not exist is still returned: the caller
    reports the broken link by name instead of silently asking again.
    """
    folder = Path(pose3d_dir)
    link = read_ref(folder / REF_NAME)
    if link is not None:
        return link
    for candidate in (folder / CALIBRATION_NAME, folder.parent / CALIBRATION_NAME):
        if candidate.is_file():
            return CalibrationLink(calibration=candidate)
    return None


def camera_names(
    calibration: Calibration, videos: Sequence[str], sources: Sequence[str] = ()
) -> dict[str, str]:
    """Map each video path to the calibration camera that filmed it.

    A camera named after the video's stem wins (``FaceCam.mp4`` -> ``FaceCam``),
    which is how a calibration fitted here names them. Otherwise the reference's
    source list is taken as the file's camera order -- anipose names cameras by
    a regex over file names, so ``A``/``B``/``C`` is common. A video matching
    neither is left out rather than guessed at.
    """
    names = calibration.names
    by_source = {name.lower(): i for i, name in enumerate(sources)}
    mapping: dict[str, str] = {}
    for video in videos:
        stem = Path(video).stem
        if stem in names:
            mapping[video] = stem
            continue
        index = by_source.get(Path(video).name.lower())
        if index is not None and index < len(names):
            mapping[video] = names[index]
    return mapping
