"""Prop sidecars reject malformed primitive fields while preserving readable records."""

from __future__ import annotations

from pathlib import Path

import pytest

from avialsync.core import prop_file, wheel_file
from avialsync.core.errors import PropModelError
from avialsync.core.physical_props import BallProp, BallSurface, Ladder
from avialsync.core.wheel import Wheel, WheelFit, WheelSpec
from tests.wheel_fixture import TRUTH


@pytest.mark.parametrize(
    ("parser", "value"),
    [
        (prop_file._mapping, []),
        (prop_file._records, {}),
        (prop_file._records, [1]),
        (prop_file._text, 1),
        (prop_file._number, True),
        (prop_file._number, "1"),
        (prop_file._number, float("inf")),
        (prop_file._point3, [1, 2]),
        (prop_file._pixel, [1]),
        (prop_file._point4, [1, 2, 3]),
        (prop_file._values, "readings"),
    ],
)
def test_malformed_toml_fields_are_not_coerced_into_apparatus_evidence(
    parser, value: object
) -> None:
    with pytest.raises(PropModelError):
        parser(value)


def test_unknown_point_status_and_choice_are_rejected() -> None:
    with pytest.raises(PropModelError, match="solve status"):
        prop_file._parse_point({"issue": "invented"})
    with pytest.raises(PropModelError, match="unknown value"):
        prop_file._choice("invented", ("one", "two"))


def test_invalid_ball_channels_and_visual_landmark_identity_are_rejected() -> None:
    head = {"name": "ball"}
    table = {"centre": [0, 0, 0], "radius": 1, "binding": {"channels": ["x", "y", "z"]}}
    with pytest.raises(PropModelError, match="four channel"):
        prop_file._parse_ball(head, {"ball": table})
    table = {
        "centre": [0, 0, 0],
        "radius": 1,
        "visual": {"reference_frame": 0, "frame": [{"frame": 0, "mark": []}]},
    }
    with pytest.raises(PropModelError, match="three named marks"):
        prop_file._parse_ball(head, {"ball": table})


def test_belt_corner_records_must_describe_four_observations() -> None:
    document = {
        "belt": {"vertex": [{"xyz": [0, 0, 0]}, {"xyz": [10, 0, 0]}], "corner": [{"click": []}]}
    }
    with pytest.raises(PropModelError, match="four clicked corners"):
        prop_file._parse_belt({"name": "belt"}, document)


def test_unrecognized_types_and_unsupported_record_formats_do_not_load(tmp_path: Path) -> None:
    with pytest.raises(PropModelError, match="kind"):
        prop_file.prop_kind(object())
    assert prop_file.read_prop_records(tmp_path / "missing") == ([], [], set())
    for index, text in enumerate(
        [
            'format = "future/2"\n[prop]\nversion=1\nkind="ladder"\nname="a"\n',
            '[prop]\nversion=1\nkind="future"\nname="a"\n',
            '[prop]\nversion=1\nkind="wheel"\nname="a"\n',
        ]
    ):
        (tmp_path / f"bad{index}_prop.toml").write_text(text, encoding="utf-8")
    records, issues, removed = prop_file.read_prop_records(tmp_path)
    assert records == [] and removed == set()
    assert {issue.reason for issue in issues} == {
        "unsupported_version",
        "unsupported_kind",
        "damaged",
    }


def test_tombstones_and_case_collisions_never_overwrite_another_record(tmp_path: Path) -> None:
    prop_file.write_ladder(tmp_path, Ladder("lower"))
    with pytest.raises(PropModelError, match="already uses"):
        prop_file.write_ladder(tmp_path, Ladder("LOWER"))
    # A manually renamed tombstone must not hide the record it claims.
    prop_file.write_ladder(tmp_path, Ladder("removed"))
    prop_file.write_removed(tmp_path, "removed", kind="ladder")
    tombstone = prop_file.prop_path(tmp_path, "removed")
    tombstone.rename(prop_file.prop_path(tmp_path, "different"))
    records, issues, removed = prop_file.read_prop_records(tmp_path)
    assert [record.name for record in records] == ["lower"]
    assert removed == set() and any(issue.reason == "name_mismatch" for issue in issues)


def test_compatibility_writers_keep_the_generalized_format(tmp_path: Path) -> None:
    ball = BallProp("ball", BallSurface((0.0, 0.0, 0.0), 1.0))
    prop_file.write_ball(tmp_path, ball)
    wheel = Wheel(WheelSpec("wheel", TRUTH.bar_count), 0, (), WheelFit(TRUTH, (), (), (), ()))
    prop_file.write_wheel(tmp_path, wheel)
    records, issues = prop_file.read_props(tmp_path)
    assert not issues and ball in records and wheel in records


@pytest.mark.parametrize(
    "document",
    [
        [],
        {"kind": "unknown", "version": 1},
        {"kind": "periodic_rotary", "version": 1, "harmonic": {}},
    ],
)
def test_wheel_motion_tables_are_structurally_validated(document: object) -> None:
    with pytest.raises(ValueError):
        wheel_file._parse_motion(document)
    assert wheel_file._parse_motion(None) is None
    assert wheel_file._parse({"wheel": {"removed": True}}) is None
