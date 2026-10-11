"""Plugin API v2 (D-220): versions, drop-in packages, ties, switches, settings, checks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from avialsync.core.plugin_check import check_path
from avialsync.core.registry import LoaderRegistry, plugin_key
from avialsync.core.source import (
    ChannelInfo,
    LoadedSource,
    PartnerSearch,
    SessionItem,
    SessionLayout,
    SessionSource,
)

_LOADER = """
from collections.abc import Iterator
import numpy as np
from avialsync.core.source import ChannelInfo, TimeSeriesSource


class {name}(TimeSeriesSource):
    {extra}
    @classmethod
    def can_open(cls, path):
        return 0.7 if path.suffix == ".tie" else 0.0

    def open(self, path, config):
        self.path = path

    def channels(self):
        return [ChannelInfo("ttl", "V", "float64", 10.0, trigger="sync_train")]

    def read_chunks(self, ch) -> Iterator:
        yield np.arange(5.0), np.zeros(5)
"""


def _write(folder: Path, name: str, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_plugin_for_another_api_version_is_refused_with_a_reason(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    _write(plugins, "old.py", _LOADER.format(name="OldReader", extra="api_version = 1"))
    registry = LoaderRegistry(plugin_dirs=[plugins])
    assert "OldReader" not in {cls.__name__ for cls in registry.loaders()}
    assert any("plugin API 1" in reason for _name, reason in registry.plugin_errors)


def test_a_package_folder_is_a_drop_in_and_lib_is_importable(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    _write(plugins / "lib" / "helperlib_v2test", "__init__.py", "VALUE = 3\n")
    _write(plugins / "rigpkg", "__init__.py", "from .reader import PackagedReader\n")
    _write(
        plugins / "rigpkg",
        "reader.py",
        "import helperlib_v2test\n" + _LOADER.format(name="PackagedReader", extra=""),
    )
    try:
        registry = LoaderRegistry(plugin_dirs=[plugins])
        assert registry.plugin_errors == []
        assert "PackagedReader" in {cls.__name__ for cls in registry.loaders()}
        found = [entry for entry in registry.plugins() if entry[1].__name__ == "PackagedReader"]
        (_kind, cls, origin) = found[0]
        assert origin == "drop-in rigpkg"
        assert plugin_key(cls) == "drop-in.rigpkg.reader:PackagedReader"
    finally:
        sys.path.remove(str(plugins / "lib"))


def test_equal_scores_are_reported_as_a_tie_and_a_switched_off_plugin_is_never_asked(
    tmp_path: Path,
) -> None:
    plugins = tmp_path / "plugins"
    _write(plugins, "a.py", _LOADER.format(name="FirstReader", extra=""))
    _write(plugins, "b.py", _LOADER.format(name="SecondReader", extra=""))
    registry = LoaderRegistry(plugin_dirs=[plugins])
    data = tmp_path / "x.tie"
    tied = {cls.__name__ for cls in registry.tied_loaders(data)}
    assert tied == {"FirstReader", "SecondReader"}
    first = registry.find_best_loader(data)
    assert first is not None
    registry.set_disabled({plugin_key(first)})
    assert registry.tied_loaders(data) == []
    chosen = registry.find_best_loader(data)
    assert chosen is not None and chosen is not first
    assert first not in registry.loaders()


def test_reload_picks_up_a_file_dropped_in_after_startup(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    registry = LoaderRegistry(plugin_dirs=[plugins])
    assert registry.find_best_loader(tmp_path / "x.tie") is None
    generation = registry.generation
    _write(plugins, "late.py", _LOADER.format(name="LateReader", extra=""))
    registry.reload()
    assert registry.generation > generation
    found = registry.find_best_loader(tmp_path / "x.tie")
    assert found is not None and found.__name__ == "LateReader"


class _Configured(SessionSource):
    received: dict = {}

    @classmethod
    def plugin_id(cls) -> str:
        return "myrig"

    @classmethod
    def settings(cls):
        from avialsync.core.settings_schema import Setting

        return (Setting("data_folder", "Data folder", "", "", str),)

    @classmethod
    def configure(cls, values) -> None:
        cls.received = dict(values)

    @classmethod
    def can_open(cls, path: Path) -> float:
        return 0.0

    def scan(self, path: Path, registry) -> SessionLayout:
        return SessionLayout()


def test_plugin_settings_are_namespaced_grouped_and_delivered() -> None:
    registry = LoaderRegistry(plugin_dirs=[])
    registry.ensure_discovered()
    registry._sessions.append(_Configured)
    declared = {setting.key: setting for setting in registry.plugin_settings()}
    assert declared["plugins/myrig/data_folder"].group == _Configured.display_name()
    # AOL declares its own, with the keys earlier releases stored them under.
    assert declared["plugins/aol/saved_data_folder"].legacy_key == "aol/saved_data_folder"
    registry.configure_plugins({"plugins/myrig/data_folder": "/data"})
    assert _Configured.received == {"data_folder": "/data"}


def test_the_default_partner_targets_are_the_loaded_source_at_its_path() -> None:
    match = PartnerSearch(Path("/rec/b"), "found")
    loaded = [LoadedSource("/rec/a"), LoadedSource(str(Path("/rec/b")))]
    assert _Configured.partner_targets(match, loaded) == [(str(Path("/rec/b")), 0.0)]
    assert _Configured.find_partner(0.0).path is None


_BAD_SESSION = """
from pathlib import Path
from avialsync.core.source import SessionItem, SessionLayout, SessionSource


