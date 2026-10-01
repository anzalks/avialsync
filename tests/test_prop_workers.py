"""Background sidecar workers report failures without replacing other evidence."""

from __future__ import annotations

from pathlib import Path

from avialsync.core.physical_props import Ladder
from avialsync.core.prop_file import prop_path
from avialsync.engine import prop_file_worker
from avialsync.engine.prop_file_worker import PropFileReadWorker, PropFileWriteWorker


def test_read_worker_reports_io_failure_without_a_partial_success(
    monkeypatch, tmp_path: Path
) -> None:
    def failed_read(_folder: Path):
        raise OSError("folder became unavailable")

    monkeypatch.setattr(prop_file_worker, "read_props", failed_read)
    worker = PropFileReadWorker(tmp_path)
    finished: list[object] = []
    errors: list[str] = []
    worker.finished.connect(lambda *_args: finished.append(True))
    worker.error.connect(errors.append)
    worker.run()
    assert finished == []
    assert errors == ["folder became unavailable"]


def test_write_worker_refuses_to_replace_an_existing_prop_record(tmp_path: Path) -> None:
    record = prop_path(tmp_path, "shared")
    record.write_text("existing prop evidence", encoding="utf-8")
    worker = PropFileWriteWorker(tmp_path, "shared", Ladder("shared"))
    finished: list[object] = []
    errors: list[str] = []
    worker.finished.connect(finished.append)
    worker.error.connect(errors.append)
    worker.run()
    assert finished == []
    assert len(errors) == 1 and "prop file" in errors[0]
    assert record.read_text(encoding="utf-8") == "existing prop evidence"
