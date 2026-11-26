"""Writing a calibrated 3D-to-2D reprojected pose CSV per camera.

When a camera already has a 2D DeepLabCut or Lightning Pose CSV, its header
block, ``scorer``, ``frame_index``, ``likelihood``, extra smoother columns, and
2D-only landmarks are preserved verbatim; only matched ``(point, x)`` and
``(point, y)`` cells are replaced with the calibrated 3D reprojection so
downstream analysis pipelines run unchanged after swapping the filename.  When a
calibrated camera has no 2D CSV on disk, a standard DLC-layout CSV is written on
the camera's frame grid.

Provenance is written out-of-band to the companion ``.json`` sidecar rather than
renaming row zero's ``scorer``, keeping strict scorer-indexed readers unbroken.
"""

from __future__ import annotations

import csv
import itertools
import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from avialsync.core.artifact_io import publish
from avialsync.core.artifact_provenance import record, write_companion
from avialsync.core.calibration import CameraModel
from avialsync.core.pose_header import PoseHeader, parse_pose_header

__all__ = [
    "REPROJECTED_SCORER",
    "REPROJECTED_SUFFIX",
    "ReprojectedCopyReport",
    "is_reprojected_pose_path",
    "match_3d_to_2d_names",
    "project_frames_to_camera",
    "reprojected_copy_path",
    "write_reprojected_copy",
    "write_reprojected_csv",
]

REPROJECTED_SUFFIX = "_reprojected.csv"
REPROJECTED_SCORER = "avialsync_reprojected"
_MIN_HEADER_ROWS = 3


@dataclass(frozen=True)
class ReprojectedCopyReport:
    """Summary of a written 3D-to-2D reprojected pose CSV."""

    rows: int = 0
    projected_rows: int = 0
    projected_points: int = 0
    cleared_points: int = 0


def reprojected_copy_path(source: Path | str) -> Path:
    """Return the default ``*_reprojected.csv`` destination beside *source*."""
    path = Path(source)
    return path.with_name(f"{path.stem}{REPROJECTED_SUFFIX}")


def is_reprojected_pose_path(path: Path | str) -> bool:
    """Return whether *path* is an AvialSync-exported reprojected 2D pose CSV."""
    return Path(path).name.lower().endswith(REPROJECTED_SUFFIX)


def match_3d_to_2d_names(
    names_3d: Sequence[str],
    names_2d: Sequence[str],
) -> dict[str, str]:
    """Map each unambiguous 2D point name to its 3D point name."""
    exact = {name: name for name in names_3d if name}
    lowered: dict[str, list[str]] = {}
    for name in names_3d:
        if name:
            lowered.setdefault(name.lower(), []).append(name)

    matched: dict[str, str] = {}
    for name_2d in names_2d:
        if not name_2d:
            continue
        resolved = _match_one_name(name_2d, exact, lowered, names_3d)
        if resolved is not None:
            matched[name_2d] = resolved
    return matched


def _match_one_name(
    name_2d: str,
    exact: dict[str, str],
    lowered: dict[str, list[str]],
    names_3d: Sequence[str],
) -> str | None:
    if name_2d in exact:
        return exact[name_2d]
    key = name_2d.lower().strip()
    by_case = lowered.get(key, [])
    if len(by_case) == 1:
        return by_case[0]
    if by_case:
        return None
    suffix_hits = [
        candidate
        for candidate in names_3d
        if candidate
        and (candidate.lower().endswith(f"_{key}") or key.endswith(f"_{candidate.lower()}"))
    ]
    return suffix_hits[0] if len(suffix_hits) == 1 else None


