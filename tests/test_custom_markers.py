"""Hand-placed 3D markers: the store and their files beside the pose data (D-112)."""

from __future__ import annotations

from pathlib import Path

from avialsync.core import custom_markers
from avialsync.core.custom_markers import CustomMarker, CustomMarkerStore
from avialsync.core.registry import LoaderRegistry
from avialsync.loaders.aol_session_loader import build_manifest


def _marker(name: str = "rung", frame: int = 4) -> CustomMarker:
    marker = CustomMarker(name=name, frame=frame)
    marker = marker.with_view("SideCam", 10.5, 20.25).with_view("FaceCam", 1.0, 2.0)
    return CustomMarker(marker.name, marker.frame, marker.views, (1.0, 2.0, 3.0), 0.75)


def test_views_are_sorted_so_equal_markers_compare_equal() -> None:
    marker = _marker()
    assert marker.cameras == ("FaceCam", "SideCam")
    assert marker.view("SideCam") == (10.5, 20.25)
    assert marker.view("Absent") is None


def test_moving_a_view_drops_the_stale_3d_position() -> None:
    moved = _marker().with_view("SideCam", 11.0, 21.0)
    assert moved.xyz is None and moved.error is None


def test_the_store_reports_only_real_changes() -> None:
    store = CustomMarkerStore()
    heard: list[object] = []
    store.observe(heard.append)
    marker = _marker()
    assert store.set("rung", 4, marker)
    assert not store.set("rung", 4, marker)
    assert store.at_frame(4) == [marker]
    assert store.names() == {"rung"}
    assert store.set("rung", 4, None)
    assert not store.set("rung", 4, None)
    assert heard == [("rung", 4), ("rung", 4)]


def test_the_2d_file_round_trips_in_dlc_layout(tmp_path) -> None:
    target = tmp_path / "SideCam_eks.custom_markers.csv"
    other = CustomMarker("paw", 9).with_view("SideCam", 5.0, 6.0)
    custom_markers.write_2d(target, "SideCam", [_marker(), other])
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("scorer,")
    assert lines[1].startswith("bodyparts,") and lines[2].startswith("coords,")
    assert custom_markers.read_2d(target) == {("rung", 4): (10.5, 20.25), ("paw", 9): (5.0, 6.0)}


def test_a_marker_absent_from_a_frame_is_blank_never_zero(tmp_path) -> None:
    target = tmp_path / "SideCam_eks.custom_markers.csv"
    other = CustomMarker("paw", 9).with_view("SideCam", 5.0, 6.0)
    custom_markers.write_2d(target, "SideCam", [_marker(), other])
    row_for_frame_9 = target.read_text(encoding="utf-8").splitlines()[-1].split(",")
    assert row_for_frame_9[0] == "9"
    assert "0.0" not in row_for_frame_9[4:7] and row_for_frame_9[4:7] == ["", "", ""]


def test_no_markers_keeps_the_file_with_its_headers(tmp_path) -> None:
    target = tmp_path / "SideCam_eks.custom_markers.csv"
    custom_markers.write_2d(target, "SideCam", [_marker()])
    custom_markers.write_2d(target, "SideCam", [])
    assert target.exists()
    assert len(target.read_text(encoding="utf-8").splitlines()) == 3
    assert custom_markers.read_2d(target) == {}


def test_the_3d_file_round_trips_in_anipose_layout(tmp_path) -> None:
    target = tmp_path / "_eks.custom_markers.csv"
    custom_markers.write_3d(target, [_marker(), CustomMarker("unsolved", 1)])
    header = target.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert header[:6] == ["rung_x", "rung_y", "rung_z", "rung_error", "rung_ncams", "rung_score"]
    assert header[-1] == "fnum"
    assert custom_markers.read_3d(target) == {("rung", 4): ((1.0, 2.0, 3.0), 0.75)}


def test_missing_files_read_as_empty(tmp_path) -> None:
    assert custom_markers.read_2d(tmp_path / "absent.csv") == {}
    assert custom_markers.read_3d(tmp_path / "absent.csv") == {}


def test_a_damaged_row_costs_only_that_row(tmp_path) -> None:
    target = tmp_path / "SideCam_eks.custom_markers.csv"
    custom_markers.write_2d(target, "SideCam", [_marker()])
    with target.open("a", encoding="utf-8") as handle:
        handle.write("not-a-frame,1,2,1.0\n")
    assert custom_markers.read_2d(target) == {("rung", 4): (10.5, 20.25)}


def test_the_file_sits_beside_the_pose_file_it_extends() -> None:
    assert custom_markers.marker_file_for("/s/FaceCam_eks.csv") == Path(
        "/s/FaceCam_eks.custom_markers.csv"
    )
    assert custom_markers.is_custom_marker_path("/s/_eks.custom_markers.csv")
    assert not custom_markers.is_custom_marker_path("/s/_eks.csv")


def test_no_loader_claims_our_own_marker_files(tmp_path) -> None:
    """They are pose-shaped CSVs; without the guard they come back as a camera."""
    target = tmp_path / "FaceCam_eks.custom_markers.csv"
    custom_markers.write_2d(target, "FaceCam", [_marker()])
    assert LoaderRegistry().find_best_loader(target) is None


def test_the_aol_manifest_does_not_mistake_markers_for_3d_pose(tmp_path) -> None:
    session = tmp_path / "09-35-24"
    eks = session / "pose-3d" / "default"
    eks.mkdir(parents=True)
    (eks / "_eks.csv").write_text("a_x,a_y,a_z,fnum\n1,2,3,0\n", encoding="utf-8")
    custom_markers.write_3d(eks / "_eks.custom_markers.csv", [_marker()])
    assert [p.name for p in build_manifest(session).eks_files] == ["_eks.csv"]
