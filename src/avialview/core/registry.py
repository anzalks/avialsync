"""Plugin registry and discovery."""

import hashlib
import importlib.util
import logging
import sys
from collections.abc import Iterable
from importlib.metadata import entry_points
from pathlib import Path
from types import ModuleType

from avialview.core.source import TimeSeriesSource, VideoSource

logger = logging.getLogger(__name__)


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
        """Return supported loose-plugin directories, in discovery order.

        BLUEPRINT Phase 5 promises two locations: the user's own drop-in folder
        and the bundled ``examples/plugins/``.  In a PyInstaller bundle the
        source tree does not exist, so the bundled directory is resolved from
        ``sys._MEIPASS`` — without it no loose plugin can load from a release
        build at all.
        """
        dirs = [Path.home() / ".avialview" / "plugins"]

        frozen_root = getattr(sys, "_MEIPASS", None)
        if frozen_root:
            dirs.append(Path(frozen_root) / "examples" / "plugins")
        else:
            # src/avialview/core/registry.py -> repository root
            repo_root = Path(__file__).resolve().parents[3]
            dirs.append(repo_root / "examples" / "plugins")

        return dirs

    def _discover(self) -> None:
        """Find all loaders in the avialview.loaders entry point group."""
        from avialview.loaders.aol_eks_loader import AOLEksLoader
        from avialview.loaders.aol_encoder_loader import AOLEncoderLoader
        from avialview.loaders.csv_loader import CSVLoader
        from avialview.loaders.neo_loader import NeoLoader
        from avialview.loaders.tracking_loader import TrackingLoader
        from avialview.loaders.video_standard import VideoStandardLoader

        self._loaders = [
            AOLEncoderLoader,
            AOLEksLoader,
            CSVLoader,
            VideoStandardLoader,
            TrackingLoader,
            NeoLoader,
        ]

        # The built-ins above are also declared as entry points so that a
        # third-party host can enumerate them; loading them again here is a
        # no-op because `not in self._loaders` deduplicates by class identity.
        eps = entry_points(group="avialview.loaders")
        for ep in eps:
            try:
                plugin_cls = ep.load()
            except (ImportError, AttributeError, TypeError) as error:
                # A broken third-party plugin must be diagnosable. Silently
                # continuing made it vanish with no way to tell why.
                logger.warning("Loader entry point %r failed to load: %s", ep.name, error)
                continue
            if plugin_cls not in self._loaders:
                self._loaders.append(plugin_cls)

        for plugin_dir in self._plugin_dirs:
            self._discover_directory(plugin_dir)

    def _discover_directory(self, plugin_dir: Path) -> None:
        """Load source classes exported by loose ``*.py`` plugin modules."""
        if not plugin_dir.is_dir():
            return
        for path in sorted(plugin_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            module = self._load_module(path)
            if module is None:
                continue
            exported = 0
            for candidate in vars(module).values():
                if (
                    isinstance(candidate, type)
                    and candidate not in (TimeSeriesSource, VideoSource)
                    and issubclass(candidate, (TimeSeriesSource, VideoSource))
                    and candidate not in self._loaders
                ):
                    self._loaders.append(candidate)
                    exported += 1
            if exported == 0:
                logger.warning(
                    "Plugin %s exported no TimeSeriesSource or VideoSource subclass.", path.name
                )

    @staticmethod
    def _load_module(path: Path) -> ModuleType | None:
        """Import one loose plugin module without adding its directory to ``sys.path``.

        The generated module name is derived from a SHA-1 of the resolved path
        rather than ``hash()``.  Python salts ``hash()`` per process, so the same
        plugin file produced a different module name on every launch, which made
        bundle contents and any error naming that module irreproducible.
        """
        digest = hashlib.sha1(
            str(path.resolve()).encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:12]
        module_name = f"avialview_plugin_{path.stem}_{digest}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning("Plugin %s could not be turned into an import spec.", path)
            return None
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except (ImportError, OSError, SyntaxError, ValueError, TypeError) as error:
            logger.warning("Plugin %s failed to import: %s", path.name, error)
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

    def loaders(self) -> list[type[TimeSeriesSource | VideoSource]]:
        """Return all discovered source loaders."""
        return list(self._loaders)