def project_frames_to_camera(
    camera: CameraModel,
    world_xyz: Mapping[str, np.ndarray],
) -> dict[str, np.ndarray]:
    """Project per-frame ``(N, 3)`` world trajectories into *camera* pixels."""
    z_axis = camera.rotation_matrix()[2]
    tz = float(camera.translation[2])
    projected: dict[str, np.ndarray] = {}
    for name, raw in world_xyz.items():
        coords = np.asarray(raw, dtype=np.float64).reshape(-1, 3)
        pixels = np.full((len(coords), 2), np.nan, dtype=np.float64)
        finite = np.all(np.isfinite(coords), axis=1)
        if np.any(finite):
            valid_xyz = coords[finite]
            in_front = (valid_xyz @ z_axis + tz) > 0.0
            if np.any(in_front):
                keep_indices = np.flatnonzero(finite)[in_front]
                pixels[keep_indices] = camera.project(valid_xyz[in_front])
        projected[name] = pixels
    return projected


def write_reprojected_copy(
    source: Path | str,
    target: Path | str,
    projected: Mapping[str, np.ndarray],
    *,
    sources: tuple[Path | str, ...] = (),
    session: Path | None = None,
) -> ReprojectedCopyReport:
    """Clone *source* to *target*, replacing matched ``x``/``y`` cells with *projected*."""
    source_path = Path(source)
    target_path = Path(target)
    if source_path.resolve() == target_path.resolve():
        raise ValueError("The reprojected copy must have a different path from the recording.")

    provenance_sources = tuple(dict.fromkeys((source_path, *(Path(s) for s in sources))))
    with open(source_path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        peeked = list(itertools.islice(reader, _MIN_HEADER_ROWS + 1))
        header_block = parse_pose_header(peeked)
        if header_block is None:
            raise ValueError(
                f"{source_path.name} has no DeepLabCut or LightningPose header block; "
                "its first rows are not scorer/[individuals/]bodyparts/coords."
            )
        targets = _target_columns(header_block, projected)
        header = [list(line) for line in header_block.lines]
        rows = itertools.chain(peeked[header_block.rows :], reader)
        result: list[ReprojectedCopyReport] = []

        def write(temporary: Path) -> None:
            result.append(_stream_copy(rows, temporary, header, targets))

        publish(target_path, write, kind="reprojected-pose", sources=provenance_sources)
        report = result[0]

    _write_provenance(target_path, provenance_sources, session, report)
    return report


def _target_columns(
    header_block: PoseHeader,
    projected: Mapping[str, np.ndarray],
) -> list[tuple[int, int, np.ndarray]]:
    columns = header_block.column_index()
    ordered_2d = list(dict.fromkeys(point for point, _coord in header_block.columns if point))
    matched = match_3d_to_2d_names(tuple(projected), ordered_2d)
    targets: list[tuple[int, int, np.ndarray]] = []
    for point_2d, point_3d in matched.items():
        x_col = columns.get((point_2d, "x"))
        y_col = columns.get((point_2d, "y"))
        if x_col is not None and y_col is not None:
            targets.append((x_col, y_col, np.asarray(projected[point_3d], dtype=np.float64)))
    return targets


def _stream_copy(
    reader: Iterator[list[str]],
    temporary: Path,
    header: list[list[str]],
    targets: list[tuple[int, int, np.ndarray]],
) -> ReprojectedCopyReport:
    rows = 0
    projected_rows = 0
    projected_points = 0
    cleared_points = 0
    with open(temporary, "w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        for line in header:
            writer.writerow(line)
        for row in reader:
            rows += 1
            frame = _frame_of(row)
            if frame is not None and frame >= 0 and targets:
                p_pts, c_pts = _replace_row_xy(row, frame, targets)
                projected_points += p_pts
                cleared_points += c_pts
                if p_pts:
                    projected_rows += 1
            writer.writerow(row)
    return ReprojectedCopyReport(
        rows=rows,
        projected_rows=projected_rows,
        projected_points=projected_points,
        cleared_points=cleared_points,
    )


def _replace_row_xy(
    row: list[str],
    frame: int,
    targets: list[tuple[int, int, np.ndarray]],
) -> tuple[int, int]:
    written = 0
    cleared = 0
    row_len = len(row)
    for x_col, y_col, xy in targets:
        if x_col >= row_len or y_col >= row_len:
            continue
        if frame < len(xy):
            px, py = float(xy[frame, 0]), float(xy[frame, 1])
            if math.isfinite(px) and math.isfinite(py):
                row[x_col] = repr(px)
                row[y_col] = repr(py)
                written += 1
                continue
        row[x_col] = ""
        row[y_col] = ""
        cleared += 1
    return written, cleared


def _frame_of(row: list[str]) -> int | None:
    if not row:
        return None
    try:
        return int(float(row[0]))
    except (ValueError, OverflowError):
        return None


def write_reprojected_csv(
    target: Path | str,
    bodyparts: Sequence[str],
    projected: Mapping[str, np.ndarray],
    *,
    frame_count: int,
    scorer: str = REPROJECTED_SCORER,
    point_labels: Mapping[str, tuple[str, str]] | None = None,
    sources: tuple[Path | str, ...] = (),
    session: Path | None = None,
) -> ReprojectedCopyReport:
    """Write a standalone DLC-layout reprojected CSV when no 2D CSV exists."""
    target_path = Path(target)
    provenance_sources = tuple(dict.fromkeys(Path(s) for s in sources))
    header = _standalone_header(bodyparts, scorer, point_labels)
    arrays = [np.asarray(projected[part], dtype=np.float64) for part in bodyparts]
    result: list[ReprojectedCopyReport] = []

    def write(temporary: Path) -> None:
        result.append(_stream_standalone(temporary, header, arrays, max(0, int(frame_count))))

    publish(target_path, write, kind="reprojected-pose", sources=provenance_sources)
    report = result[0]
    _write_provenance(target_path, provenance_sources, session, report)
    return report


def _standalone_header(
    bodyparts: Sequence[str],
    scorer: str,
    point_labels: Mapping[str, tuple[str, str]] | None,
) -> list[list[str]]:
    width = 3 * len(bodyparts)
    if point_labels is not None:
        individuals: list[str] = ["individuals"]
        parts: list[str] = ["bodyparts"]
        for name in bodyparts:
            individual, bodypart = point_labels[name]
            individuals.extend([individual] * 3)
            parts.extend([bodypart] * 3)
        return [
            ["scorer"] + [scorer] * width,
            individuals,
            parts,
            ["coords"] + ["x", "y", "likelihood"] * len(bodyparts),
        ]
    return [
        ["scorer"] + [scorer] * width,
        ["bodyparts"] + [name for name in bodyparts for _ in range(3)],
        ["coords"] + ["x", "y", "likelihood"] * len(bodyparts),
    ]


def _stream_standalone(
    temporary: Path,
    header: list[list[str]],
    arrays: list[np.ndarray],
    frame_count: int,
) -> ReprojectedCopyReport:
    projected_rows = 0
    projected_points = 0
    cleared_points = 0
    with open(temporary, "w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        for line in header:
            writer.writerow(line)
        for frame in range(frame_count):
            row = [str(frame)]
            row_written = 0
            for xy in arrays:
                if frame < len(xy):
                    px, py = float(xy[frame, 0]), float(xy[frame, 1])
                    if math.isfinite(px) and math.isfinite(py):
                        row.extend([repr(px), repr(py), "1.0"])
                        row_written += 1
                        continue
                row.extend(["", "", ""])
                cleared_points += 1
            projected_points += row_written
            if row_written:
                projected_rows += 1
            writer.writerow(row)
    return ReprojectedCopyReport(
        rows=frame_count,
        projected_rows=projected_rows,
        projected_points=projected_points,
        cleared_points=cleared_points,
    )


def _write_provenance(
    target_path: Path,
    sources: tuple[Path, ...],
    session: Path | None,
    report: ReprojectedCopyReport,
) -> None:
    write_companion(
        target_path,
        record(
            "reprojected-pose",
            sources,
            session=session,
            edit_counts={
                "rows": report.rows,
                "projected_rows": report.projected_rows,
                "projected_points": report.projected_points,
                "cleared_points": report.cleared_points,
            },
        ),
        sources=sources,
    )
