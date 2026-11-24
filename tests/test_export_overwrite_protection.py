"""Regression tests for export/proxy file-overwrite protection and joined-camera naming."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from avialsync.core.cache import cache_root
from avialsync.core.errors import ExportError
from avialsync.core.timeline import TimeMap
from avialsync.engine.proxy import ProxyWorker, proxy_path_for
from avialsync.engine.segmented_media import Segment, write_manifest
from avialsync.engine.stimulus_grid_layout import GridLabels, GridVideo
from avialsync.engine.stimulus_grid_worker import StimulusGridExportWorker
from avialsync.engine.transcode import clip_container_suffix, encode_video, remux_clip
from avialsync.ui.clip_naming import non_overwriting_path, unique_camera_stems
from avialsync.ui.stimulus_grid_sources import event_clips

_LABELS = GridLabels(
    title="Comparison",
    event="Event {index}",
    no_footage="No footage",
    ruler="{before:.2f} s  Stimulus  +{after:.2f} s",
    current="Relative: {time:+.3f} s",
    no_signal="No signal",
    frame="Frame {index}",
    no_imaging="No imaging",
    band="{label} · {count}",
)


def _tiny_video(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = np.full((32, 48, 3), 90, dtype=np.uint8)
    encode_video(path, [(frame, 0.0), (frame, 0.1), (frame, 0.2)], rate=Fraction(10, 1))
    return path


def test_unique_camera_stems_and_non_overwriting_paths_prevent_multi_camera_collisions(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "12-00-00"
    trial.mkdir()
    cam_a = trial / "FaceCam.avi"
    cam_b = trial / "FrontCam.avi"
    cam_c = trial / "SideCam.avi"
    for cam in (cam_a, cam_b, cam_c):
        cam.write_bytes(b"avi")

    joined_paths = [
        str(cam_a / "joined_trials"),
        str(cam_b / "joined_trials"),
        str(cam_c / "joined_trials"),
    ]
    stems = unique_camera_stems(joined_paths)
    assert len(set(stems.values())) == 3
    assert stems[joined_paths[0]] == "FaceCam_avi_joined_trials"
    assert stems[joined_paths[1]] == "FrontCam_avi_joined_trials"
    assert stems[joined_paths[2]] == "SideCam_avi_joined_trials"

    # Same filename in sibling camera folders also disambiguates cleanly.
    left = str(tmp_path / "cam_left" / "video.mp4")
    right = str(tmp_path / "cam_right" / "video.mp4")
    folder_stems = unique_camera_stems([left, right])
    assert folder_stems[left] == "cam_left_video"
    assert folder_stems[right] == "cam_right_video"

    # Pre-existing files in an export folder are preserved, never silently overwritten.
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    existing = out_dir / "cam_left_video_trim.mp4"
    existing.write_bytes(b"keep-me")
    reserved: set[Path] = set()
    first_pick = non_overwriting_path(existing, reserved)
    second_pick = non_overwriting_path(existing, reserved)
    assert first_pick == out_dir / "cam_left_video_trim_2.mp4"
    assert second_pick == out_dir / "cam_left_video_trim_3.mp4"
    assert existing.read_bytes() == b"keep-me"


def test_event_clips_on_segmented_joined_cameras_use_video_suffix_and_distinct_files(
    tmp_path: Path,
) -> None:
    seg_a = _tiny_video(tmp_path / "trial1" / "FaceCam.mp4")
    seg_b = _tiny_video(tmp_path / "trial1" / "SideCam.mp4")
    manifest_a = tmp_path / "cache" / "face.segments.json"
    manifest_b = tmp_path / "cache" / "side.segments.json"
    manifest_a.parent.mkdir(parents=True)
    write_manifest(manifest_a, [Segment(str(seg_a), 0, 2, 0.0)])
    write_manifest(manifest_b, [Segment(str(seg_b), 0, 2, 0.0)])

    assert clip_container_suffix(manifest_a) == ".mp4"

    orig_a = str(seg_a / "joined_trials")
    orig_b = str(seg_b / "joined_trials")
    media_map = {orig_a: str(manifest_a), orig_b: str(manifest_b)}
    fake_grid = SimpleNamespace(
        _paths=[orig_a, orig_b],
        media_path_for=lambda p: media_map[p],
        time_map_for=lambda _p: TimeMap(),
    )
    fake_window = SimpleNamespace(video_grid=fake_grid)

    out_dir = tmp_path / "clips_out"
    out_dir.mkdir()
    specs = event_clips(fake_window, [orig_a, orig_b], [0.1], 0.05, 0.05, out_dir)
    outputs = [item[3] for item in specs]
    assert len(set(outputs)) == 2
    assert all(out.suffix == ".mp4" for out in outputs)
    assert "FaceCam_mp4_joined_trials" in outputs[0].name
    assert "SideCam_mp4_joined_trials" in outputs[1].name


def test_proxy_and_clip_and_grid_workers_refuse_to_overwrite_source_recordings(
    tmp_path: Path, qapp
) -> None:
    cam1 = _tiny_video(tmp_path / "camera_1.mp4")
    cam2 = _tiny_video(tmp_path / "camera_2.mp4")

    # Joined virtual camera path resolves beside the real file, never inside camera_1.mp4/.
    joined_virtual = cam1 / "joined_trials"
    suggested = proxy_path_for(joined_virtual)
    assert suggested.parent == tmp_path
    assert suggested.name == "camera_1_mp4_joined_trials_proxy.mp4"

    # ProxyWorker must refuse overwriting either its own source or another loaded source.
    cam1_bytes = cam1.read_bytes()
    cam2_bytes = cam2.read_bytes()
    errors: list[str] = []
    worker = ProxyWorker(cam1, destination=cam2, sources=(cam1, cam2))
    worker.error.connect(errors.append)
    worker.run()
    assert errors and "loaded source file" in errors[0]
    assert cam1.read_bytes() == cam1_bytes
    assert cam2.read_bytes() == cam2_bytes

    # remux_clip must refuse overwriting a segment file referenced inside a manifest.
    manifest = tmp_path / "joined.segments.json"
    write_manifest(manifest, [Segment(str(cam1), 0, 2, 0.0)])
    with pytest.raises(ExportError, match="loaded source file"):
        remux_clip(manifest, cam1, 0.0, 0.2)
    assert cam1.read_bytes() == cam1_bytes

    # StimulusGridExportWorker must refuse overwriting a loaded source behind a proxy
    # and refuse writing inside cache_root().
    proxy_file = _tiny_video(tmp_path / "camera_1_proxy.mp4")
    grid_errors: list[str] = []
    grid_worker = StimulusGridExportWorker(
        (GridVideo(proxy_file, "Cam 1"),),
        (0.1,),
        0.05,
        0.05,
        cam1,
        10,
        _LABELS,
        sources=(cam1, cam2),
    )
    grid_worker.error.connect(grid_errors.append)
    grid_worker.run()
    assert grid_errors == ["Choose an output file separate from the source videos."]
    assert cam1.read_bytes() == cam1_bytes

    cache_errors: list[str] = []
    cache_dest = cache_root() / "illegal_grid.mp4"
    cache_worker = StimulusGridExportWorker(
        (GridVideo(proxy_file, "Cam 1"),),
        (0.1,),
        0.05,
        0.05,
        cache_dest,
        10,
        _LABELS,
    )
    cache_worker.error.connect(cache_errors.append)
    cache_worker.run()
    assert cache_errors == ["Choose a destination outside the disposable cache"]
    assert not cache_dest.exists()
