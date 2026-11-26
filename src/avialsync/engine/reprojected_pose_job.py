"""Worker job that projects calibrated 3D pose trajectories onto a camera's frames."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from avialsync.core import reprojected_pose_export
from avialsync.core.calibration import CameraModel
from avialsync.core.errors import ExportError
from avialsync.core.timeline import TimeMap
from avialsync.engine.export_worker import ReaderReference, _close_reader

__all__ = ["ReprojectedPoseJob", "run_reprojected_pose_job"]

_SAMPLE_TOLERANCE_S = 0.1


@dataclass(frozen=True)
class ReprojectedPoseJob:
    """Plain-data snapshot for writing one camera's reprojected 2D pose CSV."""

    target: Path
    video: Path
    camera: CameraModel
    pose_3d_source: Path
    calibration_path: Path
    axes: Mapping[str, tuple[ReaderReference, ReaderReference, ReaderReference]]
    video_time_map: TimeMap = field(default_factory=TimeMap)
    template_2d: Path | None = None
    frame_times: np.ndarray | None = None
    point_labels: dict[str, tuple[str, str]] | None = None
    session: Path | None = None


def run_reprojected_pose_job(
    job: ReprojectedPoseJob,
    *,
    should_cancel: Callable[[], bool] | None = None,
) -> str:
    """Sample 3D pose on *job.video*'s frame grid, project, and write CSV."""
    frame_times = _resolve_frame_times(job)
    master_times = job.video_time_map.to_master_array(frame_times)
    world_xyz = _sample_world_points(job.axes, master_times, should_cancel=should_cancel)
    projected = reprojected_pose_export.project_frames_to_camera(job.camera, world_xyz)
    sources = _provenance_sources(job)
    if job.template_2d is not None and job.template_2d.is_file():
        report = reprojected_pose_export.write_reprojected_copy(
            job.template_2d,
            job.target,
            projected,
            sources=sources,
            session=job.session,
        )
    else:
        report = reprojected_pose_export.write_reprojected_csv(
            job.target,
            tuple(job.axes),
            projected,
            frame_count=len(frame_times),
            point_labels=job.point_labels,
            sources=sources,
            session=job.session,
        )
    return (
        f"{report.projected_points} reprojected point(s) in "
        f"{report.rows} row(s) → {job.target.name}"
    )


def _resolve_frame_times(job: ReprojectedPoseJob) -> np.ndarray:
    if job.frame_times is not None:
        return np.asarray(job.frame_times, dtype=np.float64)
    if not job.video.is_file():
        raise ExportError(f"The video {job.video.name} is unavailable.")
    from avialsync.engine.pyav_reader import PyAVReader

    with PyAVReader(job.video) as reader:
        return np.asarray(reader.frame_times, dtype=np.float64).copy()


def _sample_world_points(
    axes: Mapping[str, tuple[ReaderReference, ReaderReference, ReaderReference]],
    master_times: np.ndarray,
    *,
    should_cancel: Callable[[], bool] | None,
) -> dict[str, np.ndarray]:
    world_xyz: dict[str, np.ndarray] = {}
    for name, refs in axes.items():
        if should_cancel is not None and should_cancel():
            raise ExportError("Reprojected pose export was cancelled.")
        world_xyz[name] = _sample_one_point(refs, master_times)
    return world_xyz


def _sample_one_point(
    refs: tuple[ReaderReference, ReaderReference, ReaderReference],
    master_times: np.ndarray,
) -> np.ndarray:
    rx = refs[0].open()
    ry = refs[1].open()
    rz = refs[2].open()
    try:
        times, vx, gx = rx.source_reader.mapped_columns()
        _, vy, gy = ry.source_reader.mapped_columns()
        _, vz, gz = rz.source_reader.mapped_columns()
        coords = np.full((len(master_times), 3), np.nan, dtype=np.float64)
        if len(times) == 0 or len(master_times) == 0:
            return coords
        target = rx.time_map.to_source_array(master_times)
        in_bounds = (target >= float(times[0]) - _SAMPLE_TOLERANCE_S) & (
            target <= float(times[-1]) + _SAMPLE_TOLERANCE_S
        )
        idx = np.clip(np.searchsorted(times, target + 1e-6, side="right") - 1, 0, len(times) - 1)
        sample_t = np.asarray(times[idx], dtype=np.float64)
        gap_at = (
            np.asarray(gx[idx], dtype=bool)
            | np.asarray(gy[idx], dtype=bool)
            | np.asarray(gz[idx], dtype=bool)
        )
        prev = np.maximum(idx - 1, 0)
        gap_prev = (
            np.asarray(gx[prev], dtype=bool)
            | np.asarray(gy[prev], dtype=bool)
            | np.asarray(gz[prev], dtype=bool)
        )
        crossed = ((target > sample_t) & gap_at) | ((idx > 0) & (target < sample_t) & gap_prev)
        valid = in_bounds & (~crossed)
        if np.any(valid):
            v_idx = idx[valid]
            coords[valid, 0] = np.asarray(vx[v_idx], dtype=np.float64)
            coords[valid, 1] = np.asarray(vy[v_idx], dtype=np.float64)
            coords[valid, 2] = np.asarray(vz[v_idx], dtype=np.float64)
        return coords
    finally:
        _close_reader(rx)
        _close_reader(ry)
        _close_reader(rz)


def _provenance_sources(job: ReprojectedPoseJob) -> tuple[Path, ...]:
    candidates = [job.pose_3d_source, job.calibration_path]
    if job.template_2d is not None:
        candidates.insert(0, job.template_2d)
    return tuple(dict.fromkeys(p for p in candidates if str(p)))
