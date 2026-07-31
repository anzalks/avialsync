"""Loaders and the importer raise typed errors, not bare builtins (V-06).

AGENTS §Coding standards: "raise typed exceptions from core/errors.py; UI layer
converts to user dialogs with actionable text". Bare `ValueError`/`KeyError`/
`RuntimeError` gave the UI nothing to branch on, so every failure surfaced as a
raw `str(e)` in a generic QMessageBox.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from avialview.core.errors import (
    AvialViewError,
    FileUnreadableError,
    LoaderContractError,
    MissingColumnError,
    SourceOpenError,
)
from avialview.engine.importer import ImportWorker
from avialview.loaders.csv_loader import CSVLoader
from avialview.loaders.video_standard import VideoStandardLoader

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "avialview"
GUARDED = ("loaders", "engine")
BARE = {"ValueError", "KeyError", "RuntimeError"}


def test_no_loader_or_importer_raises_a_bare_builtin() -> None:
    """The UI cannot turn a bare builtin into an actionable dialog."""
    offenders: list[str] = []
    for area in GUARDED:
        for path in sorted((SRC_ROOT / area).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Raise) or node.exc is None:
                    continue
                exc = node.exc
                name = (
                    exc.func.id
                    if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name)
                    else (exc.id if isinstance(exc, ast.Name) else None)
                )
                if name in BARE:
                    offenders.append(f"{path.relative_to(SRC_ROOT.parent.parent)}:{node.lineno}")

    assert not offenders, "Raise a typed error from core/errors.py instead: " + ", ".join(offenders)


def test_every_typed_error_shares_one_base() -> None:
    """One base means the UI can catch the whole family in a single handler."""
    for error in (
        FileUnreadableError,
        LoaderContractError,
        MissingColumnError,
        SourceOpenError,
    ):
        assert issubclass(error, AvialViewError)


# ── CSV ───────────────────────────────────────────────────────────────


def test_missing_time_column_names_what_is_available(tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    source.write_text("alpha,beta\n1,2\n", encoding="utf-8")

    with pytest.raises(MissingColumnError) as excinfo:
        CSVLoader().open(source, {"time_col": "timestamp", "separator": ","})

    assert excinfo.value.column == "timestamp"
    assert "alpha" in excinfo.value.available
    # The message is what reaches the dialog, so it must be actionable.
    assert "timestamp" in str(excinfo.value)
    assert "alpha" in str(excinfo.value)


def test_unreadable_csv_raises_file_unreadable(tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    source.write_bytes(b"\x00\x01\x02 not a csv \xff\xfe")

    with pytest.raises(AvialViewError):
        CSVLoader().open(source, {"time_col": "time", "separator": ","})


def test_reading_before_open_reports_the_source_is_not_open() -> None:
    with pytest.raises(SourceOpenError, match="not been opened"):
        list(CSVLoader()._read_batches())


def test_unknown_channel_reports_the_channels_that_exist(tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    source.write_text("time,alpha\n0,1\n1,2\n", encoding="utf-8")
    loader = CSVLoader()
    loader.open(source, {"time_col": "time", "separator": ",", "time_unit": "s"})

    with pytest.raises(MissingColumnError) as excinfo:
        list(loader.read_chunks("nope"))

    assert "alpha" in excinfo.value.available


# ── Video ─────────────────────────────────────────────────────────────


def test_video_media_path_before_open_is_typed() -> None:
    with pytest.raises(SourceOpenError, match="not been opened"):
        VideoStandardLoader().media_path()


# ── Importer contract ─────────────────────────────────────────────────


class _BadLoader:
    """A plugin that violates the frozen v1 bulk-ingest contract."""

    def open(self, path: Path, config: dict[str, Any]) -> None:
        pass

    def channels(self):
        from avialview.core.source import ChannelInfo

        return [
            ChannelInfo(name="a", unit="", dtype="f8", rate_hz=1.0),
            ChannelInfo(name="b", unit="", dtype="f8", rate_hz=1.0),
        ]

    def is_frame_indexed(self) -> bool:
        return False

    def read_all_chunks(self):
        yield {"a": (np.arange(4.0), np.arange(4.0))}  # "b" never delivered


def test_a_plugin_breaking_the_ingest_contract_is_named_as_such(tmp_path: Path) -> None:
    """Distinct from SourceOpenError: the fix is in the plugin, not the data."""
    source = tmp_path / "signal.dat"
    source.write_bytes(b"fixture")
    worker = ImportWorker(source, {}, _BadLoader)
    errors: list[str] = []
    worker.error.connect(errors.append)

    worker.run()

    assert errors and "every declared channel" in errors[0]


def test_loader_contract_error_is_not_a_source_open_error() -> None:
    assert not issubclass(LoaderContractError, SourceOpenError)
    assert issubclass(LoaderContractError, AvialViewError)
