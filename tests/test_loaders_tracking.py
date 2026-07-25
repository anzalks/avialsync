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
