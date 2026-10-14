"""A broken plugin costs its own capability, never discovery or another format."""

from __future__ import annotations

from pathlib import Path

from avialsync.core.registry import LoaderRegistry, plugin_key, plugin_setting_key
from avialsync.core.settings_schema import Setting
from tests.test_core_plugin_validation import SeriesSource


class Configured(SeriesSource):
    """Fixture settings shared by two classes of one plugin."""

    @classmethod
    def plugin_id(cls) -> str:
        return "fixture"

    @classmethod
    def settings(cls) -> tuple[Setting, ...]:
        return (Setting("folder", "Folder", "", "default", str),)


def _registry(*plugins: type) -> LoaderRegistry:
    registry = LoaderRegistry(plugin_dirs=[])
    registry._discovered = True
    registry._loaders = list(plugins)
    return registry


def test_duplicate_plugin_settings_have_one_namespace_and_disabled_plugins_are_skipped() -> None:
    class SamePlugin(Configured):
        pass

    registry = _registry(Configured, SamePlugin)
    assert len(registry.plugin_settings()) == 1
    registry.set_disabled({plugin_key(Configured), plugin_key(SamePlugin)})
    assert registry.plugin_settings() == []


def test_bad_settings_or_display_name_do_not_abort_preferences() -> None:
    class BadSettings(Configured):
        @classmethod
        def settings(cls) -> tuple:
            raise ValueError("malformed settings")

    class BadName(Configured):
        @classmethod
        def display_name(cls) -> str:
            raise ValueError("missing name")

    registry = _registry(BadSettings, BadName)
    settings = registry.plugin_settings()
    assert len(settings) == 1 and settings[0].group == "BadName"


def test_configure_failure_is_reported_without_losing_other_plugins() -> None:
    class BadConfig(Configured):
        @classmethod
        def configure(cls, values: dict) -> None:
            raise ValueError("bad configuration")

    registry = _registry(BadConfig)
    registry.configure_plugins({plugin_setting_key(BadConfig, "folder"): "chosen"})
    assert any("configure raised ValueError" in reason for name, reason in registry.plugin_errors)


def test_a_broken_sniffer_does_not_hide_another_format(tmp_path: Path) -> None:
    class Broken(SeriesSource):
        @classmethod
        def can_open(cls, path: Path) -> float:
            raise ValueError("bad signature")

    registry = _registry(Broken, SeriesSource)
    assert registry.find_best_loader(tmp_path / "data") is SeriesSource
    assert any("can_open raised ValueError" in reason for name, reason in registry.plugin_errors)
    assert registry.tied_loaders(tmp_path / "pose_csv_avialfix.csv") == []


def test_metadata_snapshot_is_reused_and_failed_warmup_is_logged(monkeypatch, caplog) -> None:
    registry = LoaderRegistry(plugin_dirs=[])
    registry._entry_points = {}
    registry._snapshot_entry_points()

    def fail() -> None:
        raise OSError("dependency unavailable")

    monkeypatch.setattr(registry, "ensure_discovered", fail)
    registry._warm()
    assert "Plugin discovery failed during warm-up" in caplog.text


def test_abstract_drop_in_classes_are_not_admitted(tmp_path: Path, monkeypatch) -> None:
    plugin = tmp_path / "incomplete.py"
    plugin.write_text(
        "from avialsync.core.source import TimeSeriesSource\n"
        "class Incomplete(TimeSeriesSource):\n    pass\n",
        encoding="utf-8",
    )
    registry = LoaderRegistry(plugin_dirs=[tmp_path])
    assert not any(cls.__name__ == "Incomplete" for cls in registry.loaders())
