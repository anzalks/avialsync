from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import avialsync.core.registry as registry_module
from avialsync.core.registry import LoaderRegistry
from avialsync.core.source import TimeSeriesSource, VideoSource


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


def test_legacy_video_plugin_receives_default_metadata() -> None:
    """The additive inspection API must not add an abstract plugin requirement."""
    metadata = DummyVideoLoader().video_metadata()

    assert metadata.nominal_fps == 30.0
    assert metadata.measured_fps == 30.0
    assert metadata.duration == 1.0


@patch("avialsync.core.registry.entry_points")
def test_loader_discovery(mock_eps):
    # Mock entry points return
    ep1 = MagicMock()
    ep1.load.return_value = DummyTimeSeriesLoader

    ep2 = MagicMock()
    ep2.load.return_value = DummyVideoLoader

    mock_eps.return_value = [ep1, ep2]

    registry = LoaderRegistry()
    # Expect 6 built-in + 2 from entry points
    assert len(registry._loaders) == 8
    assert DummyTimeSeriesLoader in registry._loaders
    assert DummyVideoLoader in registry._loaders

    # Test best loader routing
    best_ts = registry.find_best_loader(Path("data.dummy_ts"))
    assert best_ts is DummyTimeSeriesLoader

    best_vid = registry.find_best_loader(Path("movie.dummy_vid"))
    assert best_vid is DummyVideoLoader

    best_none = registry.find_best_loader(Path("unknown.xyz"))
    assert best_none is None


# ── Broken plugins must be visible, not merely absent (5.4) ──────────

_DROP_IN_SOURCE = """
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.source import ChannelInfo, TimeSeriesSource


class DropInSource(TimeSeriesSource):
    @classmethod
    def can_open(cls, path: Path) -> float:
        return 1.0 if path.suffix == ".dropin" else 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        self._path = path

    def channels(self) -> list[ChannelInfo]:
        return [ChannelInfo(name="v", unit="", dtype="float64", rate_hz=None)]

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        yield np.arange(3, dtype=np.float64), np.zeros(3)

    def time_bounds(self) -> tuple[float, float]:
        return (0.0, 2.0)
"""


def test_drop_in_plugin_is_discovered_and_routed(tmp_path: Path) -> None:
    """The `~/.avialsync/plugins/` drop-in path is a supported way to add a format."""
    (tmp_path / "good_plugin.py").write_text(_DROP_IN_SOURCE)

    registry = LoaderRegistry(plugin_dirs=[tmp_path])

    assert registry.plugin_errors == []
    assert registry.find_best_loader(Path("x.dropin")) is not None


def test_a_plugin_that_fails_to_import_is_reported(tmp_path: Path) -> None:
    """A broken plugin is otherwise indistinguishable from one never installed.

    Its formats simply stop appearing. The registry must be able to say why, or
    the Diagnostics report has nothing to show the person who installed it.
    """
    (tmp_path / "broken_plugin.py").write_text("import a_module_that_does_not_exist\n")

    registry = LoaderRegistry(plugin_dirs=[tmp_path])

    assert len(registry.plugin_errors) == 1
    source, reason = registry.plugin_errors[0]
    assert source == "broken_plugin.py"
    assert "a_module_that_does_not_exist" in reason


def test_a_plugin_exporting_no_source_is_reported(tmp_path: Path) -> None:
    """Importable but useless is still a failure the author needs told about."""
    (tmp_path / "empty_plugin.py").write_text("class NotASource:\n    pass\n")

    registry = LoaderRegistry(plugin_dirs=[tmp_path])

    assert len(registry.plugin_errors) == 1
    assert "no TimeSeriesSource, VideoSource, or SessionSource" in registry.plugin_errors[0][1]


def test_a_broken_plugin_does_not_cost_the_built_ins(tmp_path: Path) -> None:
    """One bad plugin must never take the application's own loaders with it."""
    (tmp_path / "broken_plugin.py").write_text("raise RuntimeError('boom at import')\n")

    registry = LoaderRegistry(plugin_dirs=[tmp_path])

    assert len(registry.loaders()) == 6
    assert registry.find_best_loader(Path("data.csv")) is not None


def test_a_built_in_loader_that_will_not_import_is_reported_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A built-in's dependency stack belongs to the user's machine, not to us.

    ``NeoLoader`` imports ``neo``, which imports ``quantities``, which reads an
    attribute NumPy 2 removed. On a Windows box whose per-user site-packages
    shadowed the environment that raised ``AttributeError`` at import — and
    because ``LoaderRegistry`` is built inside ``MainWindow.__init__``, the
    application died before showing a window instead of losing one format.
    """
    monkeypatch.setattr(
        registry_module,
        "_BUILTIN_LOADERS",
        (
            ("avialsync.loaders.csv_loader", "CSVLoader"),
            ("avialsync.loaders.no_such_loader", "MissingModuleLoader"),
            ("avialsync.loaders.csv_loader", "NoSuchClass"),
        ),
    )

    registry = LoaderRegistry(plugin_dirs=[tmp_path])

    # The healthy built-in still loads, and the two broken ones are named.
    assert registry.find_best_loader(Path("data.csv")) is not None
    assert dict(registry.plugin_errors).keys() == {"MissingModuleLoader", "NoSuchClass"}
    assert "ModuleNotFoundError" in dict(registry.plugin_errors)["MissingModuleLoader"]
    assert "AttributeError" in dict(registry.plugin_errors)["NoSuchClass"]


def test_a_broken_built_in_session_scanner_leaves_the_loaders_working(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Session scanning and per-file loading fail independently.

    The built-in list is only the fallback for a checkout whose entry points are
    not installed, so an installed ``avialsync.sessions`` entry point still
    supplies the scanner here. What must hold either way is that the failure is
    named rather than raised, and that it costs the loaders nothing.
    """
    monkeypatch.setattr(
        registry_module,
        "_BUILTIN_SESSIONS",
        (("avialsync.loaders.no_such_session", "MissingSessionSource"),),
    )

    registry = LoaderRegistry(plugin_dirs=[tmp_path])

    assert len(registry.loaders()) == 6
    assert registry.plugin_errors[0][0] == "MissingSessionSource"
