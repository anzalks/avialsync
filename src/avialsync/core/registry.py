"""Plugin registry and discovery."""

import hashlib
import importlib.util
import logging
import sys
from collections.abc import Iterable
from importlib.metadata import entry_points
from pathlib import Path
from types import ModuleType
from typing import Protocol, TypeVar

from avialsync.core.source import SessionSource, TimeSeriesSource, VideoSource

logger = logging.getLogger(__name__)


class _Capability(Protocol):
    """What every scored plugin has in common: it can rate a path."""

    @classmethod
    def can_open(cls, path: Path) -> float: ...


#: Any capability-scored plugin class: a loader or a session scanner.
_T = TypeVar("_T", bound=type[_Capability])


class LoaderRegistry:
    """Discovers and loads source plugins."""

    def __init__(self, plugin_dirs: Iterable[Path] | None = None) -> None:
        self._loaders: list[type[TimeSeriesSource | VideoSource]] = []
        #: Plugins that were found but could not be used, as ``(source, reason)``.
        #: A plugin that fails to import is otherwise indistinguishable from one
        #: that was never installed: the format simply does not appear, with
        #: nothing to tell the user why. A log line is not enough — the person
        #: who installed the plugin is not reading the log. `ui/diagnostics.py`
        #: renders this list so **Help → Diagnostics** can answer the question.
        self.plugin_errors: list[tuple[str, str]] = []
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
        dirs = [Path.home() / ".avialsync" / "plugins"]

        frozen_root = getattr(sys, "_MEIPASS", None)
        if frozen_root:
            dirs.append(Path(frozen_root) / "examples" / "plugins")
        else:
            # src/avialsync/core/registry.py -> repository root
            repo_root = Path(__file__).resolve().parents[3]
            dirs.append(repo_root / "examples" / "plugins")

        return dirs

    def _discover(self) -> None:
        """Find loaders and session scanners in their entry point groups."""
        from avialsync.loaders.aol_eks_loader import AOLEksLoader
        from avialsync.loaders.aol_encoder_loader import AOLEncoderLoader
        from avialsync.loaders.csv_loader import CSVLoader
        from avialsync.loaders.neo_loader import NeoLoader
        from avialsync.loaders.tracking_loader import TrackingLoader
        from avialsync.loaders.video_standard import VideoStandardLoader

        # Fallback for a source checkout whose entry points are not installed.
        # These are peers, not privileged: every one is also declared in
        # pyproject and reachable the same way a third-party loader is.
        self._loaders = [
            AOLEncoderLoader,
            AOLEksLoader,
            CSVLoader,
            VideoStandardLoader,
            TrackingLoader,
            NeoLoader,
        ]
        self._load_entry_points("avialsync.loaders", self._loaders)

        from avialsync.loaders.aol_session_loader import AOLSessionSource

        self._sessions: list[type[SessionSource]] = [AOLSessionSource]
        self._load_entry_points("avialsync.sessions", self._sessions)

        for plugin_dir in self._plugin_dirs:
            self._discover_directory(plugin_dir)

    def _load_entry_points(self, group: str, into: list) -> None:
        """Add every class published under *group*, skipping ones that fail.

        Deduplicates by class identity, so a built-in that is also declared as
        an entry point is registered once.
        """
        for ep in entry_points(group=group):
            try:
                plugin_cls = ep.load()
            except Exception as error:  # noqa: BLE001 - plugin boundary, as in _load_module
                # A broken third-party plugin must be diagnosable. Silently
                # continuing made it vanish with no way to tell why.
                logger.warning("%s entry point %r failed to load: %s", group, ep.name, error)
                self.plugin_errors.append(
                    (f"entry point {ep.name!r}", f"{type(error).__name__}: {error}")
                )
                continue
            if plugin_cls not in into:
                into.append(plugin_cls)

    def _discover_directory(self, plugin_dir: Path) -> None:
        """Load source classes exported by loose ``*.py`` plugin modules."""
        if not plugin_dir.is_dir():
            return
        for path in sorted(plugin_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            module, error = self._load_module(path)
            if module is None:
                self.plugin_errors.append((path.name, error or "could not be imported"))
                continue
            exported = 0
            for candidate in vars(module).values():
                if not isinstance(candidate, type):
                    continue
                if (
                    candidate not in (TimeSeriesSource, VideoSource)
                    and issubclass(candidate, (TimeSeriesSource, VideoSource))
                    and candidate not in self._loaders
                ):
                    self._loaders.append(candidate)
                    exported += 1
                elif (
                    candidate is not SessionSource
                    and issubclass(candidate, SessionSource)
                    and candidate not in self._sessions
                ):
                    self._sessions.append(candidate)
                    exported += 1
            if exported == 0:
                logger.warning(
                    "Plugin %s exported no TimeSeriesSource, VideoSource, or SessionSource "
                    "subclass.",
                    path.name,
                )
                self.plugin_errors.append(
                    (
                        path.name,
                        "exported no TimeSeriesSource, VideoSource, or SessionSource subclass",
                    )
                )

    @staticmethod
    def _load_module(path: Path) -> tuple[ModuleType | None, str | None]:
        """Import one loose plugin module without adding its directory to ``sys.path``.

        Returns ``(module, None)`` on success and ``(None, reason)`` on failure,
        so the caller can report *why* a plugin is missing rather than only that
        it is.

        The generated module name is derived from a SHA-1 of the resolved path
        rather than ``hash()``.  Python salts ``hash()`` per process, so the same
        plugin file produced a different module name on every launch, which made
        bundle contents and any error naming that module irreproducible.
        """
        digest = hashlib.sha1(
            str(path.resolve()).encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:12]
        module_name = f"avialsync_plugin_{path.stem}_{digest}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning("Plugin %s could not be turned into an import spec.", path)
            return None, "not importable as a Python module"
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as error:  # noqa: BLE001 - plugin boundary, see below
            # Deliberately broad, and one of the few places that is correct.
            # Executing a plugin module runs arbitrary third-party code, which
            # can raise literally anything. A narrower tuple let a plugin
            # raising, say, RuntimeError at import propagate out of __init__ —
            # and the registry is built inside MainWindow.__init__, so one bad
            # plugin file took down application startup. This is a catch, not a
            # silence: the reason is returned, logged, and shown in Diagnostics.
            logger.warning("Plugin %s failed to import: %s", path.name, error)
            return None, f"{type(error).__name__}: {error}"
        return module, None

    def _best_by_capability(self, candidates: list[_T], path: Path, kind: str) -> _T | None:
        """Return the candidate scoring highest above zero on *path*.

        ``can_open`` is third-party code running on every dropped path. One
        plugin raising there must cost only that plugin, not the whole drop:
        the alternative is a rig-specific plugin making the application unable
        to open anything at all.
        """
        best_score = 0.0
        best = None
        for candidate in candidates:
            try:
                score = candidate.can_open(path)
            except Exception as error:  # noqa: BLE001 - plugin boundary
                logger.warning("%s %s.can_open failed: %s", kind, candidate.__name__, error)
                self.plugin_errors.append(
                    (candidate.__name__, f"can_open raised {type(error).__name__}: {error}")
                )
                continue
            if score > best_score:
                best_score = score
                best = candidate
        return best

    def find_best_loader(self, path: Path) -> type[TimeSeriesSource | VideoSource] | None:
        """Return the loader with the highest can_open() score > 0."""
        return self._best_by_capability(self._loaders, path, "loader")

    def find_best_session(self, path: Path) -> type[SessionSource] | None:
        """Return the session scanner claiming *path*, if any.

        Asked before per-file resolution so a folder that *is* a recording is
        laid out by whatever understands it, rather than swept for loose files.
        """
        return self._best_by_capability(self._sessions, path, "session")

    def loaders(self) -> list[type[TimeSeriesSource | VideoSource]]:
        """Return all discovered source loaders."""
        return list(self._loaders)

    def sessions(self) -> list[type[SessionSource]]:
        """Return all discovered session scanners."""
        return list(self._sessions)
