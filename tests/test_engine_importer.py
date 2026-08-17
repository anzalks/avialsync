"""Tests for the asynchronous time-series import pipeline."""

from pathlib import Path

import numpy as np

from avialsync.core.inspection import SourceInspection
from avialsync.core.messages import Message
from avialsync.core.source import ChannelInfo
from avialsync.engine.importer import ImportWorker


class _BulkLoader:
    """One-pass test loader whose legacy per-channel API must never be used."""

    open_calls = 0
    bulk_calls = 0

    def open(self, _path: Path, _config: dict[str, object]) -> None:
        type(self).open_calls += 1

    def channels(self) -> list[ChannelInfo]:
        return [
            ChannelInfo("left", "", "Float64", None),
            ChannelInfo("right", "", "Float64", None),
        ]

    def read_all_chunks(self):
        type(self).bulk_calls += 1
        yield {
            "left": (np.array([0.0, 1.0]), np.array([1.0, 2.0])),
            "right": (np.array([0.0, 1.0]), np.array([3.0, 4.0])),
        }
        yield {
            "left": (np.array([2.0]), np.array([5.0])),
            "right": (np.array([2.0]), np.array([6.0])),
        }

    def read_chunks(self, _channel: str):
        raise AssertionError("The importer must use the optimized one-pass API.")

    def is_frame_indexed(self) -> bool:
        return False


def test_import_worker_commits_cache_without_reopening_mmap(tmp_path: Path, monkeypatch) -> None:
    """Bounds come from parsed data, so Windows can atomically rename the cache."""
    source = tmp_path / "signal.csv"
    source.write_text("time,value\n0.0,1.0\n0.5,2.0\n1.0,3.0\n", encoding="utf-8")

    def fail_if_opened(*_args, **_kwargs) -> None:
        raise AssertionError("The temporary cache must not be reopened before commit.")

    monkeypatch.setattr("avialsync.core.pyramid.PyramidReader", fail_if_opened)
    worker = ImportWorker(source, {"time_col": "time", "time_unit": "s", "separator": ","})
    completed: list[tuple[object, ...]] = []
    errors: list[str] = []
    worker.finished.connect(lambda *args: completed.append(args))
    worker.error.connect(errors.append)

    worker.run()

    assert errors == []
    assert len(completed) == 1
    assert completed[0][3] == (0.0, 1.0)
    assert (tmp_path / "signal.csv.avialcache" / "meta.json").exists()


def test_import_worker_uses_one_bulk_parse_then_reuses_valid_cache(tmp_path: Path) -> None:
    source = tmp_path / "signal.csv"
    source.write_text("source bytes", encoding="utf-8")
    _BulkLoader.open_calls = 0
    _BulkLoader.bulk_calls = 0
    config: dict[str, object] = {"timezone": "UTC"}

    first = ImportWorker(source, config, _BulkLoader)
    completed: list[tuple[object, ...]] = []
    first.finished.connect(lambda *args: completed.append(args))
    first.run()

    assert len(completed) == 1
    assert _BulkLoader.open_calls == 1
    assert _BulkLoader.bulk_calls == 1
    cache_dir = tmp_path / "signal.csv.avialcache"
    assert (cache_dir / "import.json").exists()

    second = ImportWorker(source, config, _BulkLoader)
    second.finished.connect(lambda *args: completed.append(args))
    second.run()

    assert len(completed) == 2
    assert _BulkLoader.open_calls == 1
    assert _BulkLoader.bulk_calls == 1
    assert completed[-1][2] == ["left", "right"]
    assert completed[-1][3] == (0.0, 2.0)


def test_import_cache_key_includes_accepted_loader_configuration(tmp_path: Path) -> None:
    source = tmp_path / "signal.csv"
    source.write_text("source bytes", encoding="utf-8")
    _BulkLoader.open_calls = 0
    _BulkLoader.bulk_calls = 0

    first = ImportWorker(source, {"timezone": "UTC"}, _BulkLoader)
    first.run()
    changed = ImportWorker(source, {"timezone": "Europe/Paris"}, _BulkLoader)
    changed.run()

    assert _BulkLoader.open_calls == 2
    assert _BulkLoader.bulk_calls == 2


class _TalkativeLoader(_BulkLoader):
    """A loader that also carries what the experimenter typed during recording."""

    def messages(self) -> list[Message]:
        return [
            Message(text="stimulus on", time=1.0, channel="MessageCenter"),
            Message(text="see notebook p.42"),
        ]


class _SulkyLoader(_BulkLoader):
    """A third-party loader whose message reader is broken."""

    def messages(self) -> list[Message]:
        raise RuntimeError("plugin bug")


def test_messages_survive_the_sidecar_so_a_cache_hit_still_has_them(tmp_path: Path) -> None:
    """On a cache hit the loader is never opened, so the manifest must carry them.

    Without this, a recording's notes appear on first import and vanish on every
    launch afterwards — the worst possible failure, because it looks like the
    data changed.
    """
    source = tmp_path / "signal.csv"
    source.write_text("source bytes", encoding="utf-8")
    _TalkativeLoader.open_calls = 0

    completed: list[tuple[object, ...]] = []
    first = ImportWorker(source, {}, _TalkativeLoader)
    first.finished.connect(lambda *args: completed.append(args))
    first.run()

    second = ImportWorker(source, {}, _TalkativeLoader)
    second.finished.connect(lambda *args: completed.append(args))
    second.run()

    assert _TalkativeLoader.open_calls == 1, "second import must come from cache"
    for attempt in completed:
        inspection = attempt[4]
        assert isinstance(inspection, SourceInspection)
        # Untimed first, then by time — and the untimed one keeps its missing time.
        assert [m.text for m in inspection.messages] == ["see notebook p.42", "stimulus on"]
        assert inspection.messages[0].time is None
        assert inspection.messages[1].time == 1.0


def test_a_broken_message_reader_does_not_fail_the_import(tmp_path: Path) -> None:
    """Losing the samples fails an import; losing a comment must not."""
    source = tmp_path / "signal.csv"
    source.write_text("source bytes", encoding="utf-8")

    completed: list[tuple[object, ...]] = []
    errors: list[str] = []
    worker = ImportWorker(source, {}, _SulkyLoader)
    worker.finished.connect(lambda *args: completed.append(args))
    worker.error.connect(errors.append)
    worker.run()

    assert errors == []
    assert len(completed) == 1
    assert completed[0][4].messages == ()
