from pathlib import Path

from avialview.loaders.tracking_loader import TrackingLoader


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
