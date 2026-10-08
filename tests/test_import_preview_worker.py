"""The import wizard never reads a full recording on the UI thread."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from avialsync.engine.import_preview_worker import PREVIEW_BYTES, ImportPreviewWorker
from avialsync.ui.import_wizard import ImportWizard


def test_preview_worker_reads_only_the_prefix(tmp_path: Path) -> None:
    source = tmp_path / "large.csv"
    source.write_bytes(b"time,value\n" + b"x" * (PREVIEW_BYTES * 4))
    results: list[bytes] = []
    worker = ImportPreviewWorker(source)
    worker.finished.connect(results.append)

    worker.run()

    assert len(results) == 1
    assert len(results[0]) == PREVIEW_BYTES
    assert results[0].startswith(b"time,value\n")


def test_wizard_constructs_from_supplied_bytes_without_opening_file(
    qapp: QApplication, qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "missing.csv"

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Wizard construction must not read the source")

    monkeypatch.setattr(Path, "open", refuse)
    wizard = ImportWizard(source, b"time,value\n0,1\n")
    qtbot.addWidget(wizard)

    assert wizard.config()["time_col"] == "time"
