"""Plugin API v1 discovery coverage."""

from pathlib import Path

from kinochronix.core.registry import LoaderRegistry
from kinochronix.core.source import TimeSeriesSource


def test_registry_discovers_loose_time_series_plugin(tmp_path: Path) -> None:
    """A drop-in plugin directory exposes a v1 source to the registry."""
    plugin = tmp_path / "toy_loader.py"
    plugin.write_text(
        """
from collections.abc import Iterator
from pathlib import Path
from typing import Any
import numpy as np
from kinochronix.core.source import ChannelInfo, TimeSeriesSource

class LooseToySource(TimeSeriesSource):
    @classmethod
    def can_open(cls, path: Path) -> float:
        return 1.0 if path.suffix == '.toybin' else 0.0
    def open(self, path: Path, config: dict[str, Any]) -> None:
        self.path = path
    def channels(self) -> list[ChannelInfo]:
        return [ChannelInfo('value', '', 'float64', None)]
    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        yield np.array([0.0]), np.array([1.0])
""".strip(),
        encoding="utf-8",
    )

    loader_class = LoaderRegistry(plugin_dirs=[tmp_path]).find_best_loader(Path("signal.toybin"))

    assert loader_class is not None
    assert issubclass(loader_class, TimeSeriesSource)
    assert loader_class.__name__ == "LooseToySource"
