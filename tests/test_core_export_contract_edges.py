"""Ragged pose rows preserve original cells and sparse metadata without fabricating labels."""

from pathlib import Path

import numpy as np
import pytest

from avialsync.core import artifact_io, artifacts, custom_markers, dlc_export, pose_export
from avialsync.core.errors import ExportError
from avialsync.core.identity_sidecar import _read_parts
from avialsync.core.pose_header import PoseHeader, parse_pose_header
from avialsync.core.sync import AlignmentMethod, ExactSyncFit, SyncFit, SyncProposal


def test_ragged_coordinate_rows_skip_only_unaddressable_cells() -> None:
    assert pose_export._frame_of([]) is None
    assert pose_export._frame_of(["inf"]) is None
    assert pose_export._frame_of(["image.png"]) is None
    row = ["0", "original"]
    assert pose_export._apply(row, {("head", "x"): 1, ("head", "y"): 2}, {"head": (3, 4)}) == 0
    assert row == ["0", "original"]
    assert not pose_export._reroute(row, {("a", "x"): 1}, {"a": "missing"})
    assert pose_export._renamed_scorers(["scorer", "", "model_avialsync_corrected"])[1] == ""
    assert _read_parts("head||tail") == ("head", "tail")


def test_pose_header_names_and_invalid_layouts_are_explicit() -> None:
    header = PoseHeader(
        3, (), (("", ""), ("head", "x"), ("head", "variance"), ("head", "variance")), False
    )
    assert header.points == ("", "head", "head", "head")
    assert header.coords == ("", "x", "variance", "variance")
    assert header.pose_schema().derived == ("variance",)
    for lines in [[["scorer"], ["unknown"], ["coords"]], [["scorer"], ["bodyparts"], ["wrong"]]]:
        assert parse_pose_header(lines) is None
    with pytest.raises(ValueError, match="Unknown training"):
        dlc_export.training_csv_path(Path("."), "video", "scorer", "invented")


def test_sidecar_naming_and_existing_refuse_destination_preserve_files(tmp_path: Path) -> None:
    assert (
        artifacts.get_kind("pointfix").target_for(tmp_path / "pose.csv").name
        == "pose_csv_avialfix.csv"
    )
    from dataclasses import replace

    kind = replace(artifacts.get_kind("data-slice-csv"), existing=artifacts.ExistingFile.REFUSE)
    target = tmp_path / "output.csv"
    target.write_text("old")
    with pytest.raises(ExportError, match="already exists"):
        artifact_io.publish(target, lambda p: p.write_text("new"), kind=kind)
    assert target.read_text() == "old"


def test_markers_missing_from_one_camera_write_no_invented_pixel(tmp_path: Path) -> None:
    output = tmp_path / "markers.csv"
    custom_markers.write_2d(
        output, "front", [custom_markers.CustomMarker("landmark", 0, (("side", 1, 2),))]
    )
    assert custom_markers.read_2d(output) == {}


def test_manual_and_ambiguous_proposals_preserve_their_distinct_acceptance_rules() -> None:
    fit = SyncFit(0, 0, 0, 0, 3, 0, reference_count=3, ambiguity_margin=0)
    proposal = SyncProposal("a", "b", fit, (), 0.01)
    assert "Another lag" in proposal.refusal and not proposal.acceptable
    from dataclasses import replace

    manual = replace(proposal, fit=replace(fit, method=AlignmentMethod.MANUAL))
    assert manual.refusal == "" and manual.applicable
    exact = ExactSyncFit(
        0,
        0,
        0,
        0,
        3,
        0,
        exact_master=np.array([0.0, 1.0, 2.0]),
        exact_source=np.array([0.0, 2.0, 3.0]),
    )
    assert exact.to_time_map().to_source(0.5) == 1
