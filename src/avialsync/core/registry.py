"""Plugin registry and discovery."""

import hashlib
import importlib
import importlib.util
import logging
import sys
import threading
from collections.abc import Iterable
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from types import ModuleType
from typing import Protocol, TypeVar

from avialsync.core.point_edit_sidecar import is_correction_path
from avialsync.core.source import SessionSource, TimeSeriesSource, TriggerSource, VideoSource

logger = logging.getLogger(__name__)


class _Capability(Protocol):
    """What every scored plugin has in common: it can rate a path."""

    @classmethod
    def can_open(cls, path: Path) -> float: ...


#: Any capability-scored plugin class: a loader or a session scanner.
_T = TypeVar("_T", bound=type[_Capability])

#: The entry-point groups this application publishes and reads.
_ENTRY_POINT_GROUPS: tuple[str, ...] = (
    "avialsync.loaders",
    "avialsync.sessions",
    "avialsync.triggers",
)

#: The built-in loaders, as ``(module, class name)``, in discovery order.
#: Named rather than imported at the top of ``_discover`` so each one can fail
#: alone: a loader's third-party dependency is the user's environment, not ours,
#: and ``neo`` importing a ``quantities`` too old for the installed NumPy is a
#: real report. The registry is built in ``MainWindow.__init__``, so a plain
#: import block turned that into a traceback before any window existed.
_BUILTIN_LOADERS: tuple[tuple[str, str], ...] = (
    ("avialsync.loaders.aol_encoder_loader", "AOLEncoderLoader"),
    ("avialsync.loaders.aol_eks_loader", "AOLEksLoader"),
    ("avialsync.loaders.aol_metric_loader", "AOLMetricLoader"),
    ("avialsync.loaders.aol_video_extraction_loader", "AOLVideoExtractionLoader"),
    ("avialsync.loaders.csv_loader", "CSVLoader"),
    ("avialsync.loaders.video_standard", "VideoStandardLoader"),
    ("avialsync.loaders.tracking_loader", "TrackingLoader"),
    ("avialsync.loaders.neo_loader", "NeoLoader"),
)

#: The built-in trigger providers. A third kind beside loaders and sessions,
#: because trigger evidence answers a different question: not what was recorded
#: but when things happened, and what those instants are evidence *of*.
_BUILTIN_TRIGGERS: tuple[tuple[str, str], ...] = (
    ("avialsync.loaders.trigger_csv", "TriggerCSVSource"),
)

#: The built-in session scanners, in the same form and for the same reason.
_BUILTIN_SESSIONS: tuple[tuple[str, str], ...] = (
    ("avialsync.loaders.aol_session_loader", "AOLSessionSource"),
    ("avialsync.loaders.open_ephys_session", "OpenEphysSessionSource"),
)


