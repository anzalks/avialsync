"""Fitting a missing ``calibration.toml`` from the session's own tracking.

Runs off the UI thread (rule 3): reading three pose CSVs and fitting three
cameras takes a few seconds. It is handed paths and plain numbers only, and
reads the pose files itself, so nothing the UI owns is touched from here.

The pairs are the anipose 3D pose and each camera's 2D tracking, joined on
frame number and body part -- the same observations anipose triangulated, run
backwards (see :mod:`avialsync.core.calibration` for what that can and cannot
recover).
"""

from __future__ import annotations

import datetime as _datetime
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core import calibration_ref
from avialsync.core.calibration import Calibration, fit_camera, write_calibration
from avialsync.core.errors import AvialSyncError, CalibrationError

logger = logging.getLogger(__name__)

__all__ = ["CameraFitInput", "CalibrationFitWorker"]

#: Only 2D points the tracker was sure of pair with the 3D pose; a low-confidence
#: detection is exactly the one anipose's triangulation leaned on least.
_MIN_LIKELIHOOD = 0.9


@dataclass(frozen=True)
class CameraFitInput:
    """One camera to fit: its name, its video's pixel size, its 2D tracking."""

    name: str
    size: tuple[int, int]
    pose_2d: Path


def _read_3d(path: Path) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Frame numbers and ``name -> (N, 3)`` from an anipose pose-3d CSV."""
    frame = pl.read_csv(path, infer_schema_length=0)
    names = [column[:-2] for column in frame.columns if column.endswith("_x")]
    names = [n for n in names if f"{n}_y" in frame.columns and f"{n}_z" in frame.columns]
    frames = (
        frame["fnum"].cast(pl.Float64, strict=False).to_numpy()
        if "fnum" in frame.columns
        else np.arange(frame.height, dtype=np.float64)
    )
    points = {
        name: np.column_stack(
            [
                frame[f"{name}_{axis}"].cast(pl.Float64, strict=False).to_numpy()
                for axis in ("x", "y", "z")
            ]
        )
        for name in names
    }
    return frames, points


def _read_2d(path: Path) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Frame numbers and ``name -> (N, 2)`` from a DLC / Lightning Pose CSV.

    Points below the likelihood floor are NaN, so they drop out of the join.
    """
    with open(path, encoding="utf-8") as handle:
        bodyparts = handle.readline().strip().split(",")  # scorer row, discarded
        bodyparts = handle.readline().strip().split(",")
        coords = handle.readline().strip().split(",")
    data = pl.read_csv(path, skip_rows=3, has_header=False, infer_schema_length=0)
    values = np.column_stack(
        [data[column].cast(pl.Float64, strict=False).to_numpy() for column in data.columns]
    )
    columns: dict[str, dict[str, int]] = {}
    for index in range(1, min(len(bodyparts), len(coords), values.shape[1])):
        columns.setdefault(bodyparts[index], {})[coords[index]] = index
    points: dict[str, np.ndarray] = {}
    for name, axes in columns.items():
        if "x" not in axes or "y" not in axes:
            continue
        xy = values[:, [axes["x"], axes["y"]]].copy()
        if "likelihood" in axes:
            xy[values[:, axes["likelihood"]] < _MIN_LIKELIHOOD] = np.nan
        points[name] = xy
    return values[:, 0], points


def _pairs(
    frames_3d: np.ndarray,
    world: dict[str, np.ndarray],
    frames_2d: np.ndarray,
    image: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    """Join the two files on frame number and body part."""
    row_2d = {int(f): i for i, f in enumerate(frames_2d) if np.isfinite(f)}
    rows_3d, rows_2d = [], []
    for i, f in enumerate(frames_3d):
        j = row_2d.get(int(f)) if np.isfinite(f) else None
        if j is not None:
            rows_3d.append(i)
            rows_2d.append(j)
    shared = sorted(set(world) & set(image))
    if not shared or not rows_3d:
        return np.empty((0, 3)), np.empty((0, 2))
    return (
        np.vstack([world[name][rows_3d] for name in shared]),
        np.vstack([image[name][rows_2d] for name in shared]),
    )


class CalibrationFitWorker(QObject):
    """Fit every camera, write ``calibration.toml`` and ``calibration_ref.txt``."""

    #: ``(calibration path, one-line summary per camera, where the previous
    #: calibration_ref.txt was kept -- "" when there was none)``
    finished = Signal(str, str, str)
    error = Signal(str)

    def __init__(
        self,
        pose_3d: Path,
        cameras: list[CameraFitInput],
        pose3d_dir: Path,
        sources: list[str],
    ) -> None:
        super().__init__()
        self._pose_3d = pose_3d
        self._cameras = cameras
        self._folder = pose3d_dir
        self._sources = sources

    @Slot()
    def run(self) -> None:
        try:
            frames_3d, world = _read_3d(self._pose_3d)
            fitted = []
            summary = []
            for camera in self._cameras:
                frames_2d, image = _read_2d(camera.pose_2d)
                points_3d, points_2d = _pairs(frames_3d, world, frames_2d, image)
                model, error = fit_camera(camera.name, camera.size, points_3d, points_2d)
                fitted.append((model, error))
                summary.append(f"{camera.name}: {error:.1f} px")
            if len(fitted) < 2:
                raise CalibrationError("At least two cameras with 2D tracking are needed.")
            calibration = Calibration(
                cameras=tuple(model for model, _ in fitted),
                metadata={
                    "adjusted": False,
                    "error": float(np.mean([error for _, error in fitted])),
                    "fitted_by": "avialsync",
                    "fitted_from": self._pose_3d.name,
                    "fitted_at": _datetime.datetime.now(_datetime.UTC).isoformat(
                        timespec="seconds"
                    ),
                },
            )
            self._folder.mkdir(parents=True, exist_ok=True)
            target = self._folder / calibration_ref.CALIBRATION_NAME
            if target.exists():
                # Never over a calibration someone else made -- nor over an
                # earlier fit: each fit gets a name of its own.
                target = calibration_ref.unused_name(self._folder / "calibration_fitted.toml")
            write_calibration(target, calibration)
            kept = calibration_ref.keep_aside(self._folder)
            calibration_ref.write_ref(self._folder, self._sources, target)
            self.finished.emit(str(target), "; ".join(summary), str(kept) if kept else "")
        except (AvialSyncError, OSError, ValueError, pl.exceptions.PolarsError) as error:
            logger.warning("Calibration fit failed", exc_info=True)
            self.error.emit(str(error))
