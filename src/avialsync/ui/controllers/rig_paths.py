"""Where a recording's pieces are: its cameras, its pose folder, the frame on screen.

Shared by the 3D-marker, calibration and wheel controllers (D-112, D-113),
which need the same four answers and must not each derive them their own way:
two opinions about "which frame is on screen" would key a marker and a wheel to
different frames for the same click (rule 6, one authority names the frame).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from avialsync.core import calibration_ref

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

__all__ = ["camera_name", "open_videos", "pose3d_dir", "pose_2d_file", "frame_at"]


def camera_name(video: str) -> str:
    """The name marker files and a fitted calibration give a video's camera."""
    return Path(video).stem


def open_videos(window: MainWindow) -> list[str]:
    """Every video with a pane, in pane order."""
    return list(window.video_grid.pane_paths())


def pose3d_dir(window: MainWindow) -> Path | None:
    """The recording's pose folder, shared by video-only and tracked imports."""
    videos = open_videos(window)
    video_root = _video_root(videos)
    if window._pose_3d_sources:
        source = Path(next(iter(window._pose_3d_sources)))
        owned = calibration_ref.pose3d_dir_for(source)
        if owned.name.lower() == calibration_ref.POSE_3D_DIR:
            return owned
        if video_root is None or source == video_root or video_root in source.parents:
            return (video_root or owned) / calibration_ref.POSE_3D_DIR
        return owned
    return video_root / calibration_ref.POSE_3D_DIR if video_root is not None else None


def _video_root(videos: list[str]) -> Path | None:
    """Nearest shared parent of the cameras, without inventing a filesystem root."""
    if not videos:
        return None
    first = Path(videos[0]).parent
    parents = [Path(video).parent for video in videos[1:]]
    for candidate in (first, *first.parents):
        if all(candidate == parent or candidate in parent.parents for parent in parents):
            return first if candidate == candidate.parent else candidate
    return first


def pose_2d_file(window: MainWindow, video: str) -> Path | None:
    """The 2D pose file drawn over *video* -- the ensemble when there are several."""
    entries = window._overlay_sources.get(video, {})
    for source_id, entry in entries.items():
        if entry.get("is_ensemble"):
            return Path(source_id)
    return Path(next(iter(entries))) if entries else None


def frame_at(window: MainWindow, t_master: float) -> int | None:
    """The video frame on screen at *t_master*, named by the first calibrated pane."""
    state = window._calibration_state
    videos = open_videos(window)
    ordered = [v for v in videos if state is not None and v in state.cameras] or videos
    if not ordered:
        return None
    pane = window.video_grid.panes[videos.index(ordered[0])]
    return int(pane.frame_record_at(t_master)[0])
