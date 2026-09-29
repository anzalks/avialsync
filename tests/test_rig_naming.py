"""Which camera a file is named after, decided in one place (rule 15).

A session loader matching a track to a camera and the import dialog choosing
which video a dropped pose file belongs on are the same question, and two
answers to it would eventually disagree about somebody's recording.
"""

from __future__ import annotations

from avialsync.core.rig_naming import match_label

CAMERAS = ("FaceCam", "SideCam", "FrontCam")


def test_a_pose_file_is_named_after_its_camera() -> None:
    assert match_label("FrontCam_eks", CAMERAS) == "FrontCam"
    assert match_label("SideCam", CAMERAS) == "SideCam"


def test_matching_ignores_case() -> None:
    assert match_label("frontcam_eks_corrected", CAMERAS) == "FrontCam"


def test_a_longer_label_is_never_shadowed_by_a_shorter_one() -> None:
    assert match_label("SideCamTop_eks", ("Side", "SideCamTop")) == "SideCamTop"


def test_merely_mentioning_a_camera_is_not_being_its_file() -> None:
    """A prefix, not a substring: head_FrontCam_raw is not FrontCam's file."""
    assert match_label("head_FrontCam_raw", CAMERAS) is None


def test_an_empty_label_claims_nothing() -> None:
    assert match_label("anything", ("", "FaceCam")) is None
    assert match_label("FaceCam_eks", ("", "FaceCam")) == "FaceCam"


def test_a_file_named_after_nothing_matches_nothing() -> None:
    assert match_label("_eks", CAMERAS) is None
