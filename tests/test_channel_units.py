"""Loaders' units reach the plot labels, also from an older cache (D-186)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from avialsync.core.cache import cache_dir_for
from avialsync.core.inspection import SourceInspection
from avialsync.core.source import ChannelInfo
from avialsync.engine.importer import ImportWorker


class _EphysLoader:
    """Two channels that say what they measure, the way an ephys format does."""

    open_calls = 0

    def open(self, _path: Path, _config: dict[str, object]) -> None:
        type(self).open_calls += 1

    def channels(self) -> list[ChannelInfo]:
        return [
            ChannelInfo("CH1", "µV", "Float64", 1000.0),
            ChannelInfo("sync", "", "Float64", 1000.0),
        ]

    def read_all_chunks(self):
        times = np.linspace(0.0, 1.0, 50)
        yield {"CH1": (times, np.sin(times)), "sync": (times, np.zeros_like(times))}

    def is_frame_indexed(self) -> bool:
        return False


def _run(source: Path) -> SourceInspection:
    done: list[tuple[object, ...]] = []
    worker = ImportWorker(source, {}, _EphysLoader)
    worker.finished.connect(lambda *args: done.append(args))
    worker.run()
    assert done, "the import finished"
    inspection = done[-1][4]
    assert isinstance(inspection, SourceInspection)
    return inspection


def test_declared_units_ride_the_inspection(tmp_path: Path) -> None:
    source = tmp_path / "rec.dat"
    source.write_text("bytes", encoding="utf-8")
    _EphysLoader.open_calls = 0
    inspection = _run(source)
    assert inspection.channel_units == {"CH1": "µV"}, "a channel with no unit is left out"
    assert inspection.units() == {"CH1": "µV"}


def test_a_cache_from_before_units_is_backfilled_once(tmp_path: Path) -> None:
    source = tmp_path / "rec.dat"
    source.write_text("bytes", encoding="utf-8")
    _EphysLoader.open_calls = 0
    _run(source)
    manifest = cache_dir_for(source) / "import.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["inspection"].pop("channel_units")  # as a manifest written before D-186
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    assert _run(source).channel_units == {"CH1": "µV"}
    assert _EphysLoader.open_calls == 2, "the names were read, once"
    assert _run(source).channel_units == {"CH1": "µV"}
    assert _EphysLoader.open_calls == 2, "and recorded, so the next open reads the cache"


def test_a_unit_set_at_import_wins_over_the_declared_one() -> None:
    inspection = SourceInspection(
        path="/rec.dat",
        channel_units={"CH1": "µV", "CH2": "µV"},
        import_config={"units": {"CH1": "mV", "CH3": "N"}},
    )
    assert inspection.units() == {"CH1": "mV", "CH2": "µV", "CH3": "N"}
    assert SourceInspection.from_dict(inspection.as_dict()).channel_units == {
        "CH1": "µV",
        "CH2": "µV",
    }
    assert SourceInspection.from_dict({"path": "/old"}).channel_units is None


def test_every_row_gets_its_unit_even_when_built_after_the_units_arrive(
    qtbot, tmp_path: Path
) -> None:
    """Only CH1 showed µV: units were applied to the rows built so far.

    Rows are built in slices across event-loop turns, and the import's units
    arrive once, after the first slice. Every later row must still get its own.
    """
    from avialsync.core.channel_reader import ChannelKey
    from avialsync.core.pyramid import PyramidBuilder
    from avialsync.ui.plot_pane import PlotPane

    cache = tmp_path / "ephys_cache"
    cache.mkdir()
    times = np.linspace(0.0, 1.0, 400)
    names = [f"CH{index}" for index in range(1, 33)]
    for index, name in enumerate(names):
        PyramidBuilder(cache, name).build_and_save(times, np.sin(times * (index + 1)))
    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(900, 600)
    pane.load_channels(cache, names, source_id="/rec/ephys")
    pane.set_channel_units({ChannelKey("/rec/ephys", name): "µV" for name in names})
    pane.wait_for_pending_rows()

    assert len(pane.channels) == len(names)
    for channel in pane.channels:
        label = channel.plot_item.getAxis("left").labelText
        assert "(µV)" in label, f"{channel.name} lost its unit"


def test_one_spelling_for_every_source() -> None:
    from avialsync.core.source import display_unit

    assert display_unit("uV") == "µV"
    assert display_unit("µV") == "µV"
    assert display_unit(" mV ") == "mV"
    assert display_unit("dimensionless") == ""
    assert display_unit("deg") == "deg"
