from pathlib import Path
from unittest.mock import MagicMock, patch

from kinochronix.core.registry import LoaderRegistry
from kinochronix.core.source import TimeSeriesSource, VideoSource


class DummyTimeSeriesLoader(TimeSeriesSource):
    @classmethod
    def can_open(cls, path: Path) -> float:
        if path.suffix == ".dummy_ts":
            return 0.9
        return 0.0

    def open(self, path, config):
        pass

    def channels(self):
        return []

    def read_chunks(self, ch):
        yield from []


class DummyVideoLoader(VideoSource):
    @classmethod
    def can_open(cls, path: Path) -> float:
        if path.suffix == ".dummy_vid":
            return 0.95
        return 0.0

    def open(self, path, config):
        pass

    def needs_conversion(self):
        return False

    def prepare(self, cb):
        return Path()

    def media_path(self):
        return Path()

    def start_time(self):
        return 0.0

    def time_bounds(self):
        return 0.0, 1.0

    def frame_times(self):
        return None

    def fps(self):
        return 30.0

    def label(self):
        return "cam"


@patch("kinochronix.core.registry.entry_points")
def test_loader_discovery(mock_eps):
    # Mock entry points return
    ep1 = MagicMock()
    ep1.load.return_value = DummyTimeSeriesLoader

    ep2 = MagicMock()
    ep2.load.return_value = DummyVideoLoader

    mock_eps.return_value = [ep1, ep2]

    registry = LoaderRegistry()
    # Expect 4 built-in + 2 from entry points
    assert len(registry._loaders) == 6
    assert DummyTimeSeriesLoader in registry._loaders
    assert DummyVideoLoader in registry._loaders

    # Test best loader routing
    best_ts = registry.find_best_loader(Path("data.dummy_ts"))
    assert best_ts is DummyTimeSeriesLoader

    best_vid = registry.find_best_loader(Path("movie.dummy_vid"))
    assert best_vid is DummyVideoLoader

    best_none = registry.find_best_loader(Path("unknown.xyz"))
    assert best_none is None
