"""Plugin registry and discovery."""

import dataclasses
import hashlib
import importlib
import importlib.util
import inspect
import logging
import sys
import threading
from collections.abc import Iterable
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from types import ModuleType
from typing import Protocol, TypeVar

from avialsync.core.custom_markers import is_custom_marker_path
from avialsync.core.identity_sidecar import is_swap_path
from avialsync.core.point_edit_sidecar import is_correction_path
from avialsync.core.prop_file import is_prop_path
from avialsync.core.settings_schema import Setting
from avialsync.core.source import (
    PLUGIN_API_VERSION,
    ImagingSource,
    SessionSource,
    TimeSeriesSource,
    TriggerSource,
    VideoSource,
)

logger = logging.getLogger(__name__)


def is_own_sidecar(path: Path | str) -> bool:
    """Return whether *path* is a file AvialSync writes beside a recording.

    The one list every filter consults. Each of these is a well-formed CSV or
    TOML that a generic loader claims on extension alone, and listing them at
    each call site is how the identity-swap sidecar came to be offered back as a
    time series: two filters named three of the four.
    """
    return (
        is_correction_path(path)
        or is_swap_path(path)
        or is_custom_marker_path(path)
        or is_prop_path(path)
    )


class _Capability(Protocol):
    """What every scored plugin has in common: it can rate a path."""

    @classmethod
    def can_open(cls, path: Path) -> float: ...


#: Any capability-scored plugin class: a loader or a session scanner.
_T = TypeVar("_T", bound=type[_Capability])

#: The entry-point groups this application publishes and reads. Trigger lines
#: are declared on a loader's channels (``ChannelInfo.trigger``, D-220), so
#: there is no third group: a trigger file is just another recording.
_ENTRY_POINT_GROUPS: tuple[str, ...] = (
    "avialsync.loaders",
    "avialsync.sessions",
)

#: Inside the drop-in folder: pure-Python libraries a drop-in needs and the
#: installed application does not bundle, put there with
#: ``pip install --target ~/.avialsync/plugins/lib <package>``.
LIB_DIR_NAME = "lib"

#: Module-name prefix of a drop-in plugin, imported from a file, not a package.
_DROP_IN_PREFIX = "avialsync_plugin_"

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
    ("avialsync.loaders.aol_camera_join", "AOLJoinedCameraSource"),
    ("avialsync.loaders.joined_parts", "JoinedVideoSource"),
    ("avialsync.loaders.tracking_loader", "TrackingLoader"),
    ("avialsync.loaders.vicon_c3d_loader", "ViconC3DLoader"),
    ("avialsync.loaders.joined_parts", "JoinedTimeSeriesSource"),
    ("avialsync.loaders.neo_loader", "NeoLoader"),
    ("avialsync.loaders.nwb_loader", "NWBLoader"),
    ("avialsync.loaders.nwb_imaging", "NWBImagingSource"),
    ("avialsync.loaders.nwb_stack", "NWBStackSource"),
    ("avialsync.loaders.nwb_roi_grid", "NWBRoiGridSource"),
    ("avialsync.loaders.imaging_loader", "HDF5ImagingLoader"),
    ("avialsync.loaders.aol_ribbon_scan", "AOLRibbonScanSource"),
    ("avialsync.loaders.aol_trial_encoder", "AOLTrialEncoderSource"),
    ("avialsync.loaders.imaging_loader", "TIFFImagingLoader"),
)

#: The trigger-file reader behind **Align → Open Trigger Evidence**. Built in
#: and not a plugin kind: a plugin declares trigger lines on its channels.
_BUILTIN_TRIGGERS: tuple[tuple[str, str], ...] = (
    ("avialsync.loaders.trigger_csv", "TriggerCSVSource"),
)

#: The built-in session scanners, in the same form and for the same reason.
_BUILTIN_SESSIONS: tuple[tuple[str, str], ...] = (
    ("avialsync.loaders.aol_session_loader", "AOLSessionSource"),
    ("avialsync.loaders.aol_microscope_session", "AOLMicroscopeTrialSource"),
    ("avialsync.loaders.open_ephys_session", "OpenEphysSessionSource"),
    ("avialsync.loaders.vicon_session_loader", "ViconSessionSource"),
    ("avialsync.loaders.nwb_session", "NWBSessionSource"),
)