class LoaderRegistry:
    """Discovers and loads source plugins."""

    def __init__(self, plugin_dirs: Iterable[Path] | None = None) -> None:
        self._loaders: list[type[TimeSeriesSource | VideoSource]] = []
        self._sessions: list[type[SessionSource]] = []
        self._triggers: list[type[TriggerSource]] = []
        #: Plugins that were found but could not be used, as ``(source, reason)``.
        #: A plugin that fails to import is otherwise indistinguishable from one
        #: that was never installed: the format simply does not appear, with
        #: nothing to tell the user why. A log line is not enough — the person
        #: who installed the plugin is not reading the log. `ui/diagnostics.py`
        #: renders this list so **Help → Diagnostics** can answer the question.
        self._plugin_errors: list[tuple[str, str]] = []
        self._plugin_dirs = (
            list(plugin_dirs) if plugin_dirs is not None else self._default_plugin_dirs()
        )
        # Discovery is deferred, not skipped. Importing the built-ins costs
        # ~470 ms on a warm filesystem -- `neo` pulls in scipy and quantities,
        # the AOL loader pulls in h5py -- and this registry used to run all of
        # it inside `MainWindow.__init__`, which is module IO on the UI thread
        # (architecture rule 3). Cold, behind on-access virus scanning, the same
        # work was measured at over four seconds before the window appeared.
        #
        # `_lock` guards the whole discovery, not just the flag: `drop_worker`
        # already queries this registry from a worker thread, so two threads can
        # arrive here at once and must not both import.
        self._discovered = False
        self._lock = threading.Lock()
        self._warmup: threading.Thread | None = None
        #: Entry-point metadata, read on the thread that starts the warm-up.
        #: See `_snapshot_entry_points` for why it is not read on the thread
        #: that uses it.
        self._entry_points: dict[str, list[EntryPoint]] | None = None

    @property
    def plugin_errors(self) -> list[tuple[str, str]]:
        """Plugins that were found but could not be used.

        Reading this is a use of the registry, so it waits for discovery like
        any other accessor -- otherwise Diagnostics would report an empty list
        while the warm-up was still running and say every plugin was fine.
        """
        self.ensure_discovered()
        return self._plugin_errors

    def start_warmup(self) -> None:
        """Begin discovery on a background thread; return immediately.

        Call once, early, from whatever is about to show a window. The first
        real use of the registry blocks on the same lock, so a user who drops a
        file before the warm-up finishes waits for the remainder rather than
        racing it.

        A plain ``threading.Thread`` rather than a ``QThread``: ``core/`` may
        not import PySide6 (architecture rule 2), and this is exactly what
        ``ui/diagnostics.py`` already does for its startup probes.
        """
        with self._lock:
            if self._discovered or self._warmup is not None:
                return
            self._snapshot_entry_points()
            self._warmup = threading.Thread(
                target=self._warm,
                name="avialsync-plugin-discovery",
                daemon=True,
            )
            warmup = self._warmup
        warmup.start()

    def _snapshot_entry_points(self) -> None:
        """Read the installed entry-point metadata on the *calling* thread.

        `importlib.metadata.entry_points()` parses every installed
        distribution's metadata and builds an `EntryPoint` per line. Doing that
        on the warm-up thread segfaulted CPython on a CI runner -- twice, at
        different points in the suite, with the same two stacks: this thread
        inside `entry_points`, the main thread garbage-collecting. Reading the
        metadata here and handing the thread a plain list keeps the expensive
        half -- importing each plugin module, which is the ~470 ms D-095 exists
        to move off the UI thread -- where it belongs, and takes the cheap half
        (measured at 1.5-5 ms per group) back onto the caller's thread.

        Held under `_lock` by its caller. A registry whose warm-up never runs
        (every test that builds one directly) reads the metadata inline in
        `_load_entry_points` instead, as before.
        """
        if self._entry_points is not None:
            return
        self._entry_points = {
            group: list(entry_points(group=group)) for group in _ENTRY_POINT_GROUPS
        }

    def _warm(self) -> None:
        try:
            self.ensure_discovered()
        except Exception:
            # A warm-up that raises would otherwise die silently on its own
            # thread and leave `ensure_discovered` to redo the work later.
            logger.exception("Plugin discovery failed during warm-up")

    def ensure_discovered(self) -> None:
        """Run discovery once, blocking any caller that arrives mid-flight."""
        if self._discovered:
            return
        with self._lock:
            if self._discovered:
                return
            self._discover()
            self._discovered = True

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
        # Fallback for a source checkout whose entry points are not installed.
        # These are peers, not privileged: every one is also declared in
        # pyproject and reachable the same way a third-party loader is.
        self._load_builtins(_BUILTIN_LOADERS, self._loaders)
        self._load_entry_points("avialsync.loaders", self._loaders)

        self._load_builtins(_BUILTIN_SESSIONS, self._sessions)
        self._load_entry_points("avialsync.sessions", self._sessions)

        self._load_builtins(_BUILTIN_TRIGGERS, self._triggers)
        self._load_entry_points("avialsync.triggers", self._triggers)

        for plugin_dir in self._plugin_dirs:
            self._discover_directory(plugin_dir)

    def _load_builtins(self, specs: tuple[tuple[str, str], ...], into: list[_T]) -> None:
        """Add each built-in class in *specs*, reporting any that will not import.

        A built-in gets the same treatment as a third-party plugin rather than a
        privileged one. Losing one format because its dependency stack is broken
        is a degraded application; losing startup is no application at all, and
        the traceback names ``LoaderRegistry`` instead of the loader at fault.
        """
        for module_name, class_name in specs:
            try:
                into.append(getattr(importlib.import_module(module_name), class_name))
            except Exception as error:  # noqa: BLE001 - a loader's dependencies are third-party
                logger.warning("Built-in loader %s failed to load: %s", class_name, error)
                self._plugin_errors.append((class_name, f"{type(error).__name__}: {error}"))

    def _load_entry_points(self, group: str, into: list[_T]) -> None:
        """Add every class published under *group*, skipping ones that fail.

        Deduplicates by class identity, so a built-in that is also declared as
        an entry point is registered once.

        Reads the snapshot `start_warmup` took when there is one, so this
        thread never builds `EntryPoint` objects itself (`_snapshot_entry_points`).
        """
        snapshot = self._entry_points
        published = snapshot.get(group) if snapshot is not None else None
        if published is None:
            published = list(entry_points(group=group))
        for ep in published:
            try:
                plugin_cls = ep.load()
            except Exception as error:  # noqa: BLE001 - plugin boundary, as in _load_module
                # A broken third-party plugin must be diagnosable. Silently
                # continuing made it vanish with no way to tell why.
                logger.warning("%s entry point %r failed to load: %s", group, ep.name, error)
                self._plugin_errors.append(
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
                self._plugin_errors.append((path.name, error or "could not be imported"))
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
                self._plugin_errors.append(
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
                self._plugin_errors.append(
                    (candidate.__name__, f"can_open raised {type(error).__name__}: {error}")
                )
                continue
            if score > best_score:
                best_score = score
                best = candidate
        return best

    def find_best_loader(self, path: Path) -> type[TimeSeriesSource | VideoSource] | None:
        """Return the loader with the highest can_open() score > 0.

        Our own corrections sidecars are excluded here rather than in each
        loader: a ``.avialfix.csv`` is a perfectly well-formed CSV, so the
        generic CSV loader claims it on extension alone and offers to import
        the user's hand corrections back as a time series beside the pose file
        they belong to (D-099). One place, so a plugin cannot reintroduce it.
        """
        self.ensure_discovered()
        if is_correction_path(path):
            return None
        return self._best_by_capability(self._loaders, path, "loader")

    def find_best_session(self, path: Path) -> type[SessionSource] | None:
        """Return the session scanner claiming *path*, if any.

        Asked before per-file resolution so a folder that *is* a recording is
        laid out by whatever understands it, rather than swept for loose files.
        """
        self.ensure_discovered()
        return self._best_by_capability(self._sessions, path, "session")

    def loaders(self) -> list[type[TimeSeriesSource | VideoSource]]:
        """Return all discovered source loaders."""
        self.ensure_discovered()
        return list(self._loaders)

    def sessions(self) -> list[type[SessionSource]]:
        """Return all discovered session scanners."""
        self.ensure_discovered()
        return list(self._sessions)

    def triggers(self) -> list[type[TriggerSource]]:
        """Return all discovered trigger providers."""
        self.ensure_discovered()
        return list(self._triggers)

    def trigger_for(self, path: Path) -> type[TriggerSource] | None:
        """The provider most confident it can read *path* as trigger evidence."""
        self.ensure_discovered()
        return self._best_by_capability(self._triggers, path, "trigger")
