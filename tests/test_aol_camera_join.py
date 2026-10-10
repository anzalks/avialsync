"""Per-trial AOL camera recordings joined into one video per camera, back to back."""

from __future__ import annotations

import datetime as dt
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest

from avialsync.core.registry import LoaderRegistry
from avialsync.loaders.aol_camera_join import (
    AOLJoinedCameraSource,
    configure_camera_roots,
    find_recordings,
)
from avialsync.loaders.aol_microscope_session import AOLMicroscopeTrialSource
from avialsync.loaders.video_standard import VideoStandardLoader
from tests.test_aol_microscope_trial import _trial


def _camera(
    folder: Path,
    name: str,
    frames: int,
    period_ms: float,
    shade: int,
    first_stamp: dt.datetime | None = None,
) -> Path:
    """An MJPEG AVI like the rig's, with its per-frame relative-times file.

    *first_stamp* is the camera PC's local clock at frame 0; without it every
    frame carries a placeholder stamp, for tests that do not match by clock.
    """
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
    if first_stamp is None:
        stamps = [f"03-09-2026;12:00:05.{i:04d}" for i in range(frames)]
    else:
        instants = [first_stamp + dt.timedelta(milliseconds=i * period_ms) for i in range(frames)]
        stamps = [instant.strftime("%d-%m-%Y;%H:%M:%S.%f")[:-2] for instant in instants]
    rows = [f"{i + 1}\t{i * period_ms:.3f}\t{stamp}" for i, stamp in enumerate(stamps)]
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
    # Not beside the date folder: a sibling mirror is found without the setting.
    camera_root = tmp_path / "elsewhere" / "camera_pc"
    _camera(camera_root / "2026-09-03" / "experiment_1" / "12-00-00", "FaceCam", 3, 10.0, 40)
    _camera(camera_root / "2026-09-03" / "experiment_1" / "12-10-00", "FaceCam", 3, 10.0, 90)
    assert find_recordings([first], []) == []
    found = {r.folder for r in find_recordings([first], [camera_root])}
    assert camera_root / first.relative_to(tmp_path) in found
    configure_camera_roots([camera_root])
    try:
        layout = AOLMicroscopeTrialSource().scan(experiment, None)
    finally:
        configure_camera_roots([])
    cameras = [item for item in layout.items if item.loader is AOLJoinedCameraSource]
    assert len(cameras) == 1 and len(cameras[0].config["segments"]) == 2
    assert second.name in cameras[0].config["segments"][1]["video"]


def _joined_item(tmp_path: Path):
    experiment, first, second = _experiment(tmp_path)
    _camera(first, "FaceCam", 5, 10.0, 40)
    _camera(second, "FaceCam", 5, 10.0, 140)
    layout = AOLMicroscopeTrialSource().scan(experiment, LoaderRegistry(plugin_dirs=[]))
    return next(item for item in layout.items if item.loader is AOLJoinedCameraSource)


def _frames(path: Path, indices: list[int]) -> list[np.ndarray]:
    from avialsync.engine.pyav_reader import PyAVReader

    with PyAVReader(path) as reader:
        return [reader.frame_at_index(index).to_ndarray(format="rgb24") for index in indices]


def test_trials_are_read_in_place_not_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A video is the same whether one file or several back to back (D-216).

    The cache holds a manifest of the trial files, not their footage, and it
    plays exactly the frames and times the copying join produced.
    """
    from avialsync.loaders import aol_camera_join

    item = _joined_item(tmp_path)
    listed = AOLJoinedCameraSource()
    listed.open(item.path, dict(item.config))
    manifest = listed.prepare(lambda _fraction: None)
    assert manifest.name == "joined.segments.json"
    assert sum(p.stat().st_size for p in manifest.parent.iterdir()) < 4096
    order = [5, 0, 4, 1, 3, 2]  # forward and back across both trials
    from_manifest = _frames(manifest, order)
    manifest_times = listed.exact_time_mapping()[0].copy()

    monkeypatch.setattr(aol_camera_join, "_JOIN_VERSION", 999)
    monkeypatch.setattr(aol_camera_join, "_manifest", lambda *_args: False)
    copied = AOLJoinedCameraSource()
    copied.open(item.path, dict(item.config))
    assert copied.prepare(lambda _fraction: None).suffix == ".mkv"
    for ours, theirs in zip(from_manifest, _frames(copied.media_path(), order), strict=True):
        np.testing.assert_array_equal(ours, theirs)
    np.testing.assert_array_equal(manifest_times, copied.exact_time_mapping()[0])


def test_a_trial_its_index_cannot_vouch_for_is_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from avialsync.loaders import aol_camera_join

    item = _joined_item(tmp_path)
    monkeypatch.setattr(aol_camera_join, "_indexed_frames", lambda _video: None)
    source = AOLJoinedCameraSource()
    source.open(item.path, dict(item.config))
    assert source.prepare(lambda _fraction: None).suffix == ".mkv"


def test_a_joined_video_exports_a_clip_and_a_proxy(tmp_path: Path) -> None:
    from avialsync.engine.pyav_reader import PyAVReader
    from avialsync.engine.transcode import encode_proxy, remux_clip

    item = _joined_item(tmp_path)
    source = AOLJoinedCameraSource()
    source.open(item.path, dict(item.config))
    manifest = source.prepare(lambda _fraction: None)
    with PyAVReader(manifest) as reader:
        times = reader.frame_times.copy()

    clip = tmp_path / "out" / "clip.mkv"
    clip.parent.mkdir()
    assert remux_clip(manifest, clip, float(times[1]), float(times[4]))
    with av.open(str(clip)) as container:
        assert sum(1 for p in container.demux(container.streams.video[0]) if p.size) == 4

    proxy = tmp_path / "out" / "proxy.mp4"
    encode_proxy(manifest, proxy, height=48)
    with av.open(str(proxy)) as container:
        assert sum(1 for _ in container.decode(container.streams.video[0])) == len(times)


def test_an_avi_index_gives_the_same_frame_table_as_reading_every_frame(tmp_path: Path) -> None:
    """The fast path must be the table a full read builds, or a frame is misnamed."""
    from avialsync.engine.pyav_reader import PyAVReader

    video = _camera(tmp_path, "FaceCam", 9, 10.0, 40)
    with PyAVReader(video) as reader:
        assert reader._index_table() is not None
        indexed = reader.frame_times.copy()
        read_in_full = reader._build_pts_table()[0] * float(reader.stream.time_base)
    np.testing.assert_array_equal(indexed, read_in_full)
