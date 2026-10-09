"""Per-trial AOL camera recordings joined into one video per camera, back to back."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest

from avialsync.core.registry import LoaderRegistry
from avialsync.loaders.aol_camera_join import (
    AOLJoinedCameraSource,
    camera_folder_for,
    configure_camera_roots,
)
from avialsync.loaders.aol_microscope_session import AOLMicroscopeTrialSource
from avialsync.loaders.video_standard import VideoStandardLoader
from tests.test_aol_microscope_trial import _trial


def _camera(folder: Path, name: str, frames: int, period_ms: float, shade: int) -> Path:
    """An MJPEG AVI like the rig's, with its per-frame relative-times file."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.avi"
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mjpeg", rate=100)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuvj420p"
        # Both, or mux() rejects every packet (AGENTS.md known traps).
        stream.time_base = Fraction(1, 100)
        stream.codec_context.time_base = Fraction(1, 100)
        for index in range(frames):
            image = np.full((48, 64, 3), shade + index, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            frame.pts = index
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    rows = [f"{i + 1}\t{i * period_ms:.3f}\t03-09-2026;12:00:05.{i:04d}" for i in range(frames)]
    (folder / f"{name}-relative times.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _experiment(tmp_path: Path) -> tuple[Path, Path, Path]:
    experiment = tmp_path / "2026-09-03" / "experiment_1"
    experiment.mkdir(parents=True)
    first = _trial(experiment / "12-00-00")
    second = _trial(experiment / "12-10-00", start_ms=1_700_000_600_000)
    return experiment, first, second


def test_cameras_saved_in_the_trial_folders_join_back_to_back(tmp_path: Path) -> None:
    experiment, first, second = _experiment(tmp_path)
    # 10 ms frames for 50 ms: each overruns its trial, as an untriggered stop does.
    _camera(first, "FaceCam", 5, 10.0, 40)
    _camera(second, "FaceCam", 5, 10.0, 140)
    layout = AOLMicroscopeTrialSource().scan(experiment, LoaderRegistry(plugin_dirs=[]))
    cameras = [item for item in layout.items if item.loader is AOLJoinedCameraSource]
    assert len(cameras) == 1
    item = cameras[0]
    assert item.path == first / "FaceCam.avi" / "joined_trials"
    assert LoaderRegistry(plugin_dirs=[]).find_best_loader(item.path) is AOLJoinedCameraSource
    assert [s["start"] for s in item.config["segments"]] == pytest.approx([0.0, 0.029])

    loader = AOLJoinedCameraSource()
    loader.open(item.path, dict(item.config))
    assert loader.needs_conversion()
    joined = loader.prepare(lambda _fraction: None)
    mapping = loader.exact_time_mapping()
    assert mapping is not None
    master, _source = mapping
    # Trial 1 is 29 ms long on the joined timeline, trial 2 is 22 ms: later
    # frames are the camera running past its trial and are trimmed.
    np.testing.assert_allclose(master, [0.0, 0.01, 0.02, 0.029, 0.039, 0.049], atol=1e-9)
    assert joined.is_file() and not str(joined).startswith(str(tmp_path))
    assert loader._fps == pytest.approx(100.0)  # the camera's rate, not the container's

    built = joined.stat().st_mtime_ns
    again = AOLJoinedCameraSource()
    again.open(item.path, dict(item.config))
    assert again.prepare(lambda _fraction: None) == joined
    assert joined.stat().st_mtime_ns == built  # reused, not rebuilt


def test_a_single_trial_places_its_cameras_on_its_trigger(tmp_path: Path) -> None:
    _experiment_dir, first, _second = _experiment(tmp_path)
    _camera(first, "SideCam", 3, 10.0, 60)
    layout = AOLMicroscopeTrialSource().scan(first, None)
    cameras = [item for item in layout.items if item.loader is VideoStandardLoader]
    assert len(cameras) == 1
    assert cameras[0].path == first / "SideCam.avi"
    assert cameras[0].config["frame_timestamps_format"] == "aol_relative_ms"
    assert cameras[0].source_epoch == layout.session_epoch == 1_700_000_000.0


def test_cameras_are_found_under_the_camera_data_folder_by_trial_name(tmp_path: Path) -> None:
    experiment, first, second = _experiment(tmp_path)
    camera_root = tmp_path / "camera_pc"
    _camera(camera_root / "2026-09-03" / "experiment_1" / "12-00-00", "FaceCam", 3, 10.0, 40)
    _camera(camera_root / "2026-09-03" / "experiment_1" / "12-10-00", "FaceCam", 3, 10.0, 90)
    assert camera_folder_for(first) is None
    assert camera_folder_for(first, [camera_root]) == camera_root / first.relative_to(tmp_path)
    configure_camera_roots([camera_root])
    try:
        layout = AOLMicroscopeTrialSource().scan(experiment, None)
    finally:
        configure_camera_roots([])
    cameras = [item for item in layout.items if item.loader is AOLJoinedCameraSource]
    assert len(cameras) == 1 and len(cameras[0].config["segments"]) == 2
    assert second.name in cameras[0].config["segments"][1]["video"]
