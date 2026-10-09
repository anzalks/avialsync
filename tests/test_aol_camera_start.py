"""All AOL cameras share one trigger start (the controller starts them at once)."""

from pathlib import Path

import pytest

from avialsync.loaders.aol_session_loader import build_manifest, is_aol_session


def _camera(session: Path, name: str, first_stamp: str) -> None:
    (session / f"{name}.avi").touch()
    rows = [
        f"{index + 1}\t{index * 4.346:.3f}\t24-06-2026;09:54:{first_stamp}" for index in range(5)
    ]
    (session / f"{name}-relative times.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_every_camera_item_uses_the_median_first_stamp(tmp_path: Path) -> None:
    session = tmp_path / "09-54-35"
    session.mkdir()
    _camera(session, "FaceCam", "40.5520")
    _camera(session, "FrontCam", "40.5530")
    _camera(session, "SideCam", "40.5800")
    assert is_aol_session(session)

    manifest = build_manifest(session)
    shared = {manifest.video_start_epochs[str(video)] for video in manifest.videos}
    assert len(shared) == 1
    assert set(manifest.camera_start_epochs.values()) == shared
    face = manifest.video_start_epochs[str(session / "FaceCam.avi")]
    assert face - int(face) == pytest.approx(0.553, abs=1e-6)
    # 28 ms of stamp spread is several 230 Hz frames: worth saying, never a block.
    assert any("span" in warning for warning in manifest.warnings)


def test_identical_first_stamps_share_a_start_without_a_warning(tmp_path: Path) -> None:
    session = tmp_path / "09-54-35"
    session.mkdir()
    for name in ("FaceCam", "FrontCam", "SideCam"):
        _camera(session, name, "40.5520")
    manifest = build_manifest(session)
    assert len(set(manifest.camera_start_epochs.values())) == 1
    assert not manifest.warnings
