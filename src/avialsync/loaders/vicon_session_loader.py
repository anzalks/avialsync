"""Discover Vicon Nexus trials and pair C3D markers with their video camera."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import av

from avialsync.core.errors import SourceOpenError
from avialsync.core.source import SessionItem, SessionLayout, SessionSource
from avialsync.loaders.vicon_c3d_loader import ViconC3DLoader, camera_from_xcp

logger = logging.getLogger(__name__)
_VIDEO_SUFFIXES = {".avi", ".mkv", ".mov", ".mp4", ".m4v"}


def _trial_files(path: Path) -> list[Path]:
    return sorted({*path.glob("*.c3d"), *path.glob("*/*.c3d")})


def _matching_video(c3d_path: Path, camera_id: str) -> list[Path]:
    prefix = f"{c3d_path.stem}.{camera_id}."
    return sorted(
        candidate
        for candidate in c3d_path.parent.glob(f"{prefix}*")
        if candidate.suffix.lower() in _VIDEO_SUFFIXES
    )


def _video_metadata(path: Path) -> tuple[float, int, int, int]:
    """Read the video header fields needed to sample pose on its frame grid."""
    try:
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            rate = stream.average_rate or stream.base_rate or stream.guessed_rate
            fps = float(rate) if rate is not None else 0.0
            return fps, int(stream.frames), int(stream.width), int(stream.height)
    except (av.FFmpegError, IndexError, OSError, TypeError, ValueError) as error:
        raise SourceOpenError(f"Could not inspect paired video {path.name}: {error}") from error


class ViconSessionSource(SessionSource):
    """Lay out Vicon C3D trajectories and their calibrated video recordings."""

    @classmethod
    def display_name(cls) -> str:
        return "Vicon Nexus Session"

    @classmethod
    def can_open(cls, path: Path) -> float:
        if not path.is_dir():
            return 0.0
        return (
            0.9
            if any(
                c3d_path.with_suffix(".xcp").is_file()
                and any(
                    candidate.suffix.lower() in _VIDEO_SUFFIXES
                    for candidate in c3d_path.parent.glob(f"{c3d_path.stem}.*")
                )
                for c3d_path in _trial_files(path)
            )
            else 0.0
        )

    def scan(self, path: Path, registry: Any) -> SessionLayout:
        items: list[SessionItem] = []
        warnings: list[str] = []
        for c3d_path in _trial_files(path):
            xcp_path = c3d_path.with_suffix(".xcp")
            if not xcp_path.is_file():
                warnings.append(f"{c3d_path.name} has no matching XCP camera calibration.")
                continue
            try:
                camera = camera_from_xcp(xcp_path)
            except SourceOpenError as error:
                warnings.append(str(error))
                continue

            videos = _matching_video(c3d_path, camera.name)
            if len(videos) != 1:
                state = "no" if not videos else "more than one"
                warnings.append(
                    f"{c3d_path.name} has {state} video matching calibrated camera {camera.name}."
                )
                continue
            video = videos[0]
            video_loader = registry.find_best_loader(video)
            if video_loader is None:
                warnings.append(f"No video loader is available for {video.name}.")
                continue
            try:
                fps, frame_count, width, height = _video_metadata(video)
            except SourceOpenError as error:
                warnings.append(str(error))
                continue
            if fps <= 0.0 or width <= 0 or height <= 0:
                warnings.append(f"{video.name} has no usable frame rate or image dimensions.")
                continue

            items.append(
                SessionItem(
                    path=video,
                    loader=video_loader,
                    label=f"{video.name} - video",
                )
            )
            items.append(
                SessionItem(
                    path=c3d_path,
                    loader=ViconC3DLoader,
                    config={
                        "xcp_path": str(xcp_path),
                        "camera_id": camera.name,
                        "fps": fps,
                        "frame_count": frame_count,
                        "video_width": width,
                        "video_height": height,
                        "role": "pose3d_overlay2d",
                        "overlay_video": str(video),
                        "overlay_camera": camera.name,
                        "overlay_label": "Vicon markers",
                    },
                    label=f"{c3d_path.name} - markers over {video.name}",
                )
            )

        if not items:
            warnings.append("No Vicon C3D trials could be paired with calibrated video.")
        logger.info("Vicon session: %d items from %s", len(items), path.name)
        return SessionLayout(items=items, warnings=warnings)
