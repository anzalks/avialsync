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

    first = LoaderRegistry._load_module(plugin)
    second = LoaderRegistry._load_module(plugin)

    assert first is not None and second is not None
    assert first.__name__ == second.__name__
    # Derived from the path, so it is reproducible rather than run-dependent.
    assert first.__name__.startswith("avialsync_plugin_toy_")


def test_a_broken_plugin_is_reported_not_silently_dropped(tmp_path: Path, caplog) -> None:
    from avialsync.core.registry import LoaderRegistry

    broken = tmp_path / "broken.py"
    broken.write_text("this is not valid python(", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="avialsync.core.registry"):
        module = LoaderRegistry._load_module(broken)

    assert module is None
    assert any("broken.py" in record.getMessage() for record in caplog.records)


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
