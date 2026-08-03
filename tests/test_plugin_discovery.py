"""Plugin API v1 discovery coverage."""

import logging
from pathlib import Path

from avialsync.core.registry import LoaderRegistry
from avialsync.core.source import TimeSeriesSource


def test_registry_discovers_loose_time_series_plugin(tmp_path: Path) -> None:
    """A drop-in plugin directory exposes a v1 source to the registry."""
    plugin = tmp_path / "toy_loader.py"
    plugin.write_text(
        """
from collections.abc import Iterator
from pathlib import Path
from typing import Any
import numpy as np
from avialsync.core.source import ChannelInfo, TimeSeriesSource

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


# ── Registry hardening (V-10) ─────────────────────────────────────────

_PLUGIN_SOURCE = """
from pathlib import Path
from typing import Any
from collections.abc import Iterator
import numpy as np
from avialsync.core.source import ChannelInfo, TimeSeriesSource


class ToyLoader(TimeSeriesSource):
    @classmethod
    def can_open(cls, path: Path) -> float:
        return 1.0 if path.suffix == ".toy" else 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        pass

    def channels(self) -> list[ChannelInfo]:
        return [ChannelInfo(name="toy", unit="", dtype="f8", rate_hz=1.0)]

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        yield np.zeros(1), np.zeros(1)
"""


def test_bundled_examples_plugins_directory_is_scanned() -> None:
    """BLUEPRINT Phase 5 promises the bundled directory is a plugin location."""
    from avialsync.core.registry import LoaderRegistry

    dirs = LoaderRegistry._default_plugin_dirs()

    assert any(d.parts[-2:] == ("examples", "plugins") for d in dirs), dirs


def test_frozen_bundle_resolves_plugins_from_meipass(monkeypatch, tmp_path: Path) -> None:
    """Without _MEIPASS no loose plugin can load from a PyInstaller build."""
    import avialsync.core.registry as registry_module

    monkeypatch.setattr(registry_module.sys, "_MEIPASS", str(tmp_path), raising=False)

    dirs = registry_module.LoaderRegistry._default_plugin_dirs()

    assert tmp_path / "examples" / "plugins" in dirs


def test_module_name_is_stable_across_processes(tmp_path: Path) -> None:
    """hash() is salted per process, so bundle names used to differ every launch."""
    from avialsync.core.registry import LoaderRegistry

    plugin = tmp_path / "toy.py"
    plugin.write_text(_PLUGIN_SOURCE, encoding="utf-8")

    first, first_error = LoaderRegistry._load_module(plugin)
    second, second_error = LoaderRegistry._load_module(plugin)

    assert first is not None and second is not None
    assert first_error is None and second_error is None
    assert first.__name__ == second.__name__
    # Derived from the path, so it is reproducible rather than run-dependent.
    assert first.__name__.startswith("avialsync_plugin_toy_")


def test_a_broken_plugin_is_reported_not_silently_dropped(tmp_path: Path, caplog) -> None:
    from avialsync.core.registry import LoaderRegistry

    broken = tmp_path / "broken.py"
    broken.write_text("this is not valid python(", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="avialsync.core.registry"):
        module, reason = LoaderRegistry._load_module(broken)

    assert module is None
    assert any("broken.py" in record.getMessage() for record in caplog.records)
    # The reason travels back to the caller too, so Diagnostics can show it.
    assert reason is not None and "SyntaxError" in reason


def test_a_plugin_exporting_nothing_is_reported(tmp_path: Path, caplog) -> None:
    from avialsync.core.registry import LoaderRegistry

    empty = tmp_path / "nothing.py"
    empty.write_text("VALUE = 1\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="avialsync.core.registry"):
        LoaderRegistry(plugin_dirs=[tmp_path])

    assert any("nothing.py" in record.getMessage() for record in caplog.records)


def test_builtins_are_registered_exactly_once(tmp_path: Path) -> None:
    """They are hardcoded *and* declared as entry points; that must not duplicate."""
    from avialsync.core.registry import LoaderRegistry

    loaders = LoaderRegistry(plugin_dirs=[tmp_path]).loaders()

    assert len(loaders) == len(set(loaders))


# ── A plugin may claim a whole recording folder, not only a file ─────

_FOLDER_PLUGIN = '''
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.source import ChannelInfo, TimeSeriesSource


class RigSessionSource(TimeSeriesSource):
    """Claims a directory that carries this rig's marker file."""

    @classmethod
    def can_open(cls, path: Path) -> float:
        return 1.0 if path.is_dir() and (path / "myrig.marker").exists() else 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        self._path = path

    def channels(self) -> list[ChannelInfo]:
        return [ChannelInfo(name="rig_signal", unit="V", dtype="float64", rate_hz=100.0)]

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        yield np.arange(10, dtype=np.float64) / 100.0, np.zeros(10)

    def time_bounds(self) -> tuple[float, float]:
        return (0.0, 0.1)
'''


def _rig_session(root: Path) -> tuple[Path, Path]:
    plugin_dir = root / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "rig.py").write_text(_FOLDER_PLUGIN, encoding="utf-8")

    session = root / "session_2026_08_03"
    session.mkdir()
    (session / "myrig.marker").write_text("x", encoding="utf-8")
    (session / "notes.txt").write_text("hello", encoding="utf-8")
    return plugin_dir, session


def test_a_plugin_can_claim_a_recording_folder(tmp_path: Path) -> None:
    """`can_open` is offered directories, so a lab can adopt its own folder layout.

    This is the whole reason a rig with a bespoke directory shape can be
    supported without changing AvialSync. It is easy to break by accident, since
    nothing in the loader ABC says a path might be a directory.
    """
    from avialsync.core.registry import LoaderRegistry

    plugin_dir, session = _rig_session(tmp_path)
    registry = LoaderRegistry(plugin_dirs=[plugin_dir])

    assert registry.plugin_errors == []
    chosen = registry.find_best_loader(session)
    assert chosen is not None and chosen.__name__ == "RigSessionSource"


def test_a_folder_claiming_plugin_wins_the_drop_scan(tmp_path: Path) -> None:
    """Claiming the folder must stop the scan recursing into its files.

    Otherwise the plugin is bypassed and the user gets one candidate per loose
    file — the folder's meaning, which is the point of the plugin, is lost.
    """
    from avialsync.core.registry import LoaderRegistry
    from avialsync.engine.drop_worker import DropScanWorker

    plugin_dir, session = _rig_session(tmp_path)
    worker = DropScanWorker([session], LoaderRegistry(plugin_dirs=[plugin_dir]))

    candidates = worker._collect_drop_candidates(session)

    assert len(candidates) == 1
    path, loader_cls, _config = candidates[0]
    assert path == session
    assert loader_cls is not None and loader_cls.__name__ == "RigSessionSource"


# ── Session plugins: a folder layout is pluggable, not built in ──────

_SESSION_PLUGIN = """
from pathlib import Path
from typing import Any

from avialsync.core.source import SessionItem, SessionLayout, SessionSource


class RigSession(SessionSource):
    @classmethod
    def can_open(cls, path: Path) -> float:
        return 1.0 if path.is_dir() and (path / "rig.marker").exists() else 0.0

    def scan(self, path: Path, registry: Any) -> SessionLayout:
        items = [
            SessionItem(child, registry.find_best_loader(child), {"role": "trace"})
            for child in sorted(path.glob("*.csv"))
        ]
        return SessionLayout(
            items=items, anchor_epoch=1_700_000_000.0, camera_fps=60.0, skeleton=[("a", "b")]
        )
"""


def _rig_layout(root: Path) -> tuple[Path, Path]:
    plugin_dir = root / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "rig_session.py").write_text(_SESSION_PLUGIN, encoding="utf-8")

    session = root / "rig_2026_08_03"
    session.mkdir()
    (session / "rig.marker").write_text("x", encoding="utf-8")
    for name in ("a.csv", "b.csv"):
        (session / name).write_text("time,value\n0,1\n", encoding="utf-8")
    return plugin_dir, session


def test_a_drop_in_session_plugin_is_discovered(tmp_path: Path) -> None:
    """A lab adds its own folder layout by dropping in a file — no core change."""
    from avialsync.core.registry import LoaderRegistry

    plugin_dir, session = _rig_layout(tmp_path)
    registry = LoaderRegistry(plugin_dirs=[plugin_dir])

    assert registry.plugin_errors == []
    assert [c.__name__ for c in registry.sessions() if c.__name__ == "RigSession"]
    chosen = registry.find_best_session(session)
    assert chosen is not None and chosen.__name__ == "RigSession"


def test_a_third_party_session_fans_a_folder_out(tmp_path: Path) -> None:
    """The fan-out AOL uses must be reachable by any plugin, which is the point."""
    from avialsync.core.registry import LoaderRegistry
    from avialsync.engine.drop_worker import DropScanWorker

    plugin_dir, session = _rig_layout(tmp_path)
    worker = DropScanWorker([session], LoaderRegistry(plugin_dirs=[plugin_dir]))

    candidates = worker._collect_drop_candidates(session)

    assert len(candidates) == 2, "one candidate per file the session declared"
    assert {path.name for path, _loader, _config in candidates} == {"a.csv", "b.csv"}
    assert all(config["role"] == "trace" for _p, _l, config in candidates)
    # Session-wide settings travel beside the items, not as a fake file row.
    assert worker._layout.anchor_epoch == 1_700_000_000.0
    assert worker._layout.camera_fps == 60.0
    assert all(path.exists() for path, _l, _c in candidates)


def test_a_session_plugin_that_raises_leaves_the_folder_openable(tmp_path: Path) -> None:
    """A broken session scanner must degrade to per-file scanning, not block the drop."""
    from avialsync.core.registry import LoaderRegistry
    from avialsync.engine.drop_worker import DropScanWorker

    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "bad_session.py").write_text(
        "from pathlib import Path\n"
        "from typing import Any\n"
        "from avialsync.core.source import SessionLayout, SessionSource\n"
        "\n"
        "class BadSession(SessionSource):\n"
        "    @classmethod\n"
        "    def can_open(cls, path: Path) -> float:\n"
        "        return 1.0 if path.is_dir() else 0.0\n"
        "\n"
        "    def scan(self, path: Path, registry: Any) -> SessionLayout:\n"
        "        raise RuntimeError('scanner exploded')\n",
        encoding="utf-8",
    )
    session = tmp_path / "folder"
    session.mkdir()
    (session / "a.csv").write_text("time,value\n0,1\n", encoding="utf-8")

    registry = LoaderRegistry(plugin_dirs=[plugin_dir])
    candidates = DropScanWorker([session], registry)._collect_drop_candidates(session)

    assert [path.name for path, _l, _c in candidates] == ["a.csv"]
    assert any("scan failed" in reason for _source, reason in registry.plugin_errors)