class LoaderRegistry:
    """Discovers and loads source plugins."""

    def __init__(self, plugin_dirs: Iterable[Path] | None = None) -> None:
        self._loaders: list[type[TimeSeriesSource | VideoSource | ImagingSource]] = []
        self._sessions: list[type[SessionSource]] = []
        self._triggers: list[type[TriggerSource]] = []
        #: Plugins that were found but could not be used, as ``(source, reason)``.
        #: A plugin that fails to import is otherwise indistinguishable from one
        #: that was never installed: the format simply does not appear, with
        #: nothing to tell the user why. A log line is not enough — the person
        #: who installed the plugin is not reading the log. `ui/diagnostics.py`
        #: renders this list so **Help → Diagnostics** can answer the question.
        self._plugin_errors: list[tuple[str, str]] = []
        #: Plugins the user switched off, by :func:`plugin_key`. Still listed,
        #: never asked.
        self._disabled: set[str] = set()
        #: Where each discovered class came from, for Diagnostics.
        self._origins: dict[type, str] = {}
        #: Bumped whenever the set of usable plugins changes, so a view built
        #: from it (Preferences' plugin tabs) knows to rebuild.
        self.generation = 0
        self._plugin_dirs = (
            list(plugin_dirs) if plugin_dirs is not None else self._default_plugin_dirs()
        )
        # Discovery is deferred, not skipped. Importing the built-ins costs
        # ~470 ms on a warm filesystem -- `neo` pulls in scipy and quantities,
        # the AOL loader pulls in h5py -- and this registry used to run all of
        # it inside `MainWindow.__init__`, which is module IO on the UI thread.
        # Cold, behind on-access virus scanning, the same
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
        not import PySide6, and this is exactly what
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
        on the warm-up thread segfaulted CPython, with the same two stacks each
        time: this thread inside `entry_points`, the main thread
        garbage-collecting. Reading the
        metadata here and handing the thread a plain list keeps the expensive
        half -- importing each plugin module, the ~470 ms that deferred discovery
        moves off the UI thread -- where it belongs, and takes the cheap half
        (measured at 1.5-5 ms per group) back onto the caller's thread.

        Held under `_lock` by its caller. A registry whose warm-up never runs
        (one built directly) reads the metadata inline in
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

        There are two locations: the user's own drop-in folder
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

    def reload(self) -> None:
        """Forget every plugin and discover again, picking up new drop-in files."""
        with self._lock:
            self._loaders.clear()
            self._sessions.clear()
            self._triggers.clear()
            self._plugin_errors.clear()
            self._origins.clear()
            self._entry_points = None
            self._discover()
            self._discovered = True
            self.generation += 1

    def set_disabled(self, keys: Iterable[str]) -> None:
        """Switch off the plugins named by :func:`plugin_key`; the rest stay on."""
        self._disabled = set(keys)
        self.generation += 1

    def is_enabled(self, plugin: type) -> bool:
        return plugin_key(plugin) not in self._disabled

    def plugins(self) -> list[tuple[str, type, str]]:
        """Every discovered plugin as ``(kind, class, origin)``, enabled or not."""
        self.ensure_discovered()
        found: list[tuple[str, type, str]] = [
            ("loader", cls, self._origins.get(cls, "")) for cls in self._loaders
        ]
        found += [("session", cls, self._origins.get(cls, "")) for cls in self._sessions]
        return found

    def plugin_settings(self) -> list[Setting]:
        """Every enabled plugin's declared settings, namespaced and grouped by plugin.

        Plugins sharing a :meth:`plugin_id` share their settings; each key is
        listed once.
        """
        seen: set[str] = set()
        namespaced: list[Setting] = []
        for _kind, cls, _origin in self.plugins():
            if not self.is_enabled(cls):
                continue
            for setting in _declared_settings(cls):
                key = plugin_setting_key(cls, setting.key)
                if key in seen:
                    continue
                seen.add(key)
                namespaced.append(
                    dataclasses.replace(setting, key=key, group=setting.group or _group_of(cls))
                )
        return namespaced

    def configure_plugins(self, values: dict[str, object]) -> None:
        """Hand each plugin its settings' values, keyed by its own keys.

        *values* is keyed by the namespaced key :meth:`plugin_settings` gives.
        A plugin whose ``configure`` raises is reported, not fatal.
        """
        for _kind, cls, _origin in self.plugins():
            declared = _declared_settings(cls)
            if not declared:
                continue
            own = {
                setting.key: values.get(plugin_setting_key(cls, setting.key), setting.default)
                for setting in declared
            }
            try:
                cls.configure(own)  # type: ignore[attr-defined]
            except Exception as error:  # noqa: BLE001 - plugin boundary
                logger.warning("%s.configure failed: %s", cls.__name__, error)
                self._plugin_errors.append(
                    (cls.__name__, f"configure raised {type(error).__name__}: {error}")
                )

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

        for plugin_dir in self._plugin_dirs:
            self._discover_directory(plugin_dir)

    def _admit(self, plugin: type, into: list[_T], origin: str) -> bool:
        """Add *plugin* unless it is already there or targets another API version."""
        if plugin in into:
            return False
        version = getattr(plugin, "api_version", PLUGIN_API_VERSION)
        if version != PLUGIN_API_VERSION:
            name = getattr(plugin, "__name__", str(plugin))
            logger.warning("%s targets plugin API %s, not %s", name, version, PLUGIN_API_VERSION)
            self._plugin_errors.append(
                (
                    name,
                    f"written for plugin API {version}; this AvialSync implements "
                    f"API {PLUGIN_API_VERSION}",
                )
            )
            return False
        into.append(plugin)  # type: ignore[arg-type]
        self._origins[plugin] = origin
        return True

    def _load_builtins(self, specs: tuple[tuple[str, str], ...], into: list[_T]) -> None:
        """Add each built-in class in *specs*, reporting any that will not import.

        A built-in gets the same treatment as a third-party plugin rather than a
        privileged one. Losing one format because its dependency stack is broken
        is a degraded application; losing startup is no application at all, and
        the traceback names ``LoaderRegistry`` instead of the loader at fault.
        """
        for module_name, class_name in specs:
            try:
                self._admit(
                    getattr(importlib.import_module(module_name), class_name), into, "built in"
                )
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
            self._admit(plugin_cls, into, f"package {ep.value.split(':')[0].split('.')[0]}")

    def _discover_directory(self, plugin_dir: Path) -> None:
        """Load source classes from drop-in modules: ``name.py`` or a ``name/`` package.

        Works the same in an installed application as from source: the
        modules are executed by the application's own interpreter, so they may
        import anything it bundles, plus whatever sits in ``lib/`` beside them.
        """
        if not plugin_dir.is_dir():
            return
        _add_lib_dir(plugin_dir / LIB_DIR_NAME)
        modules = [path for path in plugin_dir.glob("*.py") if path.name != "__init__.py"]
        modules += [
            path / "__init__.py"
            for path in plugin_dir.iterdir()
            if path.is_dir() and path.name != LIB_DIR_NAME and (path / "__init__.py").is_file()
        ]
        for path in sorted(modules):
            shown = path.parent.name if path.name == "__init__.py" else path.name
            if shown.startswith("_"):
                continue
            module, error = self._load_module(path)
            if module is None:
                self._plugin_errors.append((shown, error or "could not be imported"))
                continue
            exported = 0
            for candidate in vars(module).values():
                if not isinstance(candidate, type):
                    continue
                if not str(getattr(candidate, "__module__", "")).startswith(module.__name__):
                    continue  # imported into the module, not defined by it
                if inspect.isabstract(candidate):
                    continue
                if issubclass(candidate, (TimeSeriesSource, VideoSource, ImagingSource)):
                    exported += 1
                    self._admit(candidate, self._loaders, f"drop-in {shown}")
                elif issubclass(candidate, SessionSource):
                    exported += 1
                    self._admit(candidate, self._sessions, f"drop-in {shown}")
            if exported == 0:
                logger.warning(
                    "Plugin %s exported no TimeSeriesSource, VideoSource, or SessionSource "
                    "subclass (nor ImagingSource).",
                    shown,
                )
                self._plugin_errors.append(
                    (
                        shown,
                        "exported no TimeSeriesSource, VideoSource, or SessionSource "
                        "subclass (nor ImagingSource)",
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
        package = path.name == "__init__.py"
        stem = path.parent.name if package else path.stem
        module_name = f"{_DROP_IN_PREFIX}{stem}_{digest}"
        spec = importlib.util.spec_from_file_location(
            module_name,
            path,
            submodule_search_locations=[str(path.parent)] if package else None,
        )
        if spec is None or spec.loader is None:
            logger.warning("Plugin %s could not be turned into an import spec.", path)
            return None, "not importable as a Python module"
        module = importlib.util.module_from_spec(spec)
        # Registered before executing, as a normal import does, so a package's
        # relative imports (`from .reader import X`) resolve.
        sys.modules[module_name] = module
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
            sys.modules.pop(module_name, None)
            logger.warning("Plugin %s failed to import: %s", path.name, error)
            return None, f"{type(error).__name__}: {error}"
        return module, None

    def _best_by_capability(self, candidates: list[_T], path: Path, kind: str) -> _T | None:
        """Return the candidate scoring highest above zero on *path*.

        On a tie, the first registered: callers that can ask the user use
        :meth:`tied_loaders` / :meth:`tied_sessions` to find out there was one.
        """
        tied = self._top_scorers(candidates, path, kind)
        return tied[0] if tied else None

    def _top_scorers(self, candidates: list[_T], path: Path, kind: str) -> list[_T]:
        """Every enabled candidate sharing the highest score above zero on *path*.

        ``can_open`` is third-party code running on every dropped path. One
        plugin raising there must cost only that plugin, not the whole drop:
        the alternative is a rig-specific plugin making the application unable
        to open anything at all.
        """
        best_score = 0.0
        best: list[_T] = []
        for candidate in candidates:
            if not self.is_enabled(candidate):
                continue
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
                best = [candidate]
            elif score == best_score and score > 0.0:
                best.append(candidate)
        return best

    def tied_loaders(
        self,
        path: Path,
        kind: type[TimeSeriesSource] | type[VideoSource] | type[ImagingSource] | None = None,
    ) -> list[type[TimeSeriesSource | VideoSource | ImagingSource]]:
        """The loaders sharing the top score on *path*, when more than one does."""
        self.ensure_discovered()
        if is_own_sidecar(path):
            return []
        candidates = (
            self._loaders
            if kind is None
            else [loader for loader in self._loaders if issubclass(loader, kind)]
        )
        tied = self._top_scorers(candidates, path, "loader")
        return tied if len(tied) > 1 else []

    def tied_sessions(self, path: Path) -> list[type[SessionSource]]:
        """The session scanners sharing the top score on *path*, when more than one does."""
        self.ensure_discovered()
        tied = self._top_scorers(self._sessions, path, "session")
        return tied if len(tied) > 1 else []

    def find_best_loader(
        self,
        path: Path,
        kind: type[TimeSeriesSource] | type[VideoSource] | type[ImagingSource] | None = None,
    ) -> type[TimeSeriesSource | VideoSource | ImagingSource] | None:
        """Return the loader with the highest can_open() score > 0.

        *kind* limits the answer to time-series or video loaders. One file can
        be both: an NWB file holds its time series and its imaging, and the
        session that opened it records which of the two each source was. Asked
        without a kind, the highest score wins as before.

        Our own corrections sidecars are excluded here rather than in each
        loader: a ``_avialfix.csv`` is a perfectly well-formed CSV, so the
        generic CSV loader claims it on extension alone and offers to import
        the user's hand corrections back as a time series beside the pose file
        they belong to. One place, so a plugin cannot reintroduce it.
        """
        self.ensure_discovered()
        if is_own_sidecar(path):
            return None
        candidates = (
            self._loaders
            if kind is None
            else [loader for loader in self._loaders if issubclass(loader, kind)]
        )
        return self._best_by_capability(candidates, path, "loader")

    def find_best_session(self, path: Path) -> type[SessionSource] | None:
        """Return the session scanner claiming *path*, if any.

        Asked before per-file resolution so a folder that *is* a recording is
        laid out by whatever understands it, rather than swept for loose files.
        """
        self.ensure_discovered()
        return self._best_by_capability(self._sessions, path, "session")

    def loaders(self) -> list[type[TimeSeriesSource | VideoSource | ImagingSource]]:
        """Return all enabled source loaders."""
        self.ensure_discovered()
        return [loader for loader in self._loaders if self.is_enabled(loader)]

    def sessions(self) -> list[type[SessionSource]]:
        """Return all enabled session scanners."""
        self.ensure_discovered()
        return [session for session in self._sessions if self.is_enabled(session)]

    def triggers(self) -> list[type[TriggerSource]]:
        """Return the built-in trigger-file readers."""
        self.ensure_discovered()
        return list(self._triggers)

    def trigger_for(self, path: Path) -> type[TriggerSource] | None:
        """The provider most confident it can read *path* as trigger evidence."""
        self.ensure_discovered()
        return self._best_by_capability(self._triggers, path, "trigger")


def plugin_key(plugin: type) -> str:
    """How a plugin is named in the disabled list: its module and class.

    A drop-in's module name carries a digest of where the file sits; the key
    keeps only the file's own name, so moving the folder keeps the choice.
    """
    module = plugin.__module__
    if module.startswith(_DROP_IN_PREFIX):
        stem, _sep, rest = module[len(_DROP_IN_PREFIX) :].partition(".")
        module = "drop-in." + stem.rsplit("_", 1)[0] + (f".{rest}" if rest else "")
    return f"{module}:{plugin.__qualname__}"


def plugin_setting_key(plugin: type, key: str) -> str:
    """Where a plugin's own setting *key* is stored."""
    return f"plugins/{plugin.plugin_id()}/{key}"  # type: ignore[attr-defined]


def _declared_settings(plugin: type) -> tuple[Setting, ...]:
    try:
        return tuple(plugin.settings())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - plugin boundary
        logger.warning("%s.settings() failed", plugin.__name__, exc_info=True)
        return ()


def _group_of(plugin: type) -> str:
    try:
        return str(plugin.display_name())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - plugin boundary
        return plugin.__name__


def _add_lib_dir(lib: Path) -> None:
    """Make libraries installed into the drop-in ``lib/`` folder importable."""
    if lib.is_dir() and str(lib) not in sys.path:
        sys.path.append(str(lib))
