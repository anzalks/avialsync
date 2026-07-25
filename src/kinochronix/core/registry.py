"""Plugin registry and discovery."""

from importlib.metadata import entry_points
from pathlib import Path

from kinochronix.core.source import TimeSeriesSource, VideoSource


class LoaderRegistry:
    """Discovers and loads source plugins."""

    def __init__(self) -> None:
        self._loaders: list[type[TimeSeriesSource | VideoSource]] = []
        self._discover()

    def _discover(self) -> None:
        """Find all loaders in the kinochronix.loaders entry point group."""
        from kinochronix.loaders.csv_loader import CSVLoader
        from kinochronix.loaders.neo_loader import NeoLoader
        from kinochronix.loaders.tracking_loader import TrackingLoader
        from kinochronix.loaders.video_standard import VideoStandardLoader

        self._loaders = [CSVLoader, VideoStandardLoader, TrackingLoader, NeoLoader]

        eps = entry_points(group="kinochronix.loaders")
        for ep in eps:
            try:
                plugin_cls = ep.load()
                if plugin_cls not in self._loaders:
                    self._loaders.append(plugin_cls)
            except Exception:
                # Silently ignore failed plugins per discovery best practices,
                # or log them if a logger is configured.
                pass

    def find_best_loader(self, path: Path) -> type[TimeSeriesSource | VideoSource] | None:
        """Return the loader with the highest can_open() score > 0."""
        best_score = 0.0
        best_loader = None

        for loader in self._loaders:
            score = loader.can_open(path)
            if score > best_score:
                best_score = score
                best_loader = loader

        return best_loader