class RelativeEpochSession(SessionSource):
    @classmethod
    def can_open(cls, path):
        return 1.0 if (path / "rig.marker").exists() else 0.0

    def scan(self, path, registry):
        return SessionLayout(
            items=[SessionItem(path / "rig.marker", None, source_epoch=34526.0)],
            segments=[(1.7e9, 1.7e9 + 10, "t1"), (1.7e9 + 5, 1.7e9 + 20, "t2")],
        )
"""


def test_plugin_check_names_a_relative_epoch_and_overlapping_trials(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    _write(plugins, "bad.py", _BAD_SESSION)
    recording = tmp_path / "rec"
    _write(recording, "rig.marker", "x")
    report = check_path(LoaderRegistry(plugin_dirs=[plugins]), recording)
    assert not report.ok
    text = report.text()
    assert "source_epoch 34526.0 is not an absolute instant" in text
    assert "starts inside the trial before it" in text


def test_a_declared_trigger_line_survives_the_import_manifest() -> None:
    from avialsync.core.inspection import SourceInspection
    from avialsync.engine.importer import _declared_triggers

    channels = [
        ChannelInfo("strobe", "V", "float64", 1000.0, trigger="frame_strobe", trigger_for="cam1"),
        ChannelInfo("ecg", "V", "float64", 1000.0),
    ]
    triggers = _declared_triggers(channels)
    assert triggers == {"strobe": ("frame_strobe", "cam1")}
    inspection = SourceInspection(path="x", loader_id="y", channel_triggers=triggers)
    assert SourceInspection.from_dict(inspection.as_dict()).channel_triggers == triggers


def test_a_tied_file_starts_unchosen_in_the_review(qapp, tmp_path: Path) -> None:
    from avialsync.engine.drop_worker import TIED_KEY
    from avialsync.ui.batch_import_dialog import BatchImportDialog

    registry = LoaderRegistry(plugin_dirs=[])
    loader = registry.loaders()[0]
    data = tmp_path / "x.csv"
    dialog = BatchImportDialog([(data, loader, {TIED_KEY: ["A", "B"]})], registry=registry)
    assert dialog._combos[0].currentIndex() == 0
    assert "Choose one" in dialog._combos[0].toolTip()


@pytest.mark.parametrize("pairing", [True, False])
def test_a_layout_that_offers_pairing_enables_the_search(qapp, pairing: bool) -> None:
    from avialsync.core.source import PairingHint
    from avialsync.ui.controllers.drop_controller import _remember_pairing
    from avialsync.ui.controllers.session_state import SessionRuntimeState

    class Window:
        session_runtime = SessionRuntimeState()

    hint = PairingHint(1.7e9, _Configured) if pairing else None
    layout = SessionLayout(items=[SessionItem(Path("cam.mp4"), None, kind="video")], pairing=hint)
    window = Window()
    window.session_runtime.pairing = PairingHint(1.0, _Configured)
    _remember_pairing(window, layout)  # type: ignore[arg-type]
    assert window.session_runtime.pairing == hint


def _tutorial_recording(root: Path) -> Path:
    """Generated example data for the tutorial plugin: two trials, a gap between."""
    recording = root / "my_recording"
    _write(recording, "rig.json", "{}")
    for name, start in (("trial_001", 1_700_000_000.0), ("trial_002", 1_700_000_030.0)):
        _write(
            recording / name,
            "trial.json",
            f'{{"start_unix": {start}, "duration_s": 10.0}}',
        )
        rows = "\n".join(f"{t / 10:.1f},{t % 2},{t * 0.5}" for t in range(100))
        _write(recording / name, "daq.csv", "time,cam_strobe,wheel\n" + rows + "\n")
    return recording


def test_the_tutorial_trial_plugin_lays_out_its_rig_and_passes_the_check(
    tmp_path: Path,
) -> None:
    import shutil

    from avialsync.loaders.joined_parts import JoinedTimeSeriesSource

    plugins = tmp_path / "plugins"
    plugins.mkdir()
    tutorial = Path(__file__).parents[1] / "examples" / "plugin_tutorials" / "trial_folder.py"
    shutil.copy(tutorial, plugins / "trial_folder.py")
    recording = _tutorial_recording(tmp_path)
    registry = LoaderRegistry(plugin_dirs=[plugins])
    assert registry.plugin_errors == []

    session = registry.find_best_session(recording)
    assert session is not None and session.display_name() == "Trial Folder Rig"
    layout = session().scan(recording, registry)
    assert layout.session_epoch == 1_700_000_000.0
    assert [name for _start, _end, name in layout.segments] == ["trial_001", "trial_002"]
    (daq,) = layout.items
    assert daq.loader is JoinedTimeSeriesSource
    assert [part["start"] for part in daq.config["parts"]] == [0.0, 30.0]

    report = check_path(registry, recording)
    assert report.ok, report.text()

    joined = JoinedTimeSeriesSource()
    joined.open(daq.path, daq.config)
    strobe = next(c for c in joined.channels() if c.name == "cam_strobe")
    assert strobe.trigger == "frame_strobe"
