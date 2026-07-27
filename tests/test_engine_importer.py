"""Tests for the asynchronous time-series import pipeline."""

from pathlib import Path

from avialview.engine.importer import ImportWorker


def test_import_worker_commits_cache_without_reopening_mmap(tmp_path: Path, monkeypatch) -> None:
    """Bounds come from parsed data, so Windows can atomically rename the cache."""
    source = tmp_path / "signal.csv"
    source.write_text("time,value\n0.0,1.0\n0.5,2.0\n1.0,3.0\n", encoding="utf-8")

    def fail_if_opened(*_args, **_kwargs) -> None:
        raise AssertionError("The temporary cache must not be reopened before commit.")

    monkeypatch.setattr("avialview.core.pyramid.PyramidReader", fail_if_opened)
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
