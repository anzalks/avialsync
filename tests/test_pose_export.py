"""Exporting corrected pose data: the analysis copy and the retraining set (D-099).

Both exports carry human judgement into files other tools will read, so the
property under test throughout is provenance: what left must say a person
touched it, must not have destroyed the prediction it disagrees with, and must
not be quietly filtered out by the first thing downstream that reads it.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from avialsync.core import dlc_export, pose_export

SCORER = "DLC_resnet50"


def _pose_file(tmp_path: Path, *, likelihood: bool = True) -> Path:
    """A three-header-row DLC export with two body parts."""
    parts = ["nose", "tail_base"]
    coords = ["x", "y", "likelihood"] if likelihood else ["x", "y"]
    scorer_row = ["scorer"] + [SCORER] * (len(parts) * len(coords))
    bodypart_row = ["bodyparts"] + [part for part in parts for _ in coords]
    coord_row = ["coords"] + coords * len(parts)

    path = tmp_path / "eks.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(scorer_row)
        writer.writerow(bodypart_row)
        writer.writerow(coord_row)
        for frame in range(4):
            row: list[str] = [str(frame)]
            for part_index in range(len(parts)):
                row += [str(10.0 + frame), str(20.0 + part_index)]
                if likelihood:
                    row.append("0.05")
            writer.writerow(row)
    return path


def _read(path: Path) -> tuple[list[list[str]], list[list[str]]]:
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    return rows[:3], rows[3:]


# ── the corrected copy ───────────────────────────────────────────────


def test_the_original_is_left_exactly_as_it_was(tmp_path: Path) -> None:
    """The recording cannot be regenerated; an export may not consume it."""
    source = _pose_file(tmp_path)
    before = source.read_bytes()

    pose_export.write_corrected_copy(source, tmp_path / "out.csv", {1: {"nose": (99.0, 88.0)}})

    assert source.read_bytes() == before


def test_only_the_corrected_cells_change(tmp_path: Path) -> None:
    source = _pose_file(tmp_path)
    target = tmp_path / "out.csv"

    pose_export.write_corrected_copy(source, target, {1: {"nose": (99.5, 88.5)}})

    _, original_rows = _read(source)
    _, rows = _read(target)
    assert rows[1][1:3] == ["99.5", "88.5"], "the corrected point moved"
    assert rows[1][4:] == original_rows[1][4:], "the other body part is untouched"
    assert rows[0] == original_rows[0], "an uncorrected frame is copied verbatim"
    assert rows[2] == original_rows[2]


def test_a_corrected_copy_says_a_person_touched_it(tmp_path: Path) -> None:
    """A fixed-layout CSV has no comments; the scorer is the only field left."""
    source = _pose_file(tmp_path)
    target = tmp_path / "out.csv"

    pose_export.write_corrected_copy(source, target, {1: {"nose": (99.0, 88.0)}})

    header, _ = _read(target)
    assert header[0][1] == f"{SCORER}{pose_export.SCORER_SUFFIX}"
    assert header[0][0] == "scorer", "the index column's own label is left alone"
    assert header[1:] == _read(source)[0][1:], "body parts and coords are unchanged"


def test_marking_the_scorer_can_be_turned_off(tmp_path: Path) -> None:
    source = _pose_file(tmp_path)
    target = tmp_path / "out.csv"

    pose_export.write_corrected_copy(source, target, {1: {"nose": (99.0, 88.0)}}, mark_scorer=False)

    assert _read(target)[0][0][1] == SCORER


def test_a_corrected_point_is_certain(tmp_path: Path) -> None:
    """Otherwise the first likelihood threshold downstream drops the correction.

    A corrected coordinate is usually one the model was unsure about, so it
    carries a low likelihood -- and code that filters on that would discard the
    very point the user exported the file for.
    """
    source = _pose_file(tmp_path)
    target = tmp_path / "out.csv"

    pose_export.write_corrected_copy(source, target, {1: {"nose": (99.0, 88.0)}})

    _, rows = _read(target)
    assert rows[1][3] == pose_export.CORRECTED_LIKELIHOOD
    assert rows[1][6] == "0.05", "an uncorrected part keeps the model's own value"
    assert rows[0][3] == "0.05", "an uncorrected frame keeps it too"


def test_a_file_without_a_likelihood_column_still_exports(tmp_path: Path) -> None:
    source = _pose_file(tmp_path, likelihood=False)
    target = tmp_path / "out.csv"

    report = pose_export.write_corrected_copy(source, target, {1: {"nose": (99.0, 88.0)}})

    assert report.corrected_points == 1
    assert _read(target)[1][1][1:3] == ["99.0", "88.0"]


def test_the_report_counts_what_it_did(tmp_path: Path) -> None:
    source = _pose_file(tmp_path)

    report = pose_export.write_corrected_copy(
        source,
        tmp_path / "out.csv",
        {1: {"nose": (1.0, 2.0), "tail_base": (3.0, 4.0)}, 2: {"nose": (5.0, 6.0)}},
    )

    assert report.rows == 4
    assert report.corrected_rows == 2
    assert report.corrected_points == 3
    assert report.unmatched_frames == 0


def test_a_correction_naming_a_frame_that_is_not_there_is_counted(tmp_path: Path) -> None:
    """Reported, not raised: the rest of the export is still worth having."""
    source = _pose_file(tmp_path)

    report = pose_export.write_corrected_copy(
        source, tmp_path / "out.csv", {999: {"nose": (1.0, 2.0)}}
    )

    assert report.unmatched_frames == 1
    assert report.corrected_points == 0


def test_a_correction_for_an_unknown_body_part_is_ignored(tmp_path: Path) -> None:
    source = _pose_file(tmp_path)

    report = pose_export.write_corrected_copy(
        source, tmp_path / "out.csv", {1: {"whisker": (1.0, 2.0)}}
    )

    assert report.corrected_points == 0
    assert _read(tmp_path / "out.csv")[1][1] == _read(source)[1][1]


def test_a_file_that_is_not_a_pose_export_is_refused_by_name(tmp_path: Path) -> None:
    source = tmp_path / "short.csv"
    source.write_text("a,b\n1,2\n")

    with pytest.raises(ValueError, match="header rows"):
        pose_export.write_corrected_copy(source, tmp_path / "out.csv", {})


def test_the_default_output_sits_beside_the_source(tmp_path: Path) -> None:
    assert pose_export.corrected_copy_path(tmp_path / "eks.csv") == tmp_path / "eks_corrected.csv"


# ── the retraining set ───────────────────────────────────────────────


def test_a_labelled_frame_carries_the_whole_pose(tmp_path: Path) -> None:
    """A training label is a whole pose, not the one coordinate that was wrong.

    Writing only the corrected part would teach the network that the others are
    absent from the frame -- the opposite of what the correction meant.
    """
    target = tmp_path / "CollectedData_me.csv"

    dlc_export.write_labeled_data(
        target,
        "SideCam",
        "me",
        ["nose", "tail_base"],
        [
            dlc_export.LabeledFrame(
                frame=12, positions={"nose": (1.0, 2.0), "tail_base": (3.0, 4.0)}
            )
        ],
    )

    rows = list(csv.reader(target.open(newline="", encoding="utf-8")))
    assert rows[0] == ["scorer", "me", "me", "me", "me"]
    assert rows[1] == ["bodyparts", "nose", "nose", "tail_base", "tail_base"]
    assert rows[2] == ["coords", "x", "y", "x", "y"]
    assert rows[3] == ["labeled-data/SideCam/img00012.png", "1.0", "2.0", "3.0", "4.0"]


def test_an_untracked_part_is_blank_not_the_top_left_corner(tmp_path: Path) -> None:
    """``0,0`` is a position in the image, and it is where the network would look."""
    target = tmp_path / "CollectedData_me.csv"

    report = dlc_export.write_labeled_data(
        target,
        "SideCam",
        "me",
        ["nose", "tail_base"],
        [dlc_export.LabeledFrame(frame=12, positions={"nose": (1.0, 2.0)})],
    )

    rows = list(csv.reader(target.open(newline="", encoding="utf-8")))
    assert rows[3] == ["labeled-data/SideCam/img00012.png", "1.0", "2.0", "", ""]
    assert report.labelled_points == 1
    assert report.missing_points == 1


def test_frames_are_written_in_order(tmp_path: Path) -> None:
    target = tmp_path / "CollectedData_me.csv"

    dlc_export.write_labeled_data(
        target,
        "SideCam",
        "me",
        ["nose"],
        [
            dlc_export.LabeledFrame(frame=30, positions={"nose": (1.0, 1.0)}),
            dlc_export.LabeledFrame(frame=2, positions={"nose": (2.0, 2.0)}),
        ],
    )

    rows = list(csv.reader(target.open(newline="", encoding="utf-8")))[3:]
    assert [row[0] for row in rows] == [
        "labeled-data/SideCam/img00002.png",
        "labeled-data/SideCam/img00030.png",
    ]


def test_the_image_path_is_the_one_dlc_looks_for(tmp_path: Path) -> None:
    assert dlc_export.image_relative_path("SideCam", 7) == "labeled-data/SideCam/img00007.png"
    assert dlc_export.collected_data_path(tmp_path, "SideCam", "me") == (
        tmp_path / "labeled-data" / "SideCam" / "CollectedData_me.csv"
    )


def test_the_exports_need_no_qt() -> None:
    """``core/`` is headless (architecture rule 2)."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import avialsync.core.pose_export, avialsync.core.dlc_export; "
            "sys.exit(1 if 'PySide6' in sys.modules else 0)",
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
