from pathlib import Path

import pytest

from avialsync.loaders.tracking_loader import TrackingLoader


def test_loader():
    path = Path("tests/fixtures/signals/tracking_dlc.csv")

    loader = TrackingLoader()
    print("can_open:", loader.can_open(path))

    loader.open(path, {"fps": 30.0})
    print("channels:", [ch.name for ch in loader.channels()])

    chunks = list(loader.read_chunks("nose_x"))
    for t, v in chunks:
        print("chunk t:", t[:5], "v:", v[:5])
        break


if __name__ == "__main__":
    test_loader()


def test_loader_exposes_3d_coordinate_triplets(tmp_path: Path) -> None:
    path = tmp_path / "tracking_3d.csv"
    path.write_text(
        "\n".join(
            [
                "scorer,DLC,DLC,DLC,DLC",
                "bodyparts,nose,nose,nose,nose",
                "coords,x,y,z,likelihood",
                "0,1.0,2.0,3.0,0.99",
                "1,4.0,5.0,6.0,0.98",
            ]
        ),
        encoding="utf-8",
    )

    loader = TrackingLoader()
    loader.open(path, {"fps": 20.0})

    assert [channel.name for channel in loader.channels()] == [
        "nose_x",
        "nose_y",
        "nose_z",
        "nose_likelihood",
    ]
    times, values = next(loader.read_chunks("nose_z"))
    assert times.tolist() == [0.0, 0.05]
    assert values.tolist() == [3.0, 6.0]


def test_loader_bulk_api_yields_every_coordinate_from_one_batch(tmp_path: Path) -> None:
    path = tmp_path / "tracking.csv"
    path.write_text(
        "\n".join(
            [
                "scorer,DLC,DLC",
                "bodyparts,nose,nose",
                "coords,x,y",
                "0,1.0,2.0",
                "1,3.0,4.0",
            ]
        ),
        encoding="utf-8",
    )
    loader = TrackingLoader()
    loader.open(path, {"fps": 10.0})

    batch = next(loader.read_all_chunks())

    assert sorted(batch) == ["nose_x", "nose_y"]
    assert batch["nose_x"][0].tolist() == [0.0, 0.1]
    assert batch["nose_y"][1].tolist() == [2.0, 4.0]


MULTI_ANIMAL = [
    "scorer,DLC,DLC,DLC,DLC,DLC,DLC,DLC,DLC,DLC",
    "individuals,testMouse,testMouse,testMouse,conSpecific,conSpecific,conSpecific,"
    "single,single,single",
    "bodyparts,snout,snout,snout,snout,snout,snout,corner,corner,corner",
    "coords,x,y,likelihood,x,y,likelihood,x,y,likelihood",
    "0,1.0,2.0,0.9,3.0,4.0,0.8,5.0,6.0,0.7",
    "1,7.0,8.0,0.9,,,0.0,11.0,12.0,0.7",
]


def _write_multi_animal(tmp_path: Path) -> Path:
    path = tmp_path / "tracking_madlc.csv"
    path.write_text("\n".join(MULTI_ANIMAL) + "\n", encoding="utf-8")
    return path


def test_loader_claims_a_multi_animal_export(tmp_path: Path) -> None:
    assert TrackingLoader.can_open(_write_multi_animal(tmp_path)) == 1.0


def test_loader_keeps_each_animal_s_body_parts_apart(tmp_path: Path) -> None:
    """Two mice both have a ``snout``; they must not become one channel."""
    loader = TrackingLoader()
    loader.open(_write_multi_animal(tmp_path), {"fps": 10.0, "coords": ["x", "y"]})

    assert [channel.name for channel in loader.channels()] == [
        "testMouse_snout_x",
        "testMouse_snout_y",
        "conSpecific_snout_x",
        "conSpecific_snout_y",
        "single_corner_x",
        "single_corner_y",
    ]
    batch = next(loader.read_all_chunks())
    assert batch["testMouse_snout_x"][1].tolist() == [1.0, 7.0]
    assert batch["conSpecific_snout_x"][1][0] == 3.0


def test_loader_reads_an_untracked_frame_as_nan_not_zero(tmp_path: Path) -> None:
    """``0,0`` is the top-left corner of the image; a missing point is not there."""
    import math

    loader = TrackingLoader()
    loader.open(_write_multi_animal(tmp_path), {"fps": 10.0, "coords": ["x", "y"]})

    batch = next(loader.read_all_chunks())
    assert math.isnan(batch["conSpecific_snout_x"][1][1])


def test_loader_rejects_a_csv_with_no_pose_header(tmp_path: Path) -> None:
    from avialsync.core.errors import SourceOpenError

    path = tmp_path / "signal.csv"
    path.write_text("time,voltage\n0.0,1.0\n", encoding="utf-8")

    assert TrackingLoader.can_open(path) == 0.0
    with pytest.raises(SourceOpenError):
        TrackingLoader().open(path, {"fps": 30.0})
