"""Plugin registry and discovery."""

import importlib.util
from collections.abc import Iterable
from importlib.metadata import entry_points
from pathlib import Path
from types import ModuleType

from avialview.core.source import TimeSeriesSource, VideoSource


class LoaderRegistry:
    """Discovers and loads source plugins."""

    def __init__(self, plugin_dirs: Iterable[Path] | None = None) -> None:
        self._loaders: list[type[TimeSeriesSource | VideoSource]] = []
        self._plugin_dirs = (
            list(plugin_dirs) if plugin_dirs is not None else self._default_plugin_dirs()
        )
        self._discover()

    @staticmethod
    def _default_plugin_dirs() -> list[Path]:
        """Return supported loose-plugin directories, in discovery order."""
        return [Path.home() / ".avialview" / "plugins"]

    def _discover(self) -> None:
        """Find all loaders in the avialview.loaders entry point group."""
        from avialview.loaders.csv_loader import CSVLoader
        from avialview.loaders.neo_loader import NeoLoader
        from avialview.loaders.tracking_loader import TrackingLoader
        from avialview.loaders.video_standard import VideoStandardLoader

        self._loaders = [CSVLoader, VideoStandardLoader, TrackingLoader, NeoLoader]

        eps = entry_points(group="avialview.loaders")
        for ep in eps:
            try:
                plugin_cls = ep.load()
                if plugin_cls not in self._loaders:
                    self._loaders.append(plugin_cls)
            except (ImportError, AttributeError, TypeError):
                continue

        for plugin_dir in self._plugin_dirs:
            self._discover_directory(plugin_dir)

    def _discover_directory(self, plugin_dir: Path) -> None:
        """Load source classes exported by loose ``*.py`` plugin modules."""
        if not plugin_dir.is_dir():
            return
        for path in plugin_dir.glob("*.py"):
            if path.name.startswith("_"):
                continue
            module = self._load_module(path)
            if module is None:
                continue
            for candidate in vars(module).values():
                if (
                    isinstance(candidate, type)
                    and candidate not in (TimeSeriesSource, VideoSource)
                    and issubclass(candidate, (TimeSeriesSource, VideoSource))
                    and candidate not in self._loaders
                ):
                    self._loaders.append(candidate)

    @staticmethod
    def _load_module(path: Path) -> ModuleType | None:
        """Import one loose plugin module without adding its directory to ``sys.path``."""
        module_name = f"avialview_plugin_{path.stem}_{abs(hash(path.resolve()))}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except (ImportError, OSError, SyntaxError):
            return None
        return module

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
