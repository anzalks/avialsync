"""One pose schema, declared by the loader (D-140).

The property under test throughout is that a consumer never has to recover a
point's identity from a channel name: the loader states it, and two formats with
nothing in common produce the same shape at the far end.
"""

from __future__ import annotations

from pathlib import Path

from avialsync.core.pose import PosePoint, PoseSchema, canonical_name, split_channel
from avialsync.core.pose_header import read_pose_header
from avialsync.loaders.tracking_loader import TrackingLoader

SINGLE = [
    "scorer,DLC,DLC,DLC",
    "bodyparts,nose,nose,nose",
    "coords,x,y,likelihood",
    "0,1.0,2.0,0.9",
]

MULTI = [
    "scorer" + ",DLC" * 6,
    "individuals,mouseA,mouseA,mouseA,mouseB,mouseB,mouseB",
    "bodyparts,snout,snout,snout,snout,snout,snout",
    "coords,x,y,likelihood,x,y,likelihood",
    "0,1.0,2.0,0.9,3.0,4.0,0.8",
]

#: What the ensemble smoother writes: eleven columns for one body part.
EKS = [
    "scorer" + ",eks" * 11,
    "bodyparts" + ",nose" * 11,
    "coords,x,y,likelihood,x_ens_median,x_ens_var,y_ens_median,y_ens_var,"
    "zscore,nll,x_posterior_var,y_posterior_var",
    "0," + ",".join(["1.0"] * 11),
]


def _write(tmp_path: Path, lines: list[str], name: str = "pose.csv") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ── the naming rule ──────────────────────────────────────────────────


def test_a_single_animal_point_keeps_the_name_it_always_had() -> None:
    assert canonical_name("", "snout") == "snout"


def test_a_multi_animal_point_carries_its_individual() -> None:
    assert canonical_name("mouseA", "snout") == "mouseA_snout"


def test_split_channel_is_the_inverse_of_the_channel_it_names() -> None:
    point = PosePoint("mouseA", "snout", ("x", "y"))
    assert split_channel(point.channel("x")) == (point.name, "x")


def test_split_channel_declines_what_is_not_a_coordinate() -> None:
    assert split_channel("nose_likelihood") is None
    assert split_channel("nose") is None
    assert split_channel("_x") is None


# ── the schema ───────────────────────────────────────────────────────


def test_a_single_animal_file_declares_points_without_individuals(tmp_path: Path) -> None:
    schema = read_pose_header(_write(tmp_path, SINGLE)).pose_schema()

    assert [p.name for p in schema.points] == ["nose"]
    assert schema.multi_animal is False
    assert schema.individuals == ()
    assert schema.points[0].has_likelihood is True
    assert schema.is_3d is False


def test_a_multi_animal_file_declares_one_point_per_animal(tmp_path: Path) -> None:
    schema = read_pose_header(_write(tmp_path, MULTI)).pose_schema()

    assert [p.name for p in schema.points] == ["mouseA_snout", "mouseB_snout"]
    assert schema.individuals == ("mouseA", "mouseB")
    assert schema.multi_animal is True


def test_derived_columns_are_declared_not_mistaken_for_axes(tmp_path: Path) -> None:
    schema = read_pose_header(_write(tmp_path, EKS)).pose_schema()

    assert [p.name for p in schema.points] == ["nose"]
    assert schema.points[0].axes == ("x", "y")
    assert "x_ens_var" in schema.derived
    assert "nll" in schema.derived
    assert schema.coordinate_channels("x", "y") == ("nose_x", "nose_y")


def test_a_schema_with_no_points_is_falsy() -> None:
    assert not PoseSchema()
    assert PoseSchema(points=(PosePoint("", "nose", ("x", "y")),))


def test_three_d_is_stated_not_counted() -> None:
    flat = PoseSchema(points=(PosePoint("", "a", ("x", "y")), PosePoint("", "b", ("x", "y"))))
    spatial = PoseSchema(points=(PosePoint("", "a", ("x", "y", "z")),))

    assert flat.is_3d is False
    assert spatial.is_3d is True
    assert spatial.points_with("x", "y", "z") == spatial.points
    assert flat.points_with("x", "y", "z") == ()


def test_the_schema_round_trips_through_the_import_manifest(tmp_path: Path) -> None:
    """It is persisted, so a cache hit knows what its channels mean."""
    original = read_pose_header(_write(tmp_path, MULTI)).pose_schema()

    restored = PoseSchema.from_dict(original.as_dict())

    assert restored == original


# ── the loader declares it ───────────────────────────────────────────


def test_the_loader_declares_its_schema(tmp_path: Path) -> None:
    loader = TrackingLoader()
    loader.open(_write(tmp_path, MULTI), {"fps": 30.0})

    schema = loader.pose_schema()
    assert schema is not None
    assert [p.name for p in schema.points] == ["mouseA_snout", "mouseB_snout"]


def test_derived_columns_are_not_imported_by_default(tmp_path: Path) -> None:
    """Eleven columns per body part were pyramided on a plain drag-and-drop."""
    loader = TrackingLoader()
    loader.open(_write(tmp_path, EKS), {"fps": 30.0})

    names = [channel.name for channel in loader.channels()]
    assert names == ["nose_x", "nose_y", "nose_likelihood"]


def test_an_explicit_coords_request_still_wins(tmp_path: Path) -> None:
    loader = TrackingLoader()
    loader.open(_write(tmp_path, EKS), {"fps": 30.0, "coords": ["x", "y"]})

    assert [c.name for c in loader.channels()] == ["nose_x", "nose_y"]


def test_the_schema_names_match_the_channels_the_loader_emits(tmp_path: Path) -> None:
    """The contract the consumers rely on: schema names address real channels."""
    loader = TrackingLoader()
    loader.open(_write(tmp_path, MULTI), {"fps": 30.0})

    channels = {c.name for c in loader.channels()}
    schema = loader.pose_schema()
    assert schema is not None
    for point in schema.points_with("x", "y"):
        assert point.channel("x") in channels
        assert point.channel("y") in channels
