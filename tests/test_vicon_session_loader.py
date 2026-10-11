"""Vicon session discovery pairs a C3D trial with its calibrated video."""

from pathlib import Path

import numpy as np
import pytest

from avialsync.core.calibration import CameraModel
from avialsync.core.registry import LoaderRegistry
from avialsync.loaders import vicon_session_loader
from avialsync.loaders.vicon_session_loader import ViconSessionSource


def test_session_pairs_trial_files_and_declares_video_frame_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c3d_path = tmp_path / "trial.c3d"
    xcp_path = tmp_path / "trial.xcp"
    video_path = tmp_path / "trial.video-1.20260625143252.avi"
    for path in (c3d_path, xcp_path, video_path):
        path.touch()

    camera = CameraModel(
        name="video-1",
        size=(1920, 1080),
        matrix=np.eye(3),
    )
    monkeypatch.setattr(vicon_session_loader, "camera_from_xcp", lambda _path: camera)
    monkeypatch.setattr(
        vicon_session_loader, "_video_metadata", lambda _path: (100.0, 2921, 1280, 720)
    )

    layout = ViconSessionSource().scan(tmp_path, LoaderRegistry(plugin_dirs=[]))

    assert ViconSessionSource.can_open(tmp_path) == 0.9
    assert [item.path for item in layout.items] == [video_path, c3d_path]
    assert layout.items[1].config["role"] == "pose3d_overlay2d"
    assert layout.items[1].config["overlay_video"] == str(video_path)
    assert layout.items[1].config["fps"] == 100.0
    assert layout.warnings == []


def test_session_reports_unpaired_c3d_instead_of_guessing(tmp_path: Path) -> None:
    (tmp_path / "trial.c3d").touch()

    layout = ViconSessionSource().scan(tmp_path, LoaderRegistry(plugin_dirs=[]))

    assert layout.items == []
    assert any("no matching XCP" in warning for warning in layout.warnings)


def test_session_does_not_claim_a_trial_without_video(tmp_path: Path) -> None:
    (tmp_path / "trial.c3d").touch()
    (tmp_path / "trial.xcp").touch()

    assert ViconSessionSource.can_open(tmp_path) == 0.0


def test_builtin_registry_discovers_vicon_loader_and_session(tmp_path: Path) -> None:
    from avialsync.loaders.vicon_c3d_loader import ViconC3DLoader

    c3d_path = tmp_path / "trial.c3d"
    c3d_path.touch()
    c3d_path.with_suffix(".xcp").touch()
    (tmp_path / "trial.video-1.capture.avi").touch()
    registry = LoaderRegistry(plugin_dirs=[])

    assert registry.find_best_loader(c3d_path) is ViconC3DLoader
    assert registry.find_best_session(tmp_path) is ViconSessionSource


def _trial(folder: Path, name: str, start: str | None, end: str | None) -> None:
    """A trial: markers, video, and a calibration naming when it was captured."""
    (folder / f"{name}.c3d").touch()
    (folder / f"{name}.video-1.20260625143252.avi").touch()
    capture = f'<Capture START_TIME="{start} DST" END_TIME="{end} DST"/>' if start and end else ""
    (folder / f"{name}.xcp").write_text(
        f'<Cameras><Camera DEVICEID="video-1">{capture}</Camera></Cameras>', encoding="utf-8"
    )


@pytest.fixture
def fake_media(monkeypatch: pytest.MonkeyPatch) -> None:
    camera = CameraModel(name="video-1", size=(1920, 1080), matrix=np.eye(3))
    monkeypatch.setattr(vicon_session_loader, "camera_from_xcp", lambda _path: camera)
    monkeypatch.setattr(
        vicon_session_loader, "_video_metadata", lambda _path: (100.0, 1700, 1280, 720)
    )


def test_trials_sit_at_their_capture_starts_with_the_time_between_kept(
    tmp_path: Path, fake_media: None
) -> None:
    """D-217: the .xcp records each capture to the millisecond; the gap stays."""
    _trial(tmp_path, "t_02", "2026-06-25 13:59:36.246", "2026-06-25 13:59:53.424")
    _trial(tmp_path, "t_03", "2026-06-25 14:00:25.415", "2026-06-25 14:00:41.711")

    layout = ViconSessionSource().scan(tmp_path, LoaderRegistry(plugin_dirs=[]))

    epoch = layout.session_epoch
    starts = [item.source_epoch - epoch for item in layout.items]
    assert starts == pytest.approx([0.0, 0.0, 49.169, 49.169])
    relative = [(s - epoch, e - epoch, n) for s, e, n in layout.segments]
    assert [n for _s, _e, n in relative] == ["t_02", "t_03"]
    assert [edge for s, e, _n in relative for edge in (s, e)] == pytest.approx(
        [0.0, 17.178, 49.169, 65.465]
    )
    # Zone-less local time: placement only, never shown as wall clock.
    assert layout.anchor_epoch == 0.0
    assert any("without its time zone" in warning for warning in layout.warnings)
    # One lane per camera, one for its markers, rather than one per trial.
    assert {item.coverage_group for item in layout.items} == {
        "Vicon camera video-1",
        "Vicon markers over camera video-1",
    }


def test_trials_without_capture_times_start_together_and_say_so(
    tmp_path: Path, fake_media: None
) -> None:
    _trial(tmp_path, "t_02", None, None)
    _trial(tmp_path, "t_03", None, None)

    layout = ViconSessionSource().scan(tmp_path, LoaderRegistry(plugin_dirs=[]))

    assert len(layout.items) == 4
    assert all(item.source_epoch is None for item in layout.items)
    assert layout.segments == []
    assert any("records when it was captured" in warning for warning in layout.warnings)


def test_capture_span_reads_the_capture_element_only(tmp_path: Path) -> None:
    xcp = tmp_path / "t.xcp"
    xcp.write_text(
        '<Cameras><Camera><Calibration START_TIME="2026-06-25 12:54:28.870 DST" '
        'END_TIME="2026-06-25 12:55:06.828 DST"/>'
        '<Capture START_TIME="2026-06-25 13:59:36.246 DST" '
        'END_TIME="2026-06-25 13:59:53.424 DST"/></Camera></Cameras>',
        encoding="utf-8",
    )
    span = vicon_session_loader.capture_span(xcp)
    assert span is not None and span[1] - span[0] == pytest.approx(17.178)
    assert vicon_session_loader.capture_span(tmp_path / "missing.xcp") is None
