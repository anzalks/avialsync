"""Which calibration a session uses: ``pose-3d/calibration_ref.txt`` (D-112).

The file is copied between experiments by hand, so it is parsed by shape and
never overwritten: a replaced one is kept under a dated name.
"""

from __future__ import annotations

from pathlib import Path

from avialsync.core import calibration_ref
from avialsync.core.calibration import Calibration
from tests.wheel_fixture import CAMERAS


def _ref(folder: Path, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / calibration_ref.REF_NAME
    path.write_text(text, encoding="utf-8")
    return path


def test_a_reference_is_read_by_shape(tmp_path) -> None:
    ref = _ref(
        tmp_path / "pose-3d",
        "# Sources required\nSideCam.mp4\nFrontCam.mp4\n\n"
        '# 3d rotation matrix location\n/path/to/calibration.toml or "C:/rigs/rig2/real.toml"\n',
    )
    link = calibration_ref.read_ref(ref)
    assert link is not None
    assert link.sources == ("SideCam.mp4", "FrontCam.mp4")
    assert link.calibration == Path("C:/rigs/rig2/real.toml")
    assert link.ref_file == ref


def test_a_relative_calibration_is_taken_from_the_reference_folder(tmp_path) -> None:
    ref = _ref(tmp_path / "pose-3d", "# 3d rotation matrix location\nrig.toml\n")
    link = calibration_ref.read_ref(ref)
    assert link is not None and link.calibration == tmp_path / "pose-3d" / "rig.toml"


def test_a_reference_naming_no_toml_is_no_reference(tmp_path) -> None:
    ref = _ref(tmp_path / "pose-3d", "# Sources required\nA.mp4\n")
    assert calibration_ref.read_ref(ref) is None


def test_write_then_read(tmp_path) -> None:
    folder = tmp_path / "pose-3d"
    calibration_ref.write_ref(folder, ["A.mp4", "B.mp4"], tmp_path / "rig.toml")
    link = calibration_ref.read_ref(folder / calibration_ref.REF_NAME)
    assert link is not None
    assert link.sources == ("A.mp4", "B.mp4")
    assert link.calibration == tmp_path / "rig.toml"


def test_locate_prefers_the_reference_then_pose3d_then_the_session(tmp_path) -> None:
    session = tmp_path / "session"
    folder = session / "pose-3d"
    folder.mkdir(parents=True)
    (session / "calibration.toml").write_text("", encoding="utf-8")
    assert calibration_ref.locate(folder).calibration == session / "calibration.toml"
    (folder / "calibration.toml").write_text("", encoding="utf-8")
    assert calibration_ref.locate(folder).calibration == folder / "calibration.toml"
    _ref(folder, "# 3d rotation matrix location\n/elsewhere/rig.toml\n")
    assert calibration_ref.locate(folder).calibration == Path("/elsewhere/rig.toml")


def test_a_broken_reference_is_still_reported(tmp_path) -> None:
    """A reference to a missing file is returned, so the caller can name it."""
    folder = tmp_path / "pose-3d"
    _ref(folder, "# 3d rotation matrix location\n/nowhere/rig.toml\n")
    link = calibration_ref.locate(folder)
    assert link is not None and not link.calibration.exists()


def test_nothing_found_is_none(tmp_path) -> None:
    assert calibration_ref.locate(tmp_path / "pose-3d") is None


def test_cameras_are_matched_by_stem_then_by_source_order() -> None:
    rig = Calibration(cameras=tuple(CAMERAS.values()))
    videos = ["/rec/Front.mp4", "/rec/cam_b.mp4", "/rec/unknown.mp4"]
    mapping = calibration_ref.camera_names(rig, videos, ["x.mp4", "cam_b.mp4"])
    assert mapping == {"/rec/Front.mp4": "Front", "/rec/cam_b.mp4": "Left"}


def test_the_pose3d_folder_is_found_from_inside_or_beside_it(tmp_path) -> None:
    session = tmp_path / "session"
    (session / "pose-3d" / "default").mkdir(parents=True)
    inside = session / "pose-3d" / "default" / "_eks.csv"
    assert calibration_ref.pose3d_dir_for(inside) == session / "pose-3d"
    assert calibration_ref.pose3d_dir_for(session) == session / "pose-3d"


def test_an_existing_reference_is_kept_aside_not_replaced(tmp_path) -> None:
    folder = tmp_path / "pose-3d"
    original = "# 3d rotation matrix location\n/hand/edited.toml\n# a lab's note\n"
    _ref(folder, original)
    kept = calibration_ref.keep_aside(folder)
    assert kept is not None and kept.read_text(encoding="utf-8") == original
    assert not (folder / calibration_ref.REF_NAME).exists()
    assert calibration_ref.keep_aside(folder) is None


def test_an_unused_name_never_collides(tmp_path) -> None:
    (tmp_path / "calibration_fitted.toml").write_text("", encoding="utf-8")
    (tmp_path / "calibration_fitted-2.toml").write_text("", encoding="utf-8")
    assert calibration_ref.unused_name(tmp_path / "calibration_fitted.toml") == (
        tmp_path / "calibration_fitted-3.toml"
    )


def test_a_windows_path_is_kept_as_written(tmp_path) -> None:
    """A reference copied from a Windows rig names its file, not one under this folder."""
    ref = _ref(
        tmp_path / "pose-3d", '# 3d rotation matrix location\n"\\\\rigserver\\cal\\rig.toml"\n'
    )
    link = calibration_ref.read_ref(ref)
    assert link is not None and str(link.calibration).startswith("\\\\rigserver")


def test_a_rooted_path_without_a_drive_is_kept_as_written(tmp_path) -> None:
    """``\\rigs\\rig.toml`` names the drive root, not a folder under this one.

    Joined onto the reference folder, Windows would hand it the folder's own
    drive letter, and POSIX would bury it under the folder.
    """
    ref = _ref(tmp_path / "pose-3d", "# 3d rotation matrix location\n\\rigs\\rig.toml\n")
    link = calibration_ref.read_ref(ref)
    assert link is not None and link.calibration == Path("\\rigs\\rig.toml")
