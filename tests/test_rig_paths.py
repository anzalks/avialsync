"""Rig path decisions work with a narrow context, without a MainWindow."""

from pathlib import Path

from avialsync.ui.controllers.rig_paths import (
    RigPathsContext,
    frame_at,
    pose3d_dir,
    pose_2d_file,
)


def test_rig_paths_uses_declared_sources_and_calibrated_video(tmp_path: Path) -> None:
    """A small context supplies all facts needed for path and frame choices."""
    front = str(tmp_path / "front.avi")
    side = str(tmp_path / "side.avi")
    pose = str(tmp_path / "pose-3d" / "markers.csv")
    tracker = str(tmp_path / "front.csv")
    ensemble = str(tmp_path / "front-ensemble.csv")
    sampled: list[tuple[int, float]] = []

    def frame_index(index: int, time: float) -> int:
        sampled.append((index, time))
        return 17

    context = RigPathsContext(
        video_paths=lambda: [front, side],
        pose_sources={pose: object()},
        overlays={front: {tracker: {}, ensemble: {"is_ensemble": True}}},
        calibrated_videos=lambda: {side},
        frame_index=frame_index,
    )

    assert pose3d_dir(context) == tmp_path / "pose-3d"
    assert pose_2d_file(context, front) == Path(ensemble)
    assert frame_at(context, 1.25) == 17
    assert sampled == [(1, 1.25)]
